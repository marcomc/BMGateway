#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  dev-deploy.sh --target <user@host> [--remote-dir <path>]

Options:
  --target <user@host>          Remote SSH target. Required.
  --remote-dir <path>           Remote checkout path.
                                Default: /home/<user>/BMGateway-dev
  --help                        Show this help text.
EOF
}

target=""
remote_dir=""
script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
project_root="$(CDPATH='' cd -- "${script_dir}/.." && pwd)"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --target)
      target="${2:?missing value for --target}"
      shift 2
      ;;
    --remote-dir)
      remote_dir="${2:?missing value for --remote-dir}"
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

if [[ -z "${target}" ]]; then
  printf 'Missing required --target argument\n' >&2
  usage >&2
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  printf 'ssh not found\n' >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  printf 'rsync not found\n' >&2
  exit 1
fi

remote_user="${target%@*}"
if [[ "${remote_user}" = "${target}" ]]; then
  printf 'Target must include a user, for example admin@host\n' >&2
  exit 1
fi

if [[ -z "${remote_dir}" ]]; then
  remote_dir="/home/${remote_user}/BMGateway-dev"
fi

ssh "${target}" bash -s -- "${remote_dir}" <<'EOF'
set -euo pipefail
remote_dir="$1"
mkdir -p "${remote_dir}"
EOF

rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.mypy_cache' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '__pycache__' \
  --exclude 'build' \
  --exclude 'dist' \
  --exclude 'output' \
  "${project_root}/" "${target}:${remote_dir}/"

ssh "${target}" bash -s -- "${remote_dir}" "${remote_user}" <<'EOF'
set -euo pipefail
remote_dir="$1"
remote_user="$2"

export PATH="${HOME}/.local/bin:${PATH}"
cd "${remote_dir}"
command -v uv >/dev/null 2>&1 || { echo 'uv not found on remote host' >&2; exit 1; }
python_path="$(command -v python3)"
make install "PYTHON_VERSION=${python_path}"
service_args=(--user "${remote_user}")
if sudo systemctl is-active --quiet glances-web.service \
  || sudo systemctl is-enabled glances-web.service >/dev/null 2>&1; then
  service_args+=(--enable-glances)
fi
if sudo systemctl is-active --quiet cockpit.socket \
  || sudo systemctl is-enabled cockpit.socket >/dev/null 2>&1; then
  service_args+=(--enable-cockpit)
fi
sudo bash ./rpi-setup/scripts/install-service.sh "${service_args[@]}"
EOF
