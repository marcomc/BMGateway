#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  install-service.sh [options]

Options:
  --user <name>                Service account. Default: current sudo user or current user
  --config-path <path>         Config path. Default: <home>/.config/bm-gateway/config.toml
  --state-dir <path>           State directory. Default: /var/lib/bm-gateway
  --web-host <host>            Web bind host. Default: 0.0.0.0
  --web-port <port>            Web bind port. Default: 80
  --enable-glances             Install and enable Glances in HA-compatible web mode
  --glances-bind <host>        Glances bind host. Default: 0.0.0.0
  --glances-port <port>        Glances bind port. Default: 61208
  --enable-cockpit             Install and enable Cockpit on HTTPS port 9090
  --disable-web                Do not enable/start the web service
  --disable-home-assistant     Disable MQTT and Home Assistant in the installed config
  --skip-usb-otg-tools         Do not install USB OTG helper commands or sudoers entries
  --skip-start                 Enable services but do not start or restart them
  --help                       Show this help text
EOF
}

user_id="$(id -u)"
if [[ "${user_id}" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

project_root="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
service_user="${SUDO_USER:-$(id -un)}"
state_dir="/var/lib/bm-gateway"
web_host="0.0.0.0"
web_port="80"
enable_glances=0
glances_bind="0.0.0.0"
glances_port="61208"
enable_cockpit=0
enable_web=1
enable_home_assistant=1
install_usb_otg_tools=1
start_services=1

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --user)
      service_user="${2:?missing value for --user}"
      shift 2
      ;;
    --config-path)
      config_path="${2:?missing value for --config-path}"
      shift 2
      ;;
    --state-dir)
      state_dir="${2:?missing value for --state-dir}"
      shift 2
      ;;
    --web-host)
      web_host="${2:?missing value for --web-host}"
      shift 2
      ;;
    --web-port)
      web_port="${2:?missing value for --web-port}"
      shift 2
      ;;
    --enable-glances)
      enable_glances=1
      shift
      ;;
    --glances-bind)
      glances_bind="${2:?missing value for --glances-bind}"
      shift 2
      ;;
    --glances-port)
      glances_port="${2:?missing value for --glances-port}"
      shift 2
      ;;
    --enable-cockpit)
      enable_cockpit=1
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
    --skip-usb-otg-tools)
      install_usb_otg_tools=0
      shift
      ;;
    --skip-start)
      start_services=0
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

service_home="$(getent passwd "${service_user}" | cut -d: -f6)"
if [[ -z "${service_home}" ]]; then
  printf 'Unable to resolve home directory for user %s\n' "${service_user}" >&2
  exit 1
fi

config_path="${config_path:-${service_home}/.config/bm-gateway/config.toml}"
config_dir="$(dirname "${config_path}")"
devices_path="${config_dir}/devices.toml"
cli_path="${service_home}/.local/bin/bm-gateway"
web_cli_path="${service_home}/.local/bin/bm-gateway-web"
usb_otg_boot_mode_path="/usr/local/bin/bm-gateway-usb-otg-boot-mode"
usb_otg_drive_helper_path="/usr/local/bin/bm-gateway-usb-otg-frame-test"
unit_path="/etc/systemd/system/bm-gateway.service"
web_unit_path="/etc/systemd/system/bm-gateway-web.service"
glances_unit_path="/etc/systemd/system/glances-web.service"
sudoers_path="/etc/sudoers.d/bm-gateway-web"

install -d -m 0755 "${config_dir}" "${state_dir}" /usr/local/bin
chown -R "${service_user}:${service_user}" "${config_dir}" "${state_dir}"

ln -sfn "${cli_path}" /usr/local/bin/bm-gateway
ln -sfn "${web_cli_path}" /usr/local/bin/bm-gateway-web
if [[ "${install_usb_otg_tools}" -eq 1 ]]; then
  usb_otg_packages=(chromium dosfstools kmod libjpeg-dev python3-dev util-linux zlib1g-dev)
  missing_usb_otg_packages=()
  for package in "${usb_otg_packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -Fxq 'install ok installed'; then
      missing_usb_otg_packages+=("${package}")
    fi
  done
  if [[ "${#missing_usb_otg_packages[@]}" -gt 0 ]]; then
    apt-get update
    apt-get install -y "${missing_usb_otg_packages[@]}"
  fi
  install -m 0755 "${project_root}/rpi-setup/scripts/usb-otg-boot-mode.sh" \
    "${usb_otg_boot_mode_path}"
  install -m 0755 "${project_root}/rpi-setup/scripts/usb-otg-frame-test.sh" \
    "${usb_otg_drive_helper_path}"
