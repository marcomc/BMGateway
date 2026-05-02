#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bootstrap-install.sh --repo-url <repo-url> [options]

Options:
  --repo-dir <path>               Checkout path. Default: $HOME/BMGateway
  --ref <git-ref>                 Optional branch, tag, or commit to checkout after update
  --hostname <name>               Set the Pi hostname before finishing install
  --disable-web                   Do not enable the management web service
  --disable-home-assistant        Disable MQTT and Home Assistant in the installed config
  --enable-glances                Install and enable a Glances API service for Home Assistant
  --enable-cockpit                Install and enable Cockpit on HTTPS port 9090
  --skip-usb-otg-tools            Do not install USB-OTG image-export helper packages
  --service-user <name>           User that owns the services and config. Default: current user
  --skip-apt                      Skip apt package installation
  --skip-uv                       Skip uv bootstrap
  --skip-services                 Skip systemd service installation and startup
  --web-port <port>               Management web port. Default: 80
  --glances-port <port>           Glances API port. Default: 61208
  --help                          Show this help text
EOF
}

repo_url=""
script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
script_repo_dir="$(CDPATH='' cd -- "${script_dir}/.." && pwd)"
repo_dir="${HOME}/BMGateway"
git_ref=""
service_user="$(id -un)"
skip_apt=0
skip_uv=0
install_services=1
enable_web=1
enable_home_assistant=1
enable_glances=0
enable_cockpit=0
install_usb_otg_tools=1
web_port="80"
glances_port="61208"
hostname_override=""

set_system_hostname() {
  local requested_hostname="$1"
  local current_hostname

  if [[ -z "${requested_hostname}" ]]; then
    return
  fi

  current_hostname="$(hostname)"
  if [[ "${requested_hostname}" == "${current_hostname}" ]]; then
    return
  fi

  sudo hostnamectl set-hostname "${requested_hostname}"

  if sudo test -f /etc/hosts; then
    sudo python3 - <<'PY' "${requested_hostname}"
from pathlib import Path
import sys

hostname = sys.argv[1]
hosts_path = Path("/etc/hosts")
lines = hosts_path.read_text(encoding="utf-8").splitlines()
updated: list[str] = []
replaced = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("127.0.1.1"):
        updated.append(f"127.0.1.1\t{hostname}")
        replaced = True
    else:
        updated.append(line)

if not replaced:
    updated.append(f"127.0.1.1\t{hostname}")

hosts_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
  fi
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --repo-url)
      repo_url="${2:?missing value for --repo-url}"
      shift 2
      ;;
    --repo-dir)
      repo_dir="${2:?missing value for --repo-dir}"
      shift 2
      ;;
    --ref)
      git_ref="${2:?missing value for --ref}"
      shift 2
      ;;
    --hostname)
      hostname_override="${2:?missing value for --hostname}"
      shift 2
      ;;
    --skip-apt)
      skip_apt=1
      shift
      ;;
    --skip-uv)
      skip_uv=1
      shift
      ;;
    --skip-services)
      install_services=0
      shift
      ;;
    --disable-web)
      enable_web=0
      shift
      ;;
    --disable-home-assistant)
      enable_home_assistant=0
      shift
      ;;
    --enable-glances)
      enable_glances=1
      shift
      ;;
    --enable-cockpit)
      enable_cockpit=1
      shift
      ;;
    --skip-usb-otg-tools)
      install_usb_otg_tools=0
      shift
      ;;
    --service-user)
      service_user="${2:?missing value for --service-user}"
      shift 2
      ;;
    --web-port)
      web_port="${2:?missing value for --web-port}"
      shift 2
      ;;
    --glances-port)
      glances_port="${2:?missing value for --glances-port}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

export PATH="${HOME}/.local/bin:${PATH}"

if [[ -e "${script_repo_dir}/.git" ]] && [[ "${repo_dir}" = "${HOME}/BMGateway" ]]; then
  repo_dir="${script_repo_dir}"
fi

if [[ -z "${repo_url}" ]] && [[ ! -e "${repo_dir}/.git" ]]; then
  printf 'Missing required --repo-url argument\n' >&2
  usage >&2
  exit 1
fi

