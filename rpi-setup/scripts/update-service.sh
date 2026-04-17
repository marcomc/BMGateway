#!/usr/bin/env sh
set -eu

user_id=$(id -u)
if [ "${user_id}" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
UNIT_PATH=/etc/systemd/system/bm-gateway.service
WEB_UNIT_PATH=/etc/systemd/system/bm-gateway-web.service

install -m 0644 "${PROJECT_ROOT}/rpi-setup/systemd/bm-gateway.service" "${UNIT_PATH}"
install -m 0644 "${PROJECT_ROOT}/rpi-setup/systemd/bm-gateway-web.service" "${WEB_UNIT_PATH}"
systemctl daemon-reload
systemctl restart bm-gateway.service
systemctl restart bm-gateway-web.service

echo "Updated and restarted bm-gateway.service and bm-gateway-web.service"