else
  rm -f "${usb_otg_boot_mode_path}" "${usb_otg_drive_helper_path}"
fi

if [[ ! -f "${config_path}" ]]; then
  install -m 0644 "${project_root}/python/config/config.toml.example" "${config_path}"
fi
if [[ ! -f "${devices_path}" ]]; then
  : > "${devices_path}"
fi
chown "${service_user}:${service_user}" "${config_path}" "${devices_path}"

python3 - <<'PY' "${config_path}" "${state_dir}" "${web_host}" "${web_port}" "${enable_home_assistant}" "${enable_web}"
from pathlib import Path
import sys
import tomllib


def bool_to_toml(value: bool) -> str:
    return "true" if value else "false"


def string_to_toml(value: str) -> str:
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def string_sequence_to_toml(values: object) -> str:
    if not isinstance(values, list | tuple):
        return "[]"
    return "[" + ", ".join(string_to_toml(str(value)) for value in values) + "]"


config_path = Path(sys.argv[1])
state_dir = sys.argv[2]
web_host = sys.argv[3]
web_port = int(sys.argv[4])
enable_home_assistant = bool(int(sys.argv[5]))
enable_web = bool(int(sys.argv[6]))

with config_path.open("rb") as handle:
    data = tomllib.load(handle)

gateway = dict(data.get("gateway", {}))
bluetooth = dict(data.get("bluetooth", {}))
mqtt = dict(data.get("mqtt", {}))
home_assistant = dict(data.get("home_assistant", {}))
web = dict(data.get("web", {}))
usb_otg = dict(data.get("usb_otg", {}))
archive_sync = dict(data.get("archive_sync", {}))
retention = dict(data.get("retention", {}))

if str(gateway.get("name", "")).startswith("__"):
    gateway["name"] = "BMGateway"
gateway["device_registry"] = "devices.toml"
gateway["data_dir"] = state_dir
gateway["reader_mode"] = "live"
mqtt["enabled"] = enable_home_assistant
home_assistant["enabled"] = enable_home_assistant
web["enabled"] = True
web["enabled"] = enable_web
web["host"] = web_host
web["port"] = web_port

