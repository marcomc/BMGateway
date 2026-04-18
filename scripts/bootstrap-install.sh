#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bootstrap-install.sh --repo-url <repo-url> [options]

Options:
  --repo-dir <path>    Checkout path. Default: $HOME/BMGateway
  --ref <git-ref>      Optional branch, tag, or commit to checkout after update
  --skip-apt           Skip apt package installation
  --skip-uv            Skip uv bootstrap
  --help               Show this help text
EOF
}

repo_url=""
script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
script_repo_dir="$(CDPATH='' cd -- "${script_dir}/.." && pwd)"
repo_dir="${HOME}/BMGateway"
git_ref=""
skip_apt=0
skip_uv=0

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
    --skip-apt)
      skip_apt=1
      shift
      ;;
    --skip-uv)
      skip_uv=1
      shift
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

if [[ -d "${script_repo_dir}/.git" ]] && [[ "${repo_dir}" = "${HOME}/BMGateway" ]]; then
  repo_dir="${script_repo_dir}"
fi

if [[ -z "${repo_url}" ]] && [[ ! -d "${repo_dir}/.git" ]]; then
  printf 'Missing required --repo-url argument\n' >&2
  usage >&2
  exit 1
fi

if [[ "${skip_apt}" -eq 0 ]]; then
  sudo apt-get update
  sudo apt-get install -y bluetooth bluez curl git make python3 python3-venv
fi

if [[ "${skip_uv}" -eq 0 ]] && ! command -v uv >/dev/null 2>&1; then
  installer_dir="$(mktemp -d)"
  trap 'rm -rf "${installer_dir}"' EXIT
  curl -fsSL https://astral.sh/uv/install.sh -o "${installer_dir}/uv-install.sh"
  sh "${installer_dir}/uv-install.sh"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

mkdir -p "$(dirname "${repo_dir}")"

if [[ -d "${repo_dir}/.git" ]]; then
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
make install "PYTHON_VERSION=${python_path}"

printf '\nBMGateway installed.\n'
printf 'CLI: %s/.local/bin/bm-gateway\n' "${HOME}"
printf 'Config: %s/.config/bm-gateway/config.toml\n' "${HOME}"