if [[ "${skip_apt}" -eq 0 ]]; then
  sudo apt-get update
  apt_packages=(
    bluetooth
    bluez
    ca-certificates
    curl
    git
    make
    python3
    python3-venv
  )
  if [[ "${install_usb_otg_tools}" -eq 1 ]]; then
    apt_packages+=(chromium dosfstools kmod libjpeg-dev python3-dev util-linux zlib1g-dev)
  fi
  if [[ "${enable_glances}" -eq 1 ]]; then
    apt_packages+=(glances)
  fi
  if [[ "${enable_cockpit}" -eq 1 ]]; then
    apt_packages+=(cockpit)
  fi
  sudo apt-get install -y "${apt_packages[@]}"
fi

set_system_hostname "${hostname_override}"

if [[ "${skip_uv}" -eq 0 ]] && ! command -v uv >/dev/null 2>&1; then
  installer_dir="$(mktemp -d)"
  trap 'rm -rf "${installer_dir}"' EXIT
  curl -fsSL https://astral.sh/uv/install.sh -o "${installer_dir}/uv-install.sh"
  sh "${installer_dir}/uv-install.sh"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

mkdir -p "$(dirname "${repo_dir}")"

if [[ -e "${repo_dir}/.git" ]]; then
  if [[ -n "${repo_url}" ]] && [[ "${repo_dir}" != "${script_repo_dir}" ]]; then
    git -C "${repo_dir}" fetch --all --tags --prune
    git -C "${repo_dir}" pull --ff-only
  fi
else
  git clone "${repo_url}" "${repo_dir}"
fi

if [[ -n "${git_ref}" ]]; then
  git -C "${repo_dir}" checkout "${git_ref}"
fi

python_path="$(command -v python3)"

cd "${repo_dir}"
make_args=("PYTHON_VERSION=${python_path}")
if [[ "${install_usb_otg_tools}" -eq 0 ]]; then
  make_args+=("INSTALL_EXTRAS=")
fi
make install "${make_args[@]}"

if [[ "${install_services}" -eq 1 ]]; then
  service_args=(--user "${service_user}" --web-port "${web_port}")
  if [[ "${enable_web}" -eq 0 ]]; then
    service_args+=(--disable-web)
  fi
  if [[ "${enable_home_assistant}" -eq 0 ]]; then
    service_args+=(--disable-home-assistant)
  fi
  if [[ "${enable_glances}" -eq 1 ]]; then
    service_args+=(--enable-glances --glances-port "${glances_port}")
  fi
  if [[ "${enable_cockpit}" -eq 1 ]]; then
    service_args+=(--enable-cockpit)
  fi
  if [[ "${install_usb_otg_tools}" -eq 0 ]]; then
    service_args+=(--skip-usb-otg-tools)
  fi
  sudo bash "${repo_dir}/rpi-setup/scripts/install-service.sh" "${service_args[@]}"
fi

hostname_name="$(hostname)"
bonjour_name="${hostname_name}.local"
primary_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"

printf '\nBMGateway installed.\n'
printf 'CLI: %s/.local/bin/bm-gateway\n' "${HOME}"
printf 'Config: %s/.config/bm-gateway/config.toml\n' "${HOME}"
if [[ "${install_services}" -eq 1 ]] && [[ "${enable_web}" -eq 1 ]]; then
  printf 'Web UI: http://%s:%s/\n' "${bonjour_name}" "${web_port}"
  if [[ -n "${primary_ip}" ]]; then
    printf 'Web UI (IP): http://%s:%s/\n' "${primary_ip}" "${web_port}"
  fi
  printf 'Next step: open the Web UI and add your Bluetooth devices to start monitoring.\n'
fi
if [[ "${install_services}" -eq 1 ]] && [[ "${enable_glances}" -eq 1 ]]; then
  printf 'Glances API: http://%s:%s/api/4/status\n' "${bonjour_name}" "${glances_port}"
  if [[ -n "${primary_ip}" ]]; then
    printf 'Glances API (IP): http://%s:%s/api/4/status\n' "${primary_ip}" "${glances_port}"
  fi
  printf 'Home Assistant: add the Glances integration with host %s and port %s.\n' "${bonjour_name}" "${glances_port}"
fi
if [[ "${install_services}" -eq 1 ]] && [[ "${enable_cockpit}" -eq 1 ]]; then
  printf 'Cockpit: https://%s:9090/\n' "${bonjour_name}"
  if [[ -n "${primary_ip}" ]]; then
    printf 'Cockpit (IP): https://%s:9090/\n' "${primary_ip}"
  fi
  printf 'Cockpit login uses a system account password, not only SSH keys.\n'
fi