payload = "\n".join(
    [
        "[gateway]",
        f'name = {string_to_toml(gateway.get("name", "BMGateway"))}',
        f'timezone = {string_to_toml(gateway.get("timezone", "Europe/Rome"))}',
        f'poll_interval_seconds = {int(gateway.get("poll_interval_seconds", 300))}',
        f'device_registry = {string_to_toml(gateway["device_registry"])}',
        f'data_dir = {string_to_toml(gateway["data_dir"])}',
        f'reader_mode = {string_to_toml(gateway["reader_mode"])}',
        "",
        "[bluetooth]",
        f'adapter = {string_to_toml(bluetooth.get("adapter", "auto"))}',
        f'scan_timeout_seconds = {int(bluetooth.get("scan_timeout_seconds", 15))}',
        f'connect_timeout_seconds = {int(bluetooth.get("connect_timeout_seconds", 45))}',
        "",
        "[mqtt]",
        f'enabled = {bool_to_toml(bool(mqtt.get("enabled", enable_home_assistant)))}',
        f'host = {string_to_toml(mqtt.get("host", "mqtt.local"))}',
        f'port = {int(mqtt.get("port", 1883))}',
        f'username = {string_to_toml(mqtt.get("username", "mqtt-user"))}',
        f'password = {string_to_toml(mqtt.get("password", "CHANGE_ME"))}',
        f'base_topic = {string_to_toml(mqtt.get("base_topic", "bm_gateway"))}',
        f'discovery_prefix = {string_to_toml(mqtt.get("discovery_prefix", "homeassistant"))}',
        f'retain_discovery = {bool_to_toml(bool(mqtt.get("retain_discovery", True)))}',
        f'retain_state = {bool_to_toml(bool(mqtt.get("retain_state", False)))}',
        "",
        "[home_assistant]",
        f'enabled = {bool_to_toml(bool(home_assistant.get("enabled", enable_home_assistant)))}',
        f'status_topic = {string_to_toml(home_assistant.get("status_topic", "homeassistant/status"))}',
        f'gateway_device_id = {string_to_toml(home_assistant.get("gateway_device_id", "bm_gateway"))}',
        "",
        "[web]",
        f'enabled = {bool_to_toml(bool(web.get("enabled", True)))}',
        f'host = {string_to_toml(web.get("host", web_host))}',
        f'port = {int(web.get("port", web_port))}',
        f'show_chart_markers = {bool_to_toml(bool(web.get("show_chart_markers", False)))}',
        f'appearance = {string_to_toml(web.get("appearance", "system"))}',
        f'default_chart_range = {string_to_toml(web.get("default_chart_range", "7"))}',
        f'default_chart_metric = {string_to_toml(web.get("default_chart_metric", "soc"))}',
        f'language = {string_to_toml(web.get("language", "auto"))}',
        "",
        "[usb_otg]",
        f'enabled = {bool_to_toml(bool(usb_otg.get("enabled", False)))}',
        f'image_path = {string_to_toml(usb_otg.get("image_path", "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img"))}',
        f'size_mb = {int(usb_otg.get("size_mb", 64))}',
        f'gadget_name = {string_to_toml(usb_otg.get("gadget_name", "bmgw_frame"))}',
        f'image_width_px = {int(usb_otg.get("image_width_px", 480))}',
        f'image_height_px = {int(usb_otg.get("image_height_px", 234))}',
        f'image_format = {string_to_toml(usb_otg.get("image_format", "jpeg"))}',
        f'appearance = {string_to_toml(usb_otg.get("appearance", "light"))}',
        f'refresh_interval_seconds = {int(usb_otg.get("refresh_interval_seconds", 0))}',
        f'overview_devices_per_image = {int(usb_otg.get("overview_devices_per_image", 3))}',
        f'export_battery_overview = {bool_to_toml(bool(usb_otg.get("export_battery_overview", True)))}',
        f'export_fleet_trend = {bool_to_toml(bool(usb_otg.get("export_fleet_trend", True)))}',
        f'fleet_trend_metrics = {string_sequence_to_toml(usb_otg.get("fleet_trend_metrics", ["soc"]))}',
        f'fleet_trend_range = {string_to_toml(usb_otg.get("fleet_trend_range", "7"))}',
        f'fleet_trend_device_ids = {string_sequence_to_toml(usb_otg.get("fleet_trend_device_ids", []))}',
        "",
        "[archive_sync]",
        f'enabled = {bool_to_toml(bool(archive_sync.get("enabled", True)))}',
        f'periodic_interval_seconds = {int(archive_sync.get("periodic_interval_seconds", 64800))}',
        f'reconnect_min_gap_seconds = {int(archive_sync.get("reconnect_min_gap_seconds", 28800))}',
        f'safety_margin_seconds = {int(archive_sync.get("safety_margin_seconds", 7200))}',
        f'bm200_max_pages_per_sync = {int(archive_sync.get("bm200_max_pages_per_sync", 3))}',
        f'bm300_enabled = {bool_to_toml(bool(archive_sync.get("bm300_enabled", True)))}',
        f'bm300_max_pages_per_sync = {int(archive_sync.get("bm300_max_pages_per_sync", 3))}',
        "",
        "[retention]",
        f'raw_retention_days = {int(retention.get("raw_retention_days", 180))}',
        f'daily_retention_days = {int(retention.get("daily_retention_days", 0))}',
        "",
    ]
)
config_path.write_text(payload, encoding="utf-8")
PY

python3 - <<'PY' "${devices_path}"
from pathlib import Path
import sys
import tomllib

devices_path = Path(sys.argv[1])
try:
    with devices_path.open("rb") as handle:
        data = tomllib.load(handle)
except Exception:
    devices_path.write_text("", encoding="utf-8")
    raise SystemExit(0)

raw_devices = data.get("devices", [])
device_ids = {
    str(item.get("id", ""))
    for item in raw_devices
    if isinstance(item, dict)
}
if device_ids == {"bm200_house", "bm300_van"}:
    devices_path.write_text("", encoding="utf-8")
PY

cat >"${unit_path}" <<EOF
[Unit]
Description=BMGateway Runtime
After=network-online.target bluetooth.service
Wants=network-online.target

[Service]
Type=simple
Environment=BMGATEWAY_CONFIG=${config_path}
ExecStart=/usr/local/bin/bm-gateway --config \${BMGATEWAY_CONFIG} run --publish-discovery --state-dir ${state_dir}
Restart=always
RestartSec=10
User=${service_user}
Group=${service_user}
WorkingDirectory=${state_dir}

