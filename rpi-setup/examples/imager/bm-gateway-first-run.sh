#!/bin/sh

set -eu

LOG_FILE="/var/log/bm-gateway-first-run.log"
REPO_URL="${BMGATEWAY_REPO_URL:-https://github.com/marcomc/BMGateway.git}"
REPO_DIR="${BMGATEWAY_REPO_DIR:-/opt/BMGateway}"
CONFIG_DIR="/etc/bm-gateway"
BOOT_DIR="/boot/firmware"

exec >>"${LOG_FILE}" 2>&1

printf 'Starting BMGateway first-run bootstrap\n'

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y bluetooth bluez ca-certificates curl git make

if [ ! -d "${REPO_DIR}/.git" ]; then
    git clone "${REPO_URL}" "${REPO_DIR}"
else
    git -C "${REPO_DIR}" pull --ff-only
fi

cd "${REPO_DIR}"
make install

mkdir -p "${CONFIG_DIR}"
if [ ! -f "${CONFIG_DIR}/config.toml" ]; then
    install -m 0644 python/config/config.toml.example "${CONFIG_DIR}/config.toml"
fi
if [ ! -f "${CONFIG_DIR}/devices.toml" ]; then
    install -m 0644 python/config/devices.toml.example "${CONFIG_DIR}/devices.toml"
fi

if [ -f "${BOOT_DIR}/bm-gateway-config.toml" ]; then
    install -m 0644 "${BOOT_DIR}/bm-gateway-config.toml" "${CONFIG_DIR}/config.toml"
fi
if [ -f "${BOOT_DIR}/bm-gateway-devices.toml" ]; then
    install -m 0644 "${BOOT_DIR}/bm-gateway-devices.toml" "${CONFIG_DIR}/devices.toml"
fi

install -m 0644 rpi-setup/systemd/bm-gateway.service /etc/systemd/system/bm-gateway.service
install -m 0644 rpi-setup/systemd/bm-gateway-web.service /etc/systemd/system/bm-gateway-web.service

systemctl daemon-reload
systemctl enable bm-gateway.service bm-gateway-web.service

printf 'BMGateway first-run bootstrap completed\n'
