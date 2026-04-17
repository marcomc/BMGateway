#!/usr/bin/env sh
set -eu

user_id=$(id -u)
if [ "${user_id}" -ne 0 ]; then
  echo "run as root" >&2
  exit 1
fi

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
UNIT_PATH=/etc/systemd/system/bm-gateway.service

install -m 0644 "${PROJECT_ROOT}/rpi-setup/systemd/bm-gateway.service" "${UNIT_PATH}"
systemctl daemon-reload
systemctl restart bm-gateway.service

echo "Updated and restarted bm-gateway.service"
