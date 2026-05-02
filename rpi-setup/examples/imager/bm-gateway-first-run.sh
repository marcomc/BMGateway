#!/bin/sh

set -eu

LOG_FILE="/var/log/bm-gateway-first-run.log"
REPO_URL="${BMGATEWAY_REPO_URL:-https://github.com/marcomc/BMGateway.git}"
REPO_DIR="${BMGATEWAY_REPO_DIR:-/opt/BMGateway}"
SERVICE_USER="${BMGATEWAY_SERVICE_USER:-admin}"
BMGATEWAY_HOSTNAME="${BMGATEWAY_HOSTNAME:-}"
BOOT_DIR="/boot/firmware"
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
if [ -n "${BMGATEWAY_HOSTNAME}" ]; then
    ./scripts/bootstrap-install.sh \
        --repo-dir "${REPO_DIR}" \
        --service-user "${SERVICE_USER}" \
        --hostname "${BMGATEWAY_HOSTNAME}"
else
    ./scripts/bootstrap-install.sh \
        --repo-dir "${REPO_DIR}" \
        --service-user "${SERVICE_USER}"
fi

CONFIG_DIR="/home/${SERVICE_USER}/.config/bm-gateway"
if [ -f "${BOOT_DIR}/bm-gateway-config.toml" ]; then
    install -m 0644 "${BOOT_DIR}/bm-gateway-config.toml" "${CONFIG_DIR}/config.toml"
fi
if [ -f "${BOOT_DIR}/bm-gateway-devices.toml" ]; then
    install -m 0644 "${BOOT_DIR}/bm-gateway-devices.toml" "${CONFIG_DIR}/devices.toml"
fi
chown "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}/config.toml" "${CONFIG_DIR}/devices.toml" 2>/dev/null || true
systemctl restart bm-gateway.service bm-gateway-web.service

printf 'BMGateway first-run bootstrap completed\n'
