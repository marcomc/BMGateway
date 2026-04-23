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
unit_path="/etc/systemd/system/bm-gateway.service"
web_unit_path="/etc/systemd/system/bm-gateway-web.service"
glances_unit_path="/etc/systemd/system/glances-web.service"
sudoers_path="/etc/sudoers.d/bm-gateway-web"

install -d -m 0755 "${config_dir}" "${state_dir}" /usr/local/bin
chown -R "${service_user}:${service_user}" "${config_dir}" "${state_dir}"

ln -sfn "${cli_path}" /usr/local/bin/bm-gateway
ln -sfn "${web_cli_path}" /usr/local/bin/bm-gateway-web

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
AmbientCapabilities=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE
User=${service_user}
Group=${service_user}
WorkingDirectory=${state_dir}

[Install]
WantedBy=multi-user.target
EOF

cat >"${sudoers_path}" <<EOF
${service_user} ALL=(root) NOPASSWD: /usr/bin/systemctl restart bm-gateway.service, /usr/bin/systemctl restart bluetooth.service, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff
EOF
chmod 0440 "${sudoers_path}"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "${sudoers_path}"
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
printf 'Installed web action sudoers policy to %s\n' "${sudoers_path}"
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
