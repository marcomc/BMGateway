from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path


def test_pyproject_declares_dedicated_web_console_script() -> None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"

    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    scripts = data["project"]["scripts"]
    assert scripts["bm-gateway"] == "bm_gateway.cli:main"
    assert scripts["bm-gateway-web"] == "bm_gateway.web_cli:main"


def test_install_link_exposes_dedicated_web_console_script() -> None:
    result = subprocess.run(
        ["make", "-n", "install-link"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "bm-gateway-web" in result.stdout


def test_web_service_template_uses_dedicated_web_executable() -> None:
    service_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "systemd" / "bm-gateway-web.service"
    )
    payload = service_path.read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/bin/bm-gateway-web --config ${BMGATEWAY_CONFIG}" in payload


def test_install_service_script_uses_dedicated_web_executable() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    assert 'web_cli_path="${service_home}/.local/bin/bm-gateway-web"' in payload
    assert 'ln -sfn "${web_cli_path}" /usr/local/bin/bm-gateway-web' in payload
    assert "ExecStart=/usr/local/bin/bm-gateway-web --config \\${BMGATEWAY_CONFIG}" in payload


def test_install_service_script_uses_current_mqtt_username_placeholder() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    assert 'mqtt.get("username", "mqtt-user")' in payload
    assert 'mqtt.get("username", "homeassistant")' not in payload


def test_install_service_script_preserves_usb_otg_fleet_trend_preferences() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    assert "def string_sequence_to_toml(values: object) -> str:" in payload
    assert 'usb_otg.get("fleet_trend_metrics", ["soc"])' in payload
    assert 'usb_otg.get("fleet_trend_range", "7")' in payload
    assert 'usb_otg.get("fleet_trend_device_ids", [])' in payload


def test_install_service_script_preserves_web_language_preference() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    assert 'web.get("language", "auto")' in payload
    assert 'f\'language = {string_to_toml(web.get("language", "auto"))}\'' in payload


def test_install_service_script_installs_scoped_web_action_sudoers_policy() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    assert 'sudoers_path="/etc/sudoers.d/bm-gateway-web"' in payload
    assert "NOPASSWD:" in payload
    assert "/usr/bin/systemctl restart bm-gateway.service" in payload
    assert "/usr/bin/systemctl restart bluetooth.service" in payload
    assert "/usr/bin/systemctl reboot" in payload
    assert "/usr/bin/systemctl poweroff" in payload
    assert 'chmod 0440 "${sudoers_path}"' in payload
    assert 'visudo -cf "${sudoers_path}"' in payload


def test_install_service_script_skips_web_action_sudoers_policy_when_web_disabled() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    assert 'if [[ "${enable_web}" -eq 1 ]]; then' in payload
    assert 'rm -f "${sudoers_path}"' in payload
    assert "Skipped web action sudoers policy because web service is disabled" in payload


def test_web_service_unit_keeps_sudo_helper_capabilities_available() -> None:
    script_path = (
        Path(__file__).resolve().parents[2] / "rpi-setup" / "scripts" / "install-service.sh"
    )
    payload = script_path.read_text(encoding="utf-8")

    web_unit_payload = payload.split('cat >"${web_unit_path}" <<EOF', maxsplit=1)[1]
    web_unit_payload = web_unit_payload.split("EOF", maxsplit=1)[0]

    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in web_unit_payload
    assert "CapabilityBoundingSet=" not in payload
    assert "${usb_otg_drive_helper_path} setup *" in payload
    assert "${usb_otg_drive_helper_path} refresh *" in payload
