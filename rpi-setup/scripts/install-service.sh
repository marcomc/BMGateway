#!/usr/bin/env sh
set -eu

user_id=$(id -u)
if [ "${user_id}" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
CONFIG_DIR=/etc/bm-gateway
STATE_DIR=/var/lib/bm-gateway
UNIT_PATH=/etc/systemd/system/bm-gateway.service
WEB_UNIT_PATH=/etc/systemd/system/bm-gateway-web.service

install -d -m 0755 "${CONFIG_DIR}" "${STATE_DIR}"
install -m 0644 "${PROJECT_ROOT}/python/config/config.toml.example" "${CONFIG_DIR}/config.toml"
install -m 0644 "${PROJECT_ROOT}/python/config/devices.toml.example" "${CONFIG_DIR}/devices.toml"
install -m 0644 "${PROJECT_ROOT}/rpi-setup/systemd/bm-gateway.service" "${UNIT_PATH}"
install -m 0644 "${PROJECT_ROOT}/rpi-setup/systemd/bm-gateway-web.service" "${WEB_UNIT_PATH}"

systemctl daemon-reload
systemctl enable bm-gateway.service
systemctl enable bm-gateway-web.service

echo "Installed service unit to ${UNIT_PATH}"
echo "Installed web service unit to ${WEB_UNIT_PATH}"
echo "Review ${CONFIG_DIR}/config.toml before starting the service."
