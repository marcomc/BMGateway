#!/bin/sh

set -eu

LOG_FILE="/var/log/bm-gateway-first-run.log"
REPO_URL="${BMGATEWAY_REPO_URL:-https://github.com/marcomc/BMGateway.git}"
REPO_DIR="${BMGATEWAY_REPO_DIR:-/opt/BMGateway}"
exec >>"${LOG_FILE}" 2>&1

printf 'Starting BMGateway first-run bootstrap\n'

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git

if [ ! -d "${REPO_DIR}/.git" ]; then
    git clone "${REPO_URL}" "${REPO_DIR}"
else
    git -C "${REPO_DIR}" pull --ff-only
fi

cd "${REPO_DIR}"
./scripts/bootstrap-install.sh --repo-dir "${REPO_DIR}" --skip-apt

printf 'BMGateway first-run bootstrap completed\n'