[Install]
WantedBy=multi-user.target
EOF

cat >"${web_unit_path}" <<EOF
[Unit]
Description=BMGateway Web Management
After=network-online.target bm-gateway.service
Wants=network-online.target

[Service]
Type=simple
Environment=BMGATEWAY_CONFIG=${config_path}
ExecStart=/usr/local/bin/bm-gateway-web --config \${BMGATEWAY_CONFIG} --state-dir ${state_dir}
Restart=always
RestartSec=10
AmbientCapabilities=CAP_NET_BIND_SERVICE
User=${service_user}
Group=${service_user}
WorkingDirectory=${state_dir}

[Install]
WantedBy=multi-user.target
EOF

if [[ "${enable_web}" -eq 1 ]]; then
  sudoers_commands="/usr/bin/systemctl restart bm-gateway.service, /usr/bin/systemctl restart bluetooth.service, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff"
  if [[ "${install_usb_otg_tools}" -eq 1 ]]; then
    sudoers_commands="${sudoers_commands}, ${usb_otg_boot_mode_path} prepare, ${usb_otg_boot_mode_path} restore, ${usb_otg_drive_helper_path} setup *, ${usb_otg_drive_helper_path} refresh *"
  fi
  cat >"${sudoers_path}" <<EOF
${service_user} ALL=(root) NOPASSWD: ${sudoers_commands}
EOF
  chmod 0440 "${sudoers_path}"
  if command -v visudo >/dev/null 2>&1; then
    visudo -cf "${sudoers_path}"
  fi
else
  rm -f "${sudoers_path}"
fi

if [[ "${enable_glances}" -eq 1 ]]; then
  if ! command -v glances >/dev/null 2>&1; then
    apt-get update
    apt-get install -y glances
  fi

  cat >"${glances_unit_path}" <<EOF
[Unit]
Description=Glances Web API for Home Assistant
Documentation=https://glances.readthedocs.io/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/glances -w --disable-webui -B ${glances_bind} -p ${glances_port}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
else
  rm -f "${glances_unit_path}"
fi

if [[ "${enable_cockpit}" -eq 1 ]] && ! dpkg -s cockpit >/dev/null 2>&1; then
  apt-get update
  apt-get install -y cockpit
fi

systemctl daemon-reload
systemctl enable bm-gateway.service
if [[ "${enable_web}" -eq 1 ]]; then
  systemctl enable bm-gateway-web.service
else
  systemctl disable --now bm-gateway-web.service || true
fi
if [[ "${enable_glances}" -eq 1 ]]; then
  systemctl enable glances-web.service
fi
if [[ "${enable_cockpit}" -eq 1 ]]; then
  systemctl enable cockpit.socket
fi

if [[ "${start_services}" -eq 1 ]]; then
  systemctl restart bm-gateway.service
  if [[ "${enable_web}" -eq 1 ]]; then
    systemctl restart bm-gateway-web.service
  fi
  if [[ "${enable_glances}" -eq 1 ]]; then
    systemctl restart glances-web.service
  fi
  if [[ "${enable_cockpit}" -eq 1 ]]; then
    systemctl restart cockpit.socket
  fi
fi

printf 'Installed runtime service to %s\n' "${unit_path}"
printf 'Installed web service to %s\n' "${web_unit_path}"
if [[ "${enable_web}" -eq 1 ]]; then
  printf 'Installed web action sudoers policy to %s\n' "${sudoers_path}"
else
  printf 'Skipped web action sudoers policy because web service is disabled\n'
fi
if [[ "${install_usb_otg_tools}" -eq 1 ]]; then
  printf 'Installed USB OTG helpers to %s and %s\n' \
    "${usb_otg_boot_mode_path}" "${usb_otg_drive_helper_path}"
else
  printf 'Skipped USB OTG helper installation\n'
fi
if [[ "${enable_glances}" -eq 1 ]]; then
  printf 'Installed Glances service to %s\n' "${glances_unit_path}"
  printf 'Glances API: http://%s:%s/api/4/status\n' "${glances_bind}" "${glances_port}"
fi
if [[ "${enable_cockpit}" -eq 1 ]]; then
  printf 'Enabled Cockpit socket: https://0.0.0.0:9090/\n'
fi
printf 'Config path: %s\n' "${config_path}"
printf 'Devices path: %s\n' "${devices_path}"
printf 'State directory: %s\n' "${state_dir}"
