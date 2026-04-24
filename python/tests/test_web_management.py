from __future__ import annotations

import json
import socket
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from _pytest.monkeypatch import MonkeyPatch
from bm_gateway import __version__
from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry, normalize_mac_address, validate_devices
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.state_store import fetch_recent_history, persist_snapshot
from bm_gateway.usb_otg_export import USBOTGExportResult
from bm_gateway.web import (
    _add_device_form_html,
    _chart_points,
    _discover_bluetooth_adapters,
    add_device_from_form,
    build_run_once_command,
    render_add_device_html,
    render_device_html,
    render_devices_html,
    render_diagnostics_html,
    render_edit_device_html,
    render_frame_battery_overview_html,
    render_frame_fleet_trend_html,
    render_history_html,
    render_home_html,
    render_management_html,
    render_settings_html,
    render_usb_otg_export_pending_html,
    update_bluetooth_preferences,
    update_config_from_text,
    update_device_from_form,
    update_device_icon,
    update_gateway_preferences,
    update_home_assistant_preferences,
    update_mqtt_preferences,
    update_usb_otg_preferences,
    update_web_preferences,
)
from bm_gateway.web import (
    render_reboot_pending_html as render_reboot_pending_html_wrapper,
)
from bm_gateway.web_actions import (
    prepare_usb_otg_boot_mode,
    refresh_usb_otg_drive,
    restart_system_service,
    restore_usb_otg_boot_mode,
    schedule_host_shutdown,
)
from bm_gateway.web_pages_settings import render_reboot_pending_html, render_shutdown_pending_html
from bm_gateway.web_ui import base_css, chart_script


def test_update_config_from_text_writes_validated_config_and_registry(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_toml = "\n".join(
        [
            "[gateway]",
            'name = "BMGateway"',
            'timezone = "Europe/Rome"',
            "poll_interval_seconds = 15",
            'device_registry = "devices.toml"',
            'data_dir = "data"',
            'reader_mode = "fake"',
            "",
            "[bluetooth]",
            'adapter = "auto"',
            "scan_timeout_seconds = 8",
            "connect_timeout_seconds = 10",
            "",
            "[mqtt]",
            "enabled = true",
            'host = "mqtt.local"',
            "port = 1883",
            'username = "homeassistant"',
            'password = "secret"',
            'base_topic = "bm_gateway"',
            'discovery_prefix = "homeassistant"',
            "retain_discovery = true",
            "retain_state = false",
            "",
            "[home_assistant]",
            "enabled = true",
            'status_topic = "homeassistant/status"',
            'gateway_device_id = "bm_gateway"',
            "",
            "[web]",
            "enabled = true",
            'host = "127.0.0.1"',
            "port = 8090",
            "",
            "[retention]",
            "raw_retention_days = 120",
            "daily_retention_days = 0",
            "",
        ]
    )
    devices_toml = "\n".join(
        [
            "[[devices]]",
            'id = "bm200_house"',
            'type = "bm200"',
            'name = "BM200 House"',
            'mac = "AA:BB:CC:DD:EE:01"',
            "enabled = true",
            "",
        ]
    )

    errors = update_config_from_text(
        config_path=config_path,
        config_toml=config_toml,
        devices_toml=devices_toml,
    )

    assert errors == []
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert config.web.port == 8090
    assert config.retention.raw_retention_days == 120
    assert devices[0].id == "bm200_house"


def test_chart_script_centers_active_controls_in_scroll_rail() -> None:
    script = chart_script("history-chart")

    assert 'function centerButtonInRail(button, behavior = "auto")' in script
    assert 'const rail = button.closest(".control-rail");' in script
    assert "const railRect = rail.getBoundingClientRect();" in script
    assert "const buttonRect = button.getBoundingClientRect();" in script
    assert "const maxScrollLeft = Math.max(0, rail.scrollWidth - rail.clientWidth);" in script
    assert "rail.scrollTo({" in script
    assert 'centerButtonInRail(button, "smooth");' in script
    assert "requestAnimationFrame(() => {" in script
    assert "setTimeout(() => centerActiveControls(), 80);" in script
    assert 'window.addEventListener("load", () => {' in script


def test_chart_points_prefer_daily_last_seen_timestamp_for_right_edge_alignment() -> None:
    points = _chart_points(
        [
            {
                "ts": "2026-04-22T01:33:56+02:00",
                "voltage": 13.39,
                "soc": 99,
                "temperature": 26.0,
                "error_code": None,
            }
        ],
        [
            {
                "day": "2026-04-22",
                "samples": 13,
                "avg_voltage": 13.395,
                "avg_soc": 99.7,
                "avg_temperature": 25.1,
                "last_seen": "2026-04-22T01:33:56+02:00",
            }
        ],
        series="Spare NLP20",
    )

    daily_points = [point for point in points if point["kind"] == "daily"]

    assert len(daily_points) == 1
    assert daily_points[0]["ts"] == "2026-04-22T01:33:56+02:00"


def test_chart_script_supports_range_paging_and_drag_panning() -> None:
    script = chart_script("history-chart")

    assert "function rangeDurationMs(rangeValue)" in script
    assert "function clampWindowEnd(requestedEnd, { earliest, latest, duration })" in script
    assert 'data-chart-nav="previous"' in script
    assert "function pageRange(direction)" in script
    assert "let visibleSeries = new Set(" in script
    assert "function updateLegendState()" in script
    assert 'button.dataset.seriesLabel || ""' in script
    assert "visibleSeries.delete(label);" in script
    assert "visibleSeries.add(label);" in script
    assert 'previousButton.addEventListener("click", () => pageRange(-1));' in script
    assert 'nextButton.addEventListener("click", () => pageRange(1));' in script
    assert 'frame.addEventListener("pointerdown", (event) => {' in script
    assert 'frame.addEventListener("pointermove", (event) => {' in script
    assert "currentWindowEnd = dragStartEnd - deltaMs;" in script
    assert 'frame.classList.add("is-panning");' in script


def test_chart_script_renders_multi_series_tooltip_rows() -> None:
    script = chart_script("history-chart")

    assert "function tooltipEntriesForX(chart, targetX)" in script
    assert "chart.seriesBuckets.map((series) => {" in script
    assert 'class="tooltip-series-row"' in script
    assert 'class="tooltip-series-swatch"' in script
    assert 'class="tooltip-series-value"' in script
    assert "const rows = entries.map((entry) => (" in script


def test_chart_script_keeps_compact_frame_chart_inside_edges() -> None:
    script = chart_script("frame-fleet-trend-chart")

    assert 'dataset.chartCompact === "true"' in script
    assert "const padRight = isCompact ? 14 : 18;" in script
    assert "const padBottom = isCompact ? 20 : 44;" in script
    assert 'rx="${isCompact ? 12 : 22}"' in script


def test_chart_card_markup_includes_side_navigation_buttons() -> None:
    html = render_home_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
    )

    assert 'class="chart-nav-arrow previous"' in html
    assert 'class="chart-nav-arrow next"' in html
    assert 'class="chart-canvas"' in html
    assert 'class="legend-item active"' in html
    assert 'data-series-label="No devices"' in html
    assert 'aria-pressed="true"' in html


def test_restart_system_service_uses_non_interactive_sudo(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs: object) -> Any:
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Completed:
            returncode = 0
            stderr = ""

        return _Completed()

    monkeypatch.setattr("bm_gateway.web_actions.subprocess.run", _fake_run)

    restart_system_service("bm-gateway.service")

    assert captured["command"] == ["sudo", "-n", "systemctl", "restart", "bm-gateway.service"]


def test_prepare_usb_otg_boot_mode_uses_non_interactive_sudo(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs: object) -> Any:
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Completed:
            returncode = 0
            stderr = ""

        return _Completed()

    monkeypatch.setattr("bm_gateway.web_actions.subprocess.run", _fake_run)

    prepare_usb_otg_boot_mode()

    assert captured["command"] == [
        "sudo",
        "-n",
        "/usr/local/bin/bm-gateway-usb-otg-boot-mode",
        "prepare",
    ]


def test_restore_usb_otg_boot_mode_uses_non_interactive_sudo(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs: object) -> Any:
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Completed:
            returncode = 0
            stderr = ""

        return _Completed()

    monkeypatch.setattr("bm_gateway.web_actions.subprocess.run", _fake_run)

    restore_usb_otg_boot_mode()

    assert captured["command"] == [
        "sudo",
        "-n",
        "/usr/local/bin/bm-gateway-usb-otg-boot-mode",
        "restore",
    ]


def test_refresh_usb_otg_drive_uses_configured_drive_helper(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs: object) -> Any:
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Completed:
            returncode = 0
            stderr = ""

        return _Completed()

    monkeypatch.setattr("bm_gateway.web_actions.subprocess.run", _fake_run)

    refresh_usb_otg_drive(config_path)

    assert captured["command"] == [
        "sudo",
        "-n",
        "/usr/local/bin/bm-gateway-usb-otg-frame-test",
        "refresh",
        "--image-path",
        "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img",
        "--gadget-name",
        "bmgw_frame",
    ]


def test_schedule_host_shutdown_uses_non_interactive_systemctl_poweroff(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_popen(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("bm_gateway.web_actions.subprocess.Popen", _fake_popen)

    schedule_host_shutdown()

    assert captured["command"] == ["/bin/sh", "-lc", "sleep 1 && sudo -n systemctl poweroff"]
    assert captured["kwargs"] == {
        "stdout": -3,
        "stderr": -3,
        "start_new_session": True,
    }


def test_render_reboot_pending_html_contains_polling_status_page() -> None:
    html = render_reboot_pending_html(theme_preference="dark")

    assert "Reboot In Progress" in html
    assert 'id="reboot-elapsed-seconds"' in html
    assert 'id="reboot-status-text"' in html
    assert 'fetch("/api/status", { cache: "no-store" })' in html
    assert "Raspberry Pi is back online" in html


def test_render_reboot_pending_html_wrapper_delegates() -> None:
    html = render_reboot_pending_html_wrapper(theme_preference="light")

    assert "BMGateway Reboot" in html


def test_render_shutdown_pending_html_contains_safe_poweroff_guidance() -> None:
    html = render_shutdown_pending_html(theme_preference="dark")

    assert "Shutdown In Progress" in html
    assert "Shutdown scheduled" in html
    assert "Wait for the Raspberry Pi activity LED to stop blinking" in html
    assert "BMGateway Shutdown" in html


def test_render_usb_otg_export_pending_html_contains_progress_status_page() -> None:
    html = render_usb_otg_export_pending_html(theme_preference="dark")

    assert "Frame Image Export" in html
    assert 'id="usb-otg-export-progress-bar"' in html
    assert 'id="usb-otg-export-percent"' in html
    assert 'id="usb-otg-export-status-text"' in html
    assert 'fetch("/api/usb-otg-export/status", { cache: "no-store" })' in html
    assert 'window.location.replace("/settings?message=" + message)' in html
    assert 'window.location.replace("/settings?edit=1&message=" + message)' not in html


def test_update_gateway_preferences_persists_runtime_and_integration_settings(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "fake"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = true",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "mqtt-user"',
                'password = "secret"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = true",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 8080",
                "show_chart_markers = false",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = update_gateway_preferences(
        config_path=config_path,
        gateway_name="BMGateway",
        timezone="Europe/Rome",
        reader_mode="live",
        poll_interval_seconds=600,
        raw_retention_days=90,
        daily_retention_days=30,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.gateway.reader_mode == "live"
    assert config.gateway.poll_interval_seconds == 600
    assert config.retention.raw_retention_days == 90
    assert config.retention.daily_retention_days == 30


def test_update_bluetooth_preferences_persists_adapter_and_timeouts(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(Path("python/config/config.toml.example").read_text(encoding="utf-8"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = update_bluetooth_preferences(
        config_path=config_path,
        adapter="hci1",
        scan_timeout_seconds=20,
        connect_timeout_seconds=60,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.bluetooth.adapter == "hci1"
    assert config.bluetooth.scan_timeout_seconds == 20
    assert config.bluetooth.connect_timeout_seconds == 60


def test_update_gateway_preferences_rejects_invalid_numeric_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(Path("python/config/config.toml.example").read_text(encoding="utf-8"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = update_gateway_preferences(
        config_path=config_path,
        gateway_name="BMGateway",
        timezone="Europe/Rome",
        reader_mode="fake",
        poll_interval_seconds=0,
        raw_retention_days=0,
        daily_retention_days=-1,
    )

    assert "gateway.poll_interval_seconds must be greater than zero" in errors
    assert "retention.raw_retention_days must be greater than zero" in errors
    assert "retention.daily_retention_days must be zero or greater" in errors


def test_render_settings_html_warns_when_poll_interval_is_aggressive() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, gateway=replace(config.gateway, poll_interval_seconds=120))
    html = render_settings_html(config=config, snapshot={}, devices=[], edit_mode=False)

    assert "Poll interval warning" in html
    assert "Polling faster than 300 seconds can increase Bluetooth discovery failures" in html


def test_render_settings_html_edit_mode_warns_when_poll_interval_is_aggressive() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, gateway=replace(config.gateway, poll_interval_seconds=120))
    html = render_settings_html(config=config, snapshot={}, devices=[], edit_mode=True)

    assert "Poll interval warning" in html
    assert "Polling faster than 300 seconds can increase Bluetooth discovery failures" in html


def test_update_mqtt_preferences_persists_transport_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(Path("python/config/config.toml.example").read_text(encoding="utf-8"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = update_mqtt_preferences(
        config_path=config_path,
        mqtt_enabled=False,
        mqtt_host="broker.local",
        mqtt_port=2883,
        mqtt_username="gateway-user",
        mqtt_password="broker-secret",
        mqtt_base_topic="garage_gateway",
        mqtt_discovery_prefix="ha",
        mqtt_retain_discovery=False,
        mqtt_retain_state=True,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.mqtt.enabled is False
    assert config.mqtt.host == "broker.local"
    assert config.mqtt.port == 2883
    assert config.mqtt.username == "gateway-user"
    assert config.mqtt.password == "broker-secret"
    assert config.mqtt.base_topic == "garage_gateway"
    assert config.mqtt.discovery_prefix == "ha"
    assert config.mqtt.retain_discovery is False
    assert config.mqtt.retain_state is True


def test_update_mqtt_preferences_rejects_invalid_transport_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(Path("python/config/config.toml.example").read_text(encoding="utf-8"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = update_mqtt_preferences(
        config_path=config_path,
        mqtt_enabled=True,
        mqtt_host="",
        mqtt_port=0,
        mqtt_username="",
        mqtt_password="",
        mqtt_base_topic="",
        mqtt_discovery_prefix="",
        mqtt_retain_discovery=True,
        mqtt_retain_state=False,
    )

    assert "mqtt.host must not be empty" in errors
    assert "mqtt.port must be greater than zero" in errors
    assert "mqtt.base_topic must not be empty" in errors
    assert "mqtt.discovery_prefix must not be empty" in errors


def test_update_home_assistant_preferences_persists_discovery_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(Path("python/config/config.toml.example").read_text(encoding="utf-8"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = update_home_assistant_preferences(
        config_path=config_path,
        home_assistant_enabled=False,
        home_assistant_status_topic="hass/status",
        home_assistant_gateway_device_id="garage_gateway",
    )

    assert errors == []
    config = load_config(config_path)
    assert config.home_assistant.enabled is False
    assert config.home_assistant.status_topic == "hass/status"
    assert config.home_assistant.gateway_device_id == "garage_gateway"


def test_add_device_from_form_normalizes_compact_mac_and_enables_live_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "fake"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = add_device_from_form(
        config_path=config_path,
        device_type="bm200",
        device_name="Ancell BM200",
        device_mac="A1B2C3D4E5F6",
        installed_in_vehicle=True,
        vehicle_type="motorcycle",
        battery_brand="Yuasa",
        battery_model="YTX20L-BS",
        battery_nominal_voltage=12,
        battery_capacity_ah=18.0,
        battery_production_year=2025,
    )

    assert errors == []
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert config.gateway.reader_mode == "live"
    assert devices[0].id == "ancell_bm200"
    assert devices[0].mac == "A1:B2:C3:D4:E5:F6"
    assert devices[0].icon_key == "lead_acid_battery"
    assert devices[0].vehicle_type == "motorcycle"
    assert devices[0].battery_brand == "Yuasa"
    assert devices[0].battery_model == "YTX20L-BS"
    assert devices[0].battery_nominal_voltage == 12
    assert devices[0].battery_capacity_ah == 18.0
    assert devices[0].battery_production_year == 2025


def test_add_device_from_form_writes_toml_safe_strings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "fake"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = add_device_from_form(
        config_path=config_path,
        device_type="bm200",
        device_name='Ancell "Quoted" \\ Unit',
        device_mac="A1B2C3D4E5F6",
    )

    assert errors == []
    devices = load_device_registry(tmp_path / "devices.toml")
    assert devices[0].id == "ancell_quoted_unit"
    assert devices[0].name == 'Ancell "Quoted" \\ Unit'
    assert devices[0].icon_key == "lead_acid_battery"


def test_add_device_from_form_accepts_serial_style_identifier(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(Path("python/config/config.toml.example").read_text(encoding="utf-8"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")

    errors = add_device_from_form(
        config_path=config_path,
        device_type="bm200",
        device_name="Bench Test",
        device_mac="fake serial 123",
    )

    assert errors == []
    devices = load_device_registry(tmp_path / "devices.toml")
    assert devices[0].mac == "FAKE SERIAL 123"


def test_update_device_icon_persists_registry_change(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "devices.toml").write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "ancell_bm200"',
                'type = "bm200"',
                'name = "Ancell BM200"',
                'mac = "3C:AB:72:82:86:EA"',
                "enabled = true",
                'icon_key = "lead_acid_battery"',
                "[devices.battery]",
                'family = "lead_acid"',
                'profile = "regular_lead_acid"',
                'custom_soc_mode = "intelligent_algorithm"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = update_device_icon(
        config_path=config_path,
        device_id="ancell_bm200",
        icon_key="motorcycle_12v",
    )

    assert errors == []
    devices = load_device_registry(tmp_path / "devices.toml")
    assert devices[0].icon_key == "motorcycle_12v"


def test_update_web_preferences_preserves_existing_port_when_only_display_changes(
    tmp_path: Path,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 15",
                "connect_timeout_seconds = 45",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 9091",
                "show_chart_markers = false",
                "visible_device_limit = 4",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=None,
        web_host=None,
        web_port=None,
        show_chart_markers=True,
        visible_device_limit=None,
        appearance=None,
        default_chart_range=None,
        default_chart_metric=None,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.port == 9091
    assert config.web.show_chart_markers is True
    assert config.web.visible_device_limit == 4


def test_update_web_preferences_persists_host_and_enabled_flag(tmp_path: Path) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 15",
                "connect_timeout_seconds = 45",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 9091",
                "show_chart_markers = false",
                "visible_device_limit = 4",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=False,
        web_host="127.0.0.1",
        web_port=8088,
        show_chart_markers=None,
        visible_device_limit=4,
        appearance=None,
        default_chart_range=None,
        default_chart_metric=None,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.enabled is False
    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8088
    assert config.web.visible_device_limit == 4


def test_update_web_preferences_preserves_chart_markers_when_only_port_changes(
    tmp_path: Path,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 15",
                "connect_timeout_seconds = 45",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 80",
                "show_chart_markers = true",
                "visible_device_limit = 4",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=None,
        web_host=None,
        web_port=8088,
        show_chart_markers=None,
        visible_device_limit=None,
        appearance=None,
        default_chart_range=None,
        default_chart_metric=None,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.port == 8088
    assert config.web.show_chart_markers is True
    assert config.web.visible_device_limit == 4


def test_update_web_preferences_persists_appearance(tmp_path: Path) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 15",
                "connect_timeout_seconds = 45",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 9091",
                "show_chart_markers = false",
                "visible_device_limit = 4",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=None,
        web_host=None,
        web_port=None,
        show_chart_markers=None,
        visible_device_limit=None,
        appearance="dark",
        default_chart_range=None,
        default_chart_metric=None,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.appearance == "dark"


def test_update_web_preferences_persists_chart_defaults(tmp_path: Path) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    errors = update_web_preferences(
        config_path=config_path,
        web_enabled=None,
        web_host=None,
        web_port=None,
        show_chart_markers=None,
        visible_device_limit=None,
        appearance=None,
        default_chart_range="90",
        default_chart_metric="temperature",
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.default_chart_range == "90"
    assert config.web.default_chart_metric == "temperature"


def test_update_usb_otg_preferences_persists_enabled_flag(tmp_path: Path) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    errors = update_usb_otg_preferences(config_path=config_path, enabled=True)

    assert errors == []
    config = load_config(config_path)
    assert config.usb_otg.enabled is True


def test_update_usb_otg_preferences_persists_export_settings(tmp_path: Path) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    errors = update_usb_otg_preferences(
        config_path=config_path,
        enabled=True,
        image_width_px=800,
        image_height_px=480,
        image_format="png",
        appearance="dark",
        refresh_interval_seconds=120,
        overview_devices_per_image=10,
        export_battery_overview=True,
        export_fleet_trend=False,
        fleet_trend_metrics=("voltage", "temperature"),
        fleet_trend_range="30",
        fleet_trend_device_ids=("spare_nlp5", "spare_nlp20"),
    )

    assert errors == []
    config = load_config(config_path)
    assert config.usb_otg.enabled is True
    assert config.usb_otg.image_width_px == 800
    assert config.usb_otg.image_height_px == 480
    assert config.usb_otg.image_format == "png"
    assert config.usb_otg.appearance == "dark"
    assert config.usb_otg.refresh_interval_seconds == 120
    assert config.usb_otg.overview_devices_per_image == 10
    assert config.usb_otg.export_battery_overview is True
    assert config.usb_otg.export_fleet_trend is False
    assert config.usb_otg.fleet_trend_metrics == ("voltage", "temperature")
    assert config.usb_otg.fleet_trend_range == "30"
    assert config.usb_otg.fleet_trend_device_ids == ("spare_nlp5", "spare_nlp20")


def test_settings_display_post_persists_appearance_visible_limit_and_chart_defaults(
    tmp_path: Path,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    from bm_gateway.web import serve_management

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        host, port = handle.getsockname()

    server_thread = threading.Thread(
        target=serve_management,
        kwargs={
            "host": host,
            "port": port,
            "config_path": config_path,
            "state_dir": None,
        },
        daemon=True,
    )
    server_thread.start()

    request = urllib.request.Request(
        f"http://{host}:{port}/settings/web",
        data=urllib.parse.urlencode(
            {
                "settings_section": "display",
                "show_chart_markers": "on",
                "visible_device_limit": "4",
                "default_chart_range": "90",
                "default_chart_metric": "temperature",
                "appearance": "dark",
            }
        ).encode("utf-8"),
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5.0) as response:
        assert response.status in {200, 303}

    config = load_config(config_path)
    assert config.web.appearance == "dark"
    assert config.web.visible_device_limit == 4
    assert config.web.default_chart_range == "90"
    assert config.web.default_chart_metric == "temperature"


def test_settings_usb_otg_post_persists_enabled_flag(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    from bm_gateway.web import serve_management

    export_calls: list[tuple[Path, Path | None]] = []
    export_finished = threading.Event()

    def _export_now(
        *,
        config_path: Path,
        state_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        export_calls.append((config_path, state_dir))
        export_finished.set()
        return subprocess.CompletedProcess(["export"], 0, "", "")

    monkeypatch.setattr("bm_gateway.web.export_usb_otg_images_now", _export_now)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        host, port = handle.getsockname()

    server_thread = threading.Thread(
        target=serve_management,
        kwargs={
            "host": host,
            "port": port,
            "config_path": config_path,
            "state_dir": None,
        },
        daemon=True,
    )
    server_thread.start()

    request = urllib.request.Request(
        f"http://{host}:{port}/settings/usb-otg",
        data=urllib.parse.urlencode(
            {
                "usb_otg_enabled": "on",
                "export_fleet_trend": "on",
                "fleet_trend_metrics": "soc",
            }
        ).encode("utf-8"),
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5.0) as response:
        assert response.status == 200
        params = parse_qs(urlparse(response.url).query)
        assert params["message"] == ["Settings saved; USB OTG frame image export started"]

    config = load_config(config_path)
    assert config.usb_otg.enabled is True
    assert export_finished.wait(timeout=1.0)
    assert export_calls == [(config_path, None)]


def test_settings_usb_otg_post_starts_export_without_waiting(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    from bm_gateway.web import serve_management

    export_calls: list[tuple[Path, Path | None]] = []
    export_started = threading.Event()
    export_finished = threading.Event()
    release_export = threading.Event()

    def _export_now(
        *,
        config_path: Path,
        state_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        export_calls.append((config_path, state_dir))
        export_started.set()
        release_export.wait(timeout=5.0)
        export_finished.set()
        return subprocess.CompletedProcess(["export"], 0, "", "")

    monkeypatch.setattr("bm_gateway.web.export_usb_otg_images_now", _export_now)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        host, port = handle.getsockname()

    server_thread = threading.Thread(
        target=serve_management,
        kwargs={
            "host": host,
            "port": port,
            "config_path": config_path,
            "state_dir": None,
        },
        daemon=True,
    )
    server_thread.start()

    request = urllib.request.Request(
        f"http://{host}:{port}/settings/usb-otg",
        data=urllib.parse.urlencode(
            {
                "usb_otg_enabled": "on",
                "export_fleet_trend": "on",
                "fleet_trend_metrics": "soc",
            }
        ).encode("utf-8"),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            assert response.status == 200
            params = parse_qs(urlparse(response.url).query)
            assert params["message"] == ["Settings saved; USB OTG frame image export started"]
    finally:
        release_export.set()

    assert export_started.wait(timeout=1.0)
    assert export_finished.wait(timeout=2.0)
    assert export_calls == [(config_path, None)]


def test_settings_usb_otg_post_rejects_non_numeric_values_without_snapshot(
    tmp_path: Path,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    from bm_gateway.web import serve_management

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        host, port = handle.getsockname()

    server_thread = threading.Thread(
        target=serve_management,
        kwargs={
            "host": host,
            "port": port,
            "config_path": config_path,
            "state_dir": tmp_path,
        },
        daemon=True,
    )
    server_thread.start()

    request = urllib.request.Request(
        f"http://{host}:{port}/settings/usb-otg",
        data=urllib.parse.urlencode(
            {
                "usb_otg_enabled": "on",
                "image_width_px": "wide",
                "export_fleet_trend": "on",
                "fleet_trend_metrics": "soc",
            }
        ).encode("utf-8"),
        method="POST",
    )

    try:
        urllib.request.urlopen(request, timeout=5.0)
    except urllib.error.HTTPError as error:
        html = error.read().decode("utf-8")
        assert error.code == 400
    else:  # pragma: no cover - the request must fail validation
        raise AssertionError("USB OTG settings POST unexpectedly succeeded")

    assert "Validation failed: USB OTG settings values must be numeric" in html


def test_manual_usb_otg_export_redirects_to_progress_page_and_reports_status(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        Path("python/config/config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    from bm_gateway.web import serve_management

    export_finished = threading.Event()
    marker_calls: list[Path | None] = []

    update_force_values: list[object] = []

    def _update_drive(**kwargs: object) -> USBOTGExportResult:
        update_force_values.append(kwargs.get("force"))
        progress = kwargs.get("progress")
        if callable(progress):
            progress(0, 3, "Preparing USB OTG frame image export")
            progress(1, 3, "Rendered frame image")
            progress(2, 3, "Writing images to USB OTG drive")
            progress(3, 3, "USB OTG frame images exported")
        export_finished.set()
        return USBOTGExportResult(exported=True, reason="exported")

    def _mark_exported(**kwargs: object) -> None:
        state_dir = kwargs.get("state_dir")
        marker_calls.append(state_dir if isinstance(state_dir, Path) else None)

    monkeypatch.setattr("bm_gateway.web.update_usb_otg_drive", _update_drive)
    monkeypatch.setattr("bm_gateway.web.mark_usb_otg_exported", _mark_exported)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        host, port = handle.getsockname()

    server_thread = threading.Thread(
        target=serve_management,
        kwargs={
            "host": host,
            "port": port,
            "config_path": config_path,
            "state_dir": tmp_path,
        },
        daemon=True,
    )
    server_thread.start()

    request = urllib.request.Request(
        f"http://{host}:{port}/actions/export-usb-otg-images",
        data=b"",
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        html = response.read().decode("utf-8")
        assert response.status == 200
        assert urlparse(response.url).path == "/usb-otg-export/progress"
        assert "Frame Image Export" in html

    assert export_finished.wait(timeout=1.0)
    assert marker_calls == [tmp_path]
    assert update_force_values == [True]

    status_request = urllib.request.Request(
        f"http://{host}:{port}/api/usb-otg-export/status",
        headers={"Accept-Language": "it"},
    )
    with urllib.request.urlopen(status_request, timeout=5.0) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert payload["status"] == "completed"
    assert payload["completed"] == 3
    assert payload["total"] == 3
    assert payload["percent"] == 100
    assert payload["message"] == "Immagini cornice USB OTG esportate"


def test_compact_mac_address_is_normalized() -> None:
    assert normalize_mac_address("A1B2C3D4E5F6") == "A1:B2:C3:D4:E5:F6"


def test_empty_device_registry_is_allowed() -> None:
    assert validate_devices([]) == []


def test_validate_devices_rejects_mqtt_unsafe_device_ids() -> None:
    from bm_gateway.device_registry import Device

    errors = validate_devices(
        [
            Device(
                id="spare/nlp5",
                type="bm200",
                name="Spare NLP5",
                mac="AA:BB:CC:DD:EE:01",
            )
        ]
    )

    assert (
        "device spare/nlp5 id must contain only letters, numbers, underscores, or hyphens" in errors
    )


def test_build_run_once_command_targets_module_entrypoint(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"

    command = build_run_once_command(config_path, state_dir=state_dir)

    assert command[1:4] == ["-m", "bm_gateway", "--config"]
    assert command[-4:] == ["run", "--once", "--state-dir", str(state_dir)]


def test_build_run_once_command_can_publish_discovery(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"

    command = build_run_once_command(
        config_path,
        state_dir=state_dir,
        publish_discovery=True,
    )

    assert "--publish-discovery" in command
    assert command.index("--publish-discovery") > command.index("--once")
    assert command[-2:] == ["--state-dir", str(state_dir)]


def test_render_management_html_includes_contract_and_storage_sections() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_management_html(
        snapshot={"generated_at": "2026-04-17T20:00:00+02:00", "devices": []},
        config=config,
        storage_summary={
            "counts": {
                "gateway_snapshots": 3,
                "device_readings": 30,
                "device_daily_rollups": 10,
            },
            "devices": [
                {
                    "device_id": "bm200_house",
                    "raw_samples": 30,
                    "raw_first_ts": "2026-04-01T00:00:00+00:00",
                    "raw_last_ts": "2026-04-17T00:00:00+00:00",
                    "daily_days": 10,
                    "daily_first_day": "2026-04-01",
                    "daily_last_day": "2026-04-17",
                }
            ],
        },
        devices=[
            {
                "id": "bm200_house",
                "type": "bm200",
                "name": "BM200 House",
                "mac": "AA:BB:CC:DD:EE:01",
                "enabled": True,
                "icon_key": "car_12v",
            }
        ],
        config_text='[gateway]\nname = "BMGateway"\n',
        devices_text='[[devices]]\nid = "bm200_house"\n',
        contract={
            "gateway": {
                "state_topic": "bm_gateway/gateway/state",
                "discovery_topic": "homeassistant/device/bm_gateway/config",
            },
            "devices": [{"id": "bm200_house"}],
        },
        message="Configuration saved",
    )

    assert "Home Assistant Contract" not in html
    assert "Storage Summary" not in html
    assert "/api/ha/contract" not in html
    assert "Prune History Using Retention Settings" not in html
    assert "Done" in html
    assert "Web Service" in html
    assert "Display Settings" in html
    assert "Save gateway settings" in html
    assert "Configuration Files" not in html
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="Primary"' in html
    assert 'name="settings_section" value="web"' in html
    assert 'name="settings_section" value="display"' in html
    assert 'action="/settings/gateway"' in html
    assert __version__ not in html
    assert "build" in html


def test_render_management_html_includes_analytics_and_device_links() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_management_html(
        snapshot={
            "generated_at": "2026-04-17T20:00:00+02:00",
            "devices": [{"id": "bm200_house", "name": "BM200 House"}],
        },
        config=config,
        storage_summary={
            "counts": {
                "gateway_snapshots": 3,
                "device_readings": 30,
                "device_daily_rollups": 10,
            },
            "devices": [],
        },
        devices=[
            {
                "id": "bm200_house",
                "type": "bm200",
                "name": "BM200 House",
                "mac": "AA:BB:CC:DD:EE:01",
                "enabled": True,
                "icon_key": "car_12v",
            }
        ],
        config_text='[gateway]\nname = "BMGateway"\n',
        devices_text='[[devices]]\nid = "bm200_house"\n',
        contract={"gateway": {}, "devices": []},
        message="ok",
    )

    assert "/api/analytics?device_id=" not in html
    assert "Gateway Overview" not in html
    assert "Operational Surfaces" not in html
    assert "Recover Bluetooth Adapter" not in html
    assert "Save gateway settings" in html


def test_render_settings_html_is_summary_first_with_edit_link() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={"devices": [], "mqtt_connected": False},
        devices=[],
    )

    assert "Gateway Settings" in html
    assert "MQTT Settings" in html
    assert "Home Assistant Settings" in html
    assert "MQTT broker host" in html
    assert "MQTT broker connection" in html
    assert '<span class="status-badge error">Disconnected</span>' in html
    assert "MQTT broker port" in html
    assert "MQTT username" in html
    assert "MQTT password" in html
    assert "Home Assistant status topic" in html
    assert "Web Service" in html
    assert "Display Settings" in html
    assert "Visible overview cards" in html
    assert "Edit settings" in html
    assert 'href="/settings?edit=1"' in html
    assert "Save display settings" not in html
    assert "Save web service settings" not in html
    assert "Run One Collection Cycle" in html
    assert "Republish Home Assistant Discovery" in html
    assert 'action="/actions/republish-discovery"' in html
    assert "Restart bm-gateway service" in html
    assert "Restart Bluetooth service" in html
    assert "Reboot Raspberry Pi" in html
    assert "Reboot the Raspberry Pi now?" in html
    assert "Shut Down Raspberry Pi" in html
    assert 'action="/actions/shutdown-host"' in html
    assert "Shut down the Raspberry Pi now?" in html
    assert "Home Assistant MQTT Discovery" in html
    assert "Storage Summary" in html
    assert "Configuration Files" in html
    assert 'id="config-toml-readonly"' in html
    assert 'id="devices-toml-readonly"' in html
    assert "readonly" in html
    assert html.index('section-title">Gateway Overview') < html.index('section-title">Actions')
    assert html.index('section-title">Actions') < html.index('section-title">Gateway Settings')
    assert html.index('section-title">Gateway Settings') < html.index(
        'section-title">MQTT Settings'
    )
    assert html.index('section-title">MQTT Settings') < html.index(
        'section-title">Home Assistant Settings'
    )
    assert html.index('section-title">Home Assistant Settings') < html.index(
        'section-title">Home Assistant MQTT Discovery'
    )
    assert html.index('section-title">Home Assistant MQTT Discovery') < html.index(
        'section-title">Web Service'
    )
    assert html.index('section-title">Home Assistant MQTT Discovery') < html.index(
        'section-title">Storage Summary'
    )


def test_render_settings_html_shows_connected_mqtt_status_in_green() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={"devices": [], "mqtt_connected": True},
        devices=[],
    )

    assert '<span class="status-badge ok">Connected</span>' in html


def test_render_settings_html_summary_shows_appearance() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, web=replace(config.web, appearance="system"))
    html = render_settings_html(config=config, snapshot={}, devices=[], edit_mode=False)

    assert "Appearance" in html
    assert "System" in html


def test_render_settings_html_storage_summary_filters_removed_devices() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[
            {
                "id": "ancell_bm200",
                "type": "bm200",
                "name": "Ancell BM200",
                "mac": "AA:BB:CC:DD:EE:01",
            },
            {
                "id": "spare_nlp20",
                "type": "bm200",
                "name": "Spare NLP20",
                "mac": "AA:BB:CC:DD:EE:02",
            },
        ],
        edit_mode=False,
        storage_summary={
            "counts": {
                "gateway_snapshots": 3,
                "device_readings": 30,
                "device_daily_rollups": 10,
            },
            "devices": [
                {"device_id": "ancell_bm200", "raw_samples": 10},
                {"device_id": "bm200_house", "raw_samples": 10},
                {"device_id": "bm300_van", "raw_samples": 10},
                {"device_id": "fake_serial_test", "raw_samples": 10},
                {"device_id": "spare_nlp20", "raw_samples": 10},
            ],
        },
    )

    assert "ancell_bm200" in html
    assert "spare_nlp20" in html
    assert "bm200_house" not in html
    assert "bm300_van" not in html
    assert "fake_serial_test" not in html


def test_render_settings_html_summary_shows_chart_defaults() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        web=replace(config.web, default_chart_range="7", default_chart_metric="soc"),
    )
    html = render_settings_html(config=config, snapshot={}, devices=[], edit_mode=False)

    assert "Default chart range" in html
    assert "7 days" in html
    assert "Default chart metric" in html
    assert "State of Charge" in html


def test_render_settings_html_shows_disabled_usb_otg_export_by_default() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=False,
        usb_otg_support_installed=True,
    )

    assert "USB OTG Image Export" in html
    assert "USB OTG image export" in html
    assert "Disabled" in html
    assert "USB OTG support" in html
    assert "Installed" in html
    assert "USB OTG device controller" in html
    assert "Output size" in html
    assert "480 x 234 px" in html
    assert "Output format" in html
    assert "JPEG" in html
    assert "Devices per overview image" in html
    assert "Backing disk image" in html


def test_render_settings_html_warns_when_usb_otg_support_not_installed() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=True,
        usb_otg_support_installed=False,
    )

    assert "USB OTG support was not installed on this system" in html
    assert "--skip-usb-otg-tools" in html
    assert "Not installed" in html
    assert "Prepare USB OTG Mode" not in html
    assert "Export Frame Images" not in html
    assert "Export Frame Images Now" not in html
    assert "Refresh USB OTG Drive" not in html


def test_render_settings_html_non_edit_actions_show_usb_otg_drive_actions() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=False,
        usb_otg_support_installed=True,
    )

    assert "Actions" in html
    assert "Refresh USB OTG Drive" in html
    assert 'action="/actions/refresh-usb-otg-drive"' in html
    assert "Export Frame Images" in html
    assert "Export Frame Images Now" not in html
    assert 'action="/actions/export-usb-otg-images"' in html


def test_render_settings_html_non_edit_header_links_to_diagnostics() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=False,
        usb_otg_support_installed=True,
    )

    assert '<a class="secondary-button" href="/diagnostics">Diagnostics</a>' in html
    assert "Exit Diagnostics" not in html


def test_render_diagnostics_html_embeds_frame_preview() -> None:
    html = render_diagnostics_html(theme_preference="dark")

    assert "Diagnostics" in html
    assert '<a class="secondary-button" href="/settings">Back to Settings</a>' in html
    assert "Frame Preview" in html
    assert 'target="frame-preview-display"' in html
    assert '<iframe class="frame-preview-display"' in html
    assert 'name="frame-preview-display"' in html
    assert 'src="/frame/fleet-trend?metric=soc"' in html
    assert 'title="Frame Preview"' not in html
    assert 'aria-label="Frame Preview"' in html
    assert "Fleet Trend SoC" in html
    assert ">Fleet Trend</a>" not in html
    assert 'href="/frame/battery-overview?page=1"' in html
    assert "Battery Overview Page 1" in html


def test_render_diagnostics_html_lists_only_enabled_fleet_metric_previews() -> None:
    html = render_diagnostics_html(
        theme_preference="dark",
        fleet_trend_metrics=("voltage", "soc", "temperature"),
    )

    assert html.index("Fleet Trend SoC") < html.index("Fleet Trend Temperature")
    assert html.index("Fleet Trend Temperature") < html.index("Fleet Trend Voltage")
    assert html.count("Fleet Trend SoC") == 1
    assert html.count("Fleet Trend Temperature") == 1
    assert html.count("Fleet Trend Voltage") == 1
    assert ">Fleet Trend</a>" not in html


def test_render_frame_fleet_trend_html_is_clean_screenshot_page() -> None:
    html = render_frame_fleet_trend_html(
        chart_points=[],
        legend=[("Spare NLP5", "#f0b429")],
        show_chart_markers=False,
        appearance="dark",
        default_chart_range="7",
        default_chart_metric="soc",
        width=480,
        height=234,
    )

    assert "<span>Fleet Trend</span> · <span>SoC</span> · <span>7 days</span>" in html
    assert "<span>Latest:</span> <span>No data</span>" in html
    assert "Spare NLP5" in html
    assert 'id="frame-fleet-trend-chart"' in html
    assert 'class="bottom-nav"' not in html
    assert 'class="page-shell"' not in html
    assert "pointer-events: none;" in html
    assert "background: var(--bg-app);" in html
    assert 'class="chart-frame" id="frame-fleet-trend-chart" data-chart-compact="true"' in html
    assert ".frame-capture-root .chart-nav-arrow" in html
    assert ".frame-capture-root .chart-tooltip" in html
    assert ".frame-capture-root .chart-meta" in html
    assert "inset: 30px 0 0;" in html
    assert "padding: 0;" in html
    assert "background: transparent;" in html
    assert "top: 10px;" in html
    assert "left: 5px;" in html
    assert "const padLeft = isCompact ? 30 : 68;" in html
    assert "const padBottom = isCompact ? 20 : 44;" in html
    assert "line-height: 1.25;" in html
    assert "font-size: 8px;" in html
    assert "border: 0;" in html
    assert "display: none;" in html
    assert "--frame-width: 480px;" in html
    assert "--frame-height: 234px;" in html


def test_render_frame_fleet_trend_html_localizes_latest_label_to_italian() -> None:
    html = render_frame_fleet_trend_html(
        chart_points=[
            {
                "ts": "2026-04-24T01:05:00+02:00",
                "series": "Spare NLP20",
                "series_color": "#ec5c86",
                "soc": 91,
                "voltage": 13.31,
                "temperature": 24.0,
            },
        ],
        legend=[("Spare NLP20", "#ec5c86")],
        show_chart_markers=False,
        appearance="dark",
        default_chart_range="30",
        default_chart_metric="voltage",
        width=480,
        height=234,
        language="it",
    )

    assert "Andamento flotta" in html
    assert "Voltaggio" in html
    assert "30 giorni" in html
    assert "Ultimo:" in html
    assert "Latest:" not in html


def test_render_frame_fleet_trend_html_uses_selected_metric_range_and_device_values() -> None:
    html = render_frame_fleet_trend_html(
        chart_points=[
            {
                "ts": "2026-04-24T01:00:00+02:00",
                "series": "Spare NLP5",
                "series_color": "#f0b429",
                "soc": 88,
                "voltage": 13.29,
                "temperature": 23.0,
            },
            {
                "ts": "2026-04-24T01:05:00+02:00",
                "series": "Spare NLP20",
                "series_color": "#ec5c86",
                "soc": 91,
                "voltage": 13.31,
                "temperature": 24.0,
            },
        ],
        legend=[("Spare NLP5", "#f0b429"), ("Spare NLP20", "#ec5c86")],
        show_chart_markers=False,
        appearance="dark",
        default_chart_range="30",
        default_chart_metric="temperature",
        width=480,
        height=234,
    )

    assert "<span>Fleet Trend</span> · <span>Temperature</span> · <span>30 days</span>" in html
    assert "<span>Latest:</span> <span>2026-04-24 01:05</span>" in html
    assert "Spare NLP5 23.0°C" in html
    assert "Spare NLP20 24.0°C" in html
    assert 'data-metric="temperature" class="active"' in html
    assert 'data-range="30" data-range-label="30 days" class="active"' in html


def test_render_frame_battery_overview_html_uses_fixed_frame_cards() -> None:
    html = render_frame_battery_overview_html(
        snapshot={
            "devices": [
                {
                    "id": "spare_nlp5",
                    "name": "Spare NLP5",
                    "soc": 91,
                    "voltage": 13.1,
                    "temperature": 22.5,
                    "last_seen": "2026-04-24T03:12:24+02:00",
                    "state": "normal",
                    "connected": True,
                }
            ]
        },
        devices=[
            {
                "id": "spare_nlp5",
                "name": "Spare NLP5",
                "color_key": "amber",
                "icon_key": "lead_acid_battery",
            }
        ],
        page=1,
        devices_per_page=5,
        appearance="dark",
        width=480,
        height=234,
    )

    assert "<span>Battery Overview</span> · <span>Latest:</span>" in html
    assert "<span>2026-04-24 03:12</span>" in html
    assert "Spare NLP5" in html
    assert "frame-battery-card" in html
    assert "frame-battery-soc" in html
    assert "91%" in html
    assert 'class="bottom-nav"' not in html


def test_render_frame_battery_overview_html_uses_configured_enabled_devices_only() -> None:
    html = render_frame_battery_overview_html(
        snapshot={
            "devices": [
                {
                    "id": "enabled_battery",
                    "name": "Enabled Runtime Name",
                    "soc": 91,
                    "voltage": 13.1,
                    "last_seen": "2026-04-24T03:12:24+02:00",
                    "enabled": True,
                },
                {
                    "id": "disabled_battery",
                    "name": "Disabled Runtime Name",
                    "soc": 44,
                    "voltage": 12.1,
                    "last_seen": "2026-04-24T03:13:24+02:00",
                    "enabled": True,
                },
                {
                    "id": "removed_battery",
                    "name": "Removed Runtime Name",
                    "soc": 55,
                    "voltage": 12.4,
                    "last_seen": "2026-04-24T03:14:24+02:00",
                    "enabled": True,
                },
            ]
        },
        devices=[
            {"id": "enabled_battery", "name": "Enabled Config Name", "enabled": True},
            {"id": "disabled_battery", "name": "Disabled Config Name", "enabled": False},
        ],
        page=1,
        devices_per_page=5,
        appearance="dark",
        width=480,
        height=234,
    )

    assert "Enabled Config Name" in html
    assert "91%" in html
    assert "Disabled Config Name" not in html
    assert "Disabled Runtime Name" not in html
    assert "Removed Runtime Name" not in html


def test_render_frame_battery_overview_html_fits_cards_inside_frame() -> None:
    html = render_frame_battery_overview_html(
        snapshot={
            "devices": [
                {"id": "one", "name": "Spare NLP5", "soc": 86, "voltage": 13.29},
                {
                    "id": "two",
                    "name": "Spare NLP20",
                    "soc": 88,
                    "voltage": 13.29,
                    "last_seen": "2026-04-24T03:20:00+02:00",
                },
            ]
        },
        devices=[
            {"id": "one", "name": "Spare NLP5", "enabled": True},
            {"id": "two", "name": "Spare NLP20", "enabled": True},
        ],
        page=1,
        devices_per_page=5,
        appearance="dark",
        width=480,
        height=234,
    )

    assert "display: block;" in html
    assert "frame-battery-stage" in html
    assert "--frame-overview-card-size: 208px;" in html
    assert "position: absolute;" in html
    assert "width: 208px; height: 208px;" in html
    assert "left: 17.0px; top: 22.0px;" in html
    assert "conic-gradient(" in html
    assert "font-size: 12px;" in html
    assert "<span>Battery Overview</span> · <span>Latest:</span>" in html
    assert "<span>2026-04-24 03:20</span>" in html


def test_render_settings_html_warns_when_usb_otg_enabled_without_controller() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, usb_otg=replace(config.usb_otg, enabled=True))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=False,
        usb_otg_device_controller_detected=False,
        usb_otg_support_installed=True,
    )

    assert "USB OTG image export is enabled" in html
    assert "no USB OTG device controller is currently detected" in html
    assert "Zero USB Plug" in html


def test_render_settings_html_edit_mode_shows_prepare_when_usb_otg_boot_mode_not_prepared() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=True,
        usb_otg_boot_mode_prepared=False,
        usb_otg_support_installed=True,
    )

    assert "Prepare USB OTG Mode" in html
    assert 'action="/actions/prepare-usb-otg-mode"' in html
    assert "Restore USB Host Mode" not in html
    assert 'action="/actions/restore-usb-host-mode"' not in html


def test_render_settings_html_edit_mode_shows_restore_when_usb_otg_boot_mode_prepared() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=True,
        usb_otg_boot_mode_prepared=True,
        usb_otg_support_installed=True,
    )

    assert "Prepare USB OTG Mode" not in html
    assert 'action="/actions/prepare-usb-otg-mode"' not in html
    assert "Restore USB Host Mode" in html
    assert 'action="/actions/restore-usb-host-mode"' in html
    assert "Refresh USB OTG Drive" not in html
    assert 'action="/actions/refresh-usb-otg-drive"' not in html
    assert "Export Frame Images" not in html
    assert 'action="/actions/export-usb-otg-images"' not in html


def test_render_settings_html_edit_mode_merges_summary_and_edit_controls() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={"generated_at": "2026-04-17T20:00:00+02:00", "devices": []},
        devices=[],
        edit_mode=True,
        message="Settings saved",
        storage_summary={
            "counts": {
                "gateway_snapshots": 3,
                "device_readings": 30,
                "device_daily_rollups": 10,
            },
            "devices": [],
        },
        config_text='[gateway]\nname = "BMGateway"\n',
        devices_text="",
        contract={
            "gateway": {
                "state_topic": "bm_gateway/gateway/state",
                "discovery_topic": "homeassistant/device/bm_gateway/config",
            },
            "devices": [],
        },
    )

    assert "Gateway Settings" in html
    assert "Gateway Overview" not in html
    assert "MQTT Settings" in html
    assert "Home Assistant Settings" in html
    assert "Web Service" in html
    assert "Display Settings" in html
    assert "USB OTG Image Export" in html
    assert "Save gateway settings" in html
    assert "Save MQTT settings" in html
    assert "Save Home Assistant settings" in html
    assert "Save web service settings" in html
    assert "Save display settings" in html
    assert "Save USB OTG settings" in html
    assert 'name="gateway_name"' in html
    assert 'name="timezone"' in html
    assert '<select id="timezone-input" name="timezone" autocomplete="off" translate="no">' in html
    assert '<input id="timezone-input" type="text"' not in html
    assert '<option value="Europe/Rome" selected>Europe/Rome</option>' in html
    assert '<option value="UTC">UTC</option>' in html
    assert 'name="mqtt_host"' in html
    assert 'name="mqtt_port"' in html
    assert 'name="mqtt_username"' in html
    assert 'name="mqtt_password"' in html
    assert 'name="mqtt_base_topic"' in html
    assert 'name="mqtt_discovery_prefix"' in html
    assert 'name="mqtt_retain_discovery"' in html
    assert 'name="mqtt_retain_state"' in html
    assert 'name="home_assistant_status_topic"' in html
    assert 'name="home_assistant_gateway_device_id"' in html
    assert 'name="web_host"' in html
    assert 'name="usb_otg_enabled"' in html
    assert 'name="image_width_px"' in html
    assert 'name="image_height_px"' in html
    assert 'name="image_format"' in html
    assert 'name="appearance"' in html
    assert 'name="refresh_interval_seconds"' in html
    assert 'name="overview_devices_per_image"' in html
    assert 'name="export_battery_overview"' in html
    assert 'name="export_fleet_trend"' in html
    assert 'name="fleet_trend_metrics"' in html
    assert 'name="fleet_trend_range"' in html
    assert 'name="fleet_trend_device_ids"' in html
    assert 'name="web_enabled"' in html
    assert 'name="visible_device_limit"' in html
    assert 'name="bluetooth_adapter"' in html
    assert 'name="scan_timeout_seconds"' in html
    assert 'name="connect_timeout_seconds"' in html
    assert "Configuration Files" not in html
    assert "Home Assistant MQTT Discovery" not in html
    assert "Storage Summary" not in html
    assert "Run One Collection Cycle" not in html
    assert "Recover Bluetooth Adapter" not in html
    assert 'href="/settings"' in html
    assert "Leave blank if your broker allows anonymous connections." in html
    assert (
        "Keeps discovery messages on the broker so Home Assistant can rediscover the gateway "
        "after restarts."
    ) in html
    assert (
        "Publishes Home Assistant-compatible MQTT discovery messages so entities can appear "
        "automatically."
    ) in html


def test_render_settings_html_edit_mode_shows_appearance_options() -> None:
    html = render_settings_html(
        config=load_config(Path("python/config/config.toml.example")),
        snapshot={},
        devices=[],
        edit_mode=True,
    )

    assert 'name="appearance"' in html
    assert '<option value="light"' in html
    assert '<option value="dark"' in html
    assert '<option value="system"' in html


def test_render_settings_html_edit_mode_shows_chart_default_options() -> None:
    html = render_settings_html(
        config=load_config(Path("python/config/config.toml.example")),
        snapshot={},
        devices=[],
        edit_mode=True,
    )

    assert 'name="default_chart_range"' in html
    assert 'name="default_chart_metric"' in html
    assert '<option value="7" selected>' in html
    assert '<option value="3"' in html
    assert '<option value="5"' in html
    assert '<option value="raw"' not in html
    assert '<option value="soc" selected>' in html


def test_discover_bluetooth_adapters_reads_sysfs_entries(tmp_path: Path) -> None:
    hci0 = tmp_path / "hci0"
    hci0.mkdir()
    (hci0 / "address").write_text("AA:BB:CC:DD:EE:FF\n", encoding="utf-8")
    (hci0 / "name").write_text("Primary Adapter\n", encoding="utf-8")
    (tmp_path / "rfkill0").mkdir()

    adapters = _discover_bluetooth_adapters(tmp_path)

    assert adapters == [
        {
            "name": "hci0",
            "address": "AA:BB:CC:DD:EE:FF",
            "alias": "Primary Adapter",
        }
    ]


def test_render_settings_html_edit_mode_highlights_missing_bluetooth_adapter() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=True,
        detected_bluetooth_adapters=[],
    )

    assert "No Bluetooth adapters detected on this host." in html
    assert '<option value="auto"' in html


def test_render_settings_html_edit_mode_marks_configured_adapter_missing() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        edit_mode=True,
        detected_bluetooth_adapters=[{"name": "hci0", "address": "", "alias": "hci0"}],
    )

    assert "Detected adapters: hci0." in html


def test_render_home_html_renders_device_icon() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "ancell_bm200",
                    "name": "Ancell BM200",
                    "type": "bm200",
                    "soc": 91,
                    "voltage": 13.31,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                    "installed_in_vehicle": True,
                    "vehicle_type": "motorcycle",
                }
            ]
        },
        devices=[
            {
                "id": "ancell_bm200",
                "name": "Ancell BM200",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "installed_in_vehicle": True,
                "vehicle_type": "motorcycle",
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "device-icon-frame" in html
    assert 'data-icon-key="lead_acid_battery"' in html
    assert 'data-icon-key="vehicle_motorcycle"' in html
    assert "device-icon-frame battery-tile-icon" in html
    assert "battery-card-gauge" in html
    assert "battery-card-gauge-value" in html
    assert "battery-card-status" in html
    assert "battery-card-status-inline" in html
    assert "Battery OK" in html
    assert "home-overview-card-link" in html
    assert "home-overview-orb" in html
    assert "home-orb-layout" in html
    assert "Open device" not in html
    assert "All" in html
    assert "home-overview-scroller" in html
    assert 'aria-label="Show previous home cards"' not in html
    assert 'aria-label="Show next home cards"' not in html
    assert "home-overview-page" in html
    assert "--overview-columns:" in html
    assert "Add Device" in html
    assert (
        '<div class="hero-actions"><a class="secondary-button" href="/settings">Settings</a>'
        not in html
    )


def test_render_home_html_threads_appearance_to_document_root() -> None:
    html = render_home_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
        appearance="dark",
    )

    assert 'data-theme-preference="dark"' in html
    assert "<h1>BMGateway</h1>" in html
    assert "Bluetooth device status is shown directly on each card." not in html
    assert 'class="header-build-badge"' in html
    assert 'rel="icon" href="/favicon.png" sizes="32x32" type="image/png"' in html
    assert 'rel="icon" href="/favicon.svg"' in html
    assert 'rel="apple-touch-icon" href="/apple-touch-icon.png"' in html
    assert 'rel="manifest" href="/site.webmanifest"' in html


def test_render_home_html_defaults_chart_to_seven_days_and_soc() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
    )

    assert 'data-range="7" data-range-label="7 days" class="active"' in html
    assert 'data-range="3" data-range-label="3 days"' in html
    assert 'data-range="5" data-range-label="5 days"' in html
    assert 'data-range="raw"' not in html
    assert 'data-metric="soc" class="active"' in html


def test_render_home_html_uses_shared_icon_badge_markup() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "ancell_bm200",
                    "name": "Ancell BM200",
                    "type": "bm200",
                    "soc": 91,
                    "voltage": 13.31,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                    "installed_in_vehicle": True,
                    "vehicle_type": "motorcycle",
                }
            ]
        },
        devices=[
            {
                "id": "ancell_bm200",
                "name": "Ancell BM200",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "installed_in_vehicle": True,
                "vehicle_type": "motorcycle",
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "battery-card-badge" in html
    assert "battery-tile-icon" in html
    assert "badge-placeholder" in html


def test_render_home_html_prefers_registry_name_over_stale_snapshot_name() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "ancell_bm200",
                    "name": "Ancell BM200",
                    "type": "bm200",
                    "soc": 91,
                    "voltage": 13.31,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                }
            ]
        },
        devices=[
            {
                "id": "ancell_bm200",
                "name": "NLP5",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "NLP5" in html
    assert "Ancell BM200" not in html


def test_render_home_html_places_identity_and_badges_inside_home_orb() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "ancell_bm200",
                    "name": "Ancell BM200",
                    "type": "bm200",
                    "soc": 91,
                    "voltage": 13.31,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                    "installed_in_vehicle": True,
                    "vehicle_type": "motorcycle",
                }
            ]
        },
        devices=[
            {
                "id": "ancell_bm200",
                "name": "Ancell BM200",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "installed_in_vehicle": True,
                "vehicle_type": "motorcycle",
            }
        ],
        chart_points=[],
        legend=[],
    )

    link_index = html.index("home-overview-card-link")
    link_close_index = html.index("</a>", link_index)
    orb_slice = html[link_index:link_close_index]

    assert "home-orb-head" in orb_slice
    assert "home-orb-badges" in orb_slice
    assert "home-orb-center" in orb_slice
    assert "battery-card-gauge-value" in orb_slice
    assert "battery-card-status-inline" in orb_slice
    assert "battery-card-gauge-label" in orb_slice
    assert "battery-card-gauge-subvalue" in orb_slice
    assert "meta-name" in orb_slice
    assert "meta-context" in orb_slice


def test_render_home_html_uses_compact_home_metadata_line_with_nominal_voltage() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "spare_nlp5",
                    "name": "Spare NLP5",
                    "type": "bm200",
                    "soc": 88,
                    "voltage": 13.30,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                    "battery": {
                        "brand": "NOCO",
                        "model": "NLP5",
                        "nominal_voltage": 12,
                        "capacity_ah": 5.0,
                        "production_year": 2025,
                    },
                }
            ]
        },
        devices=[
            {
                "id": "spare_nlp5",
                "name": "Spare NLP5",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "battery": {
                    "brand": "NOCO",
                    "model": "NLP5",
                    "nominal_voltage": 12,
                    "capacity_ah": 5.0,
                    "production_year": 2025,
                },
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "NOCO NLP5 12 V 5.0 Ah" in html
    assert "2025" not in html


def test_base_css_stacks_battery_badges_next_to_identity_copy() -> None:
    css = base_css()

    assert ".home-overview-card {" in css
    assert ".home-overview-card-link {" in css
    assert ".home-overview-orb {" in css
    assert ".home-orb-layout {" in css
    assert ".home-orb-head {" in css
    assert ".device-badge-stack {" in css
    assert ".device-icon-frame {" in css
    assert "aspect-ratio: 1 / 1;" in css
    assert ".battery-card-badge {" in css
    assert "place-items: center;" in css
    assert "justify-content: flex-start;" in css
    assert ".history-device-badge {" in css
    assert "min-width: 48px;" in css
    assert "min-height: 48px;" in css
    assert "padding: 0.85rem 0.95rem 0.85rem 1.1rem;" in css


def test_base_css_highlights_selected_history_device_with_device_accent() -> None:
    css = base_css()

    assert ".history-device-card {" in css
    assert "border-color: color-mix(in srgb, var(--card-accent) 44%, var(--border-soft));" in css
    assert "0 14px 30px color-mix(in srgb, var(--card-accent) 10%, transparent)," in css
    assert ".history-device-card.selected {" in css
    assert "border-color: color-mix(in srgb, var(--card-accent) 72%, var(--border-soft));" in css
    assert "0 16px 34px color-mix(in srgb, var(--card-accent) 18%, transparent)," in css
    assert ".history-device-card.selected .history-device-current {" in css
    assert "color: var(--card-accent);" in css
    assert "font-weight: 800;" in css


def test_base_css_uses_wrapping_flex_layout_for_history_device_selector() -> None:
    css = base_css()

    assert ".history-device-grid {" in css
    assert "display: flex;" in css
    assert "flex-wrap: wrap;" in css
    assert "align-items: flex-start;" in css
    assert "gap: 1rem;" in css


def test_base_css_compacts_raw_history_table() -> None:
    css = base_css()

    assert ".raw-readings-scroll {" in css
    assert "max-height: 24rem;" in css
    assert "overflow: auto;" in css
    assert ".raw-readings-table {" in css
    assert "white-space: nowrap;" in css
    assert "position: sticky;" in css


def test_base_css_strengthens_device_page_cards_with_device_accent() -> None:
    css = base_css()

    assert (
        "--card-accent-soft: color-mix(in srgb, var(--card-accent) 16%, var(--bg-surface));" in css
    )
    assert (
        "--card-accent-soft-strong: color-mix(in srgb, var(--card-accent) 22%, var(--bg-surface));"
        in css
    )
    assert ".devices-grid .tone-card {" in css
    assert "border-color: color-mix(in srgb, var(--card-accent) 44%, var(--border-soft));" in css
    assert "0 14px 30px color-mix(in srgb, var(--card-accent) 10%, transparent)," in css


def test_base_css_exposes_theme_preference_selectors() -> None:
    css = base_css()

    assert 'body[data-theme-preference="light"]' in css
    assert 'body[data-theme-preference="dark"]' in css
    assert 'body[data-theme-preference="system"]' in css
    assert "@media (prefers-color-scheme: dark)" in css


def test_base_css_scales_frame_preview_without_clipping() -> None:
    css = base_css()

    assert ".frame-preview-display {" in css
    assert "width: min(100%, 480px);" in css
    assert "aspect-ratio: 480 / 234;" in css
    assert "height: auto;" in css
    assert "background: var(--bg-app);" in css


def test_base_css_overrides_shared_icon_badge_treatment_in_dark_modes() -> None:
    css = base_css()

    assert "--badge-surface: rgba(248, 252, 249, 0.96);" in css
    assert "--badge-border: rgba(168, 196, 176, 0.62);" in css
    assert "--badge-icon-color: rgba(28, 37, 45, 0.92);" in css
    assert "--badge-accent-stroke: rgba(23, 196, 90, 0.88);" in css
    assert "--badge-surface: rgba(38, 38, 41, 0.98);" in css
    assert "--badge-border: rgba(120, 120, 128, 0.42);" in css
    assert "--badge-icon-color: rgba(245, 245, 247, 0.96);" in css
    assert "--badge-accent-stroke: rgba(72, 222, 137, 0.92);" in css
    assert "@media (prefers-color-scheme: dark)" in css


def test_base_css_uses_coherent_dark_surfaces_and_mobile_card_scaling() -> None:
    css = base_css()

    assert "--bg-app: #111214;" in css
    assert "--bg-surface: #1c1c1e;" in css
    assert "--bg-elevated: #2c2c2e;" in css
    assert "--text-primary: #f5f5f7;" in css
    assert "--text-secondary: rgba(235, 235, 245, 0.78);" in css
    assert ".home-overview-page.is-single-page.page-two-cards {" in css
    assert "justify-content: flex-start;" in css
    assert "background: var(--bg-surface);" in css
    assert ".banner-strip {" in css
    assert "@media (max-width: 640px)" in css
    assert "width: 116px;" in css
    assert "width: 36px;" in css
    assert "height: 36px;" in css
    assert "flex: 0 0 36px;" in css
    assert "inline-size: 36px;" in css
    assert "block-size: 36px;" in css
    assert "max-inline-size: 36px;" in css
    assert "overflow: hidden;" in css
    assert ".device-icon-frame.history-device-badge {" in css
    assert "inline-size: 40px;" in css
    assert "max-inline-size: 40px;" in css
    assert "width: 22px;" in css
    assert "height: 22px;" in css
    assert "width: 30px;" in css
    assert "height: 30px;" in css
    assert "width: 24px;" in css
    assert "height: 24px;" in css
    assert "font-size: clamp(2rem, 5vw, 2.9rem);" in css
    assert "font-size: 0.78rem;" in css
    assert "font-size: 0.82rem;" in css
    assert "font-size: 2.2rem;" in css
    assert "padding: 0.75rem 0.8rem 0.75rem 0.95rem;" in css
    assert ".home-overview-page.is-single-page.page-two-cards," in css


def test_render_devices_html_threads_appearance_to_document_root() -> None:
    html = render_devices_html(
        snapshot={"devices": []},
        devices=[],
        message="",
        theme_preference="dark",
    )

    assert 'data-theme-preference="dark"' in html


def test_render_devices_html_wraps_single_device_in_grid_layout_hook() -> None:
    html = render_devices_html(
        snapshot={"devices": []},
        devices=[
            {
                "id": "ancell_bm200",
                "type": "bm200",
                "name": "Ancell BM200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
            }
        ],
        message="",
        theme_preference="dark",
    )

    assert 'class="device-list-rows"' in html
    assert "device-list-row tone-card green" in html
    assert "Edit device" in html


def test_render_devices_html_reserves_second_badge_slot_for_non_vehicle_devices() -> None:
    html = render_devices_html(
        snapshot={"devices": []},
        devices=[
            {
                "id": "bench_battery",
                "type": "bm200",
                "name": "Bench Battery",
                "mac": "3C:AB:72:00:00:01",
                "enabled": True,
                "installed_in_vehicle": False,
                "battery": {
                    "family": "lithium",
                    "profile": "lithium",
                    "brand": "NOCO",
                    "model": "NLP20",
                },
            }
        ],
        message="",
    )

    assert "device-badge-stack compact" in html
    assert "badge-placeholder" in html


def test_render_history_html_threads_appearance_to_document_root() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
        theme_preference="dark",
    )

    assert 'data-theme-preference="dark"' in html


def test_render_history_html_respects_saved_chart_defaults() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
        default_chart_range="90",
        default_chart_metric="temperature",
    )

    assert 'data-range="90" data-range-label="90 days" class="active"' in html
    assert 'data-range="3" data-range-label="3 days"' in html
    assert 'data-range="5" data-range-label="5 days"' in html
    assert 'data-range="raw"' not in html
    assert 'data-metric="temperature" class="active"' in html


def test_render_history_html_reserves_second_badge_slot_for_non_vehicle_devices() -> None:
    html = render_history_html(
        device_id="bench_battery",
        configured_devices=[
            {
                "id": "bench_battery",
                "name": "Bench Battery",
                "type": "bm200",
                "installed_in_vehicle": False,
                "battery": {
                    "family": "lithium",
                    "profile": "lithium",
                    "brand": "NOCO",
                    "model": "NLP20",
                },
            }
        ],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "history-device-badge" in html
    assert "badge-placeholder" in html


def test_render_settings_html_threads_appearance_to_document_root() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, web=replace(config.web, appearance="dark"))
    html = render_settings_html(
        config=config,
        snapshot={},
        devices=[],
        theme_preference=config.web.appearance,
    )

    assert 'data-theme-preference="dark"' in html


def test_render_home_html_pages_cards_by_visible_device_limit() -> None:
    from bm_gateway.web import render_home_html

    snapshot_devices = [
        {
            "id": f"battery_{index}",
            "name": f"Battery {index}",
            "type": "bm200",
            "soc": 80 + index,
            "voltage": 13.1 + (index * 0.01),
            "temperature": 22.0,
            "state": "normal",
            "connected": True,
            "icon_key": "car_12v",
        }
        for index in range(1, 8)
    ]
    html = render_home_html(
        snapshot={"devices": snapshot_devices},
        devices=[
            {
                "id": device["id"],
                "name": device["name"],
                "type": "bm200",
                "mac": f"AA:BB:CC:DD:EE:{index:02d}",
                "enabled": True,
                "icon_key": "car_12v",
            }
            for index, device in enumerate(snapshot_devices, start=1)
        ],
        chart_points=[],
        legend=[],
        visible_device_limit=4,
    )

    assert html.count('class="home-overview-page page-multi-cards"') == 2
    assert 'class="home-overview-page page-one-card"' not in html
    assert "--overview-columns: 2;" in html
    assert "--overview-rows: 2;" in html
    assert "Battery 7" in html
    assert 'data-direction="previous"' in html
    assert 'data-direction="next"' in html
    assert "home-overview-add-tile" not in html
    assert "icon-button" in html


def test_render_home_html_marks_single_page_card_count() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "ancell_bm200",
                    "name": "Ancell BM200",
                    "type": "bm200",
                    "soc": 90,
                    "voltage": 13.3,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                    "icon_key": "lithium_battery",
                }
            ]
        },
        devices=[
            {
                "id": "ancell_bm200",
                "name": "Ancell BM200",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "icon_key": "lithium_battery",
            }
        ],
        chart_points=[],
        legend=[],
        visible_device_limit=4,
    )

    assert "home-overview-page is-single-page page-one-card" in html


def test_render_home_html_uses_four_by_two_layout_for_eight_visible_cards() -> None:
    from bm_gateway.web import render_home_html

    snapshot_devices = [
        {
            "id": f"battery_{index}",
            "name": f"Battery {index}",
            "type": "bm200",
            "soc": 80 + index,
            "voltage": 13.1 + (index * 0.01),
            "temperature": 22.0,
            "state": "normal",
            "connected": True,
            "icon_key": "lithium_battery",
        }
        for index in range(1, 9)
    ]
    registry_devices = [
        {
            "id": device["id"],
            "name": device["name"],
            "type": "bm200",
            "mac": f"AA:BB:CC:DD:EE:{index:02d}",
            "enabled": True,
            "icon_key": "lithium_battery",
        }
        for index, device in enumerate(snapshot_devices, start=1)
    ]

    html = render_home_html(
        snapshot={"devices": snapshot_devices},
        devices=registry_devices,
        chart_points=[],
        legend=[],
        visible_device_limit=8,
    )

    assert 'class="home-overview-page is-single-page page-multi-cards"' in html
    assert "--overview-columns: 4;" in html
    assert "--overview-rows: 2;" in html
    assert 'class="home-overview-controls"' not in html


def test_render_home_html_keeps_registry_only_devices_visible() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "live_device",
                    "name": "Live Device",
                    "type": "bm200",
                    "soc": 87,
                    "voltage": 13.2,
                    "temperature": 24.0,
                    "state": "normal",
                    "connected": True,
                }
            ]
        },
        devices=[
            {
                "id": "live_device",
                "name": "Live Device",
                "type": "bm200",
                "mac": "AA:BB:CC:DD:EE:01",
                "enabled": True,
                "icon_key": "lithium_battery",
            },
            {
                "id": "pending_device",
                "name": "Pending Device",
                "type": "bm200",
                "mac": "AA:BB:CC:DD:EE:02",
                "enabled": True,
                "icon_key": "lithium_battery",
            },
        ],
        chart_points=[],
        legend=[],
        visible_device_limit=4,
    )

    assert "Live Device" in html
    assert "Pending Device" in html


def test_render_home_html_shows_charging_status_with_explicit_icon() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "bm_charging",
                    "name": "Charging Battery",
                    "type": "bm200",
                    "soc": 100,
                    "voltage": 14.36,
                    "temperature": 19.0,
                    "state": "charging",
                    "connected": True,
                    "icon_key": "lithium_battery",
                }
            ]
        },
        devices=[
            {
                "id": "bm_charging",
                "name": "Charging Battery",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "icon_key": "lithium_battery",
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "Charging" in html
    assert "battery-card-status battery-card-status-inline charging" in html
    assert 'aria-label="Charging"' in html


def test_render_home_html_shows_connection_failure_as_red_warning() -> None:
    from bm_gateway.web import render_home_html

    html = render_home_html(
        snapshot={
            "devices": [
                {
                    "id": "bm_offline",
                    "name": "Offline Battery",
                    "type": "bm200",
                    "soc": 0,
                    "voltage": 0.0,
                    "temperature": None,
                    "state": "offline",
                    "connected": False,
                    "error_code": "device_not_found",
                    "error_detail": "No BLE advertisement seen during the scan window.",
                }
            ]
        },
        devices=[
            {
                "id": "bm_offline",
                "name": "Offline Battery",
                "type": "bm200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "icon_key": "lithium_battery",
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "Unable to connect" in html
    assert "battery-card-status battery-card-status-inline error" in html
    assert 'aria-label="Unable to connect"' in html
    assert "No recent sample" not in html


def test_render_device_html_keeps_reported_status_badge_for_offline_state() -> None:
    html = render_device_html(
        device_id="bm_offline",
        raw_history=[],
        daily_history=[],
        monthly_history=[],
        yearly_history=[],
        analytics={"windows": []},
        device_summary={
            "name": "Offline Battery",
            "soc": 0,
            "voltage": 0.0,
            "temperature": None,
            "rssi": None,
            "state": "offline",
            "error_code": "device_not_found",
            "error_detail": "No BLE advertisement seen during the scan window.",
            "last_seen": "2026-04-22T16:30:00+02:00",
            "connected": False,
            "battery": {
                "brand": "NOCO",
                "model": "NLP5",
                "nominal_voltage": 12,
                "capacity_ah": 5.0,
                "production_year": 2025,
            },
            "installed_in_vehicle": False,
        },
    )

    assert "Reported Status" in html
    assert '<span class="status-badge offline">Unable to connect</span>' in html
    assert '<div class="status-scale" role="img"' not in html
    assert "No BLE advertisement seen during the scan window." in html


def test_chart_points_ignore_error_rows_and_empty_raw_samples() -> None:
    points = _chart_points(
        raw_history=[
            {
                "ts": "2026-04-19T10:00:00+02:00",
                "voltage": 0.0,
                "soc": 0,
                "temperature": None,
                "error_code": "timeout",
            },
            {
                "ts": "2026-04-19T10:05:00+02:00",
                "voltage": 13.32,
                "soc": 92,
                "temperature": 17.2,
                "error_code": None,
            },
        ],
        daily_history=[
            {
                "day": "2026-04-18",
                "samples": 4,
                "avg_voltage": 13.31,
                "avg_soc": 91,
            }
        ],
    )

    assert len(points) == 2
    assert [point["kind"] for point in points] == ["daily", "raw"]
    assert points[-1]["voltage"] == 13.32
    assert points[-1]["soc"] == 92


def test_chart_points_include_daily_temperature_rollups() -> None:
    points = _chart_points(
        raw_history=[],
        daily_history=[
            {
                "day": "2026-04-18",
                "samples": 4,
                "avg_voltage": 13.31,
                "avg_soc": 91,
                "avg_temperature": 22.4,
            }
        ],
    )

    assert points == [
        {
            "ts": "2026-04-18T12:00:00",
            "label": "04-18",
            "kind": "daily",
            "voltage": 13.31,
            "soc": 91,
            "temperature": 22.4,
            "series": "Series",
            "series_color": "#4f8df7",
        }
    ]


def test_render_device_html_escapes_history_values_and_renders_chart() -> None:
    html = render_device_html(
        device_id="bm200_house",
        raw_history=[
            {
                "ts": "2026-04-17T20:00:00+02:00",
                "voltage": 12.7,
                "soc": 81,
                "state": "<script>alert(1)</script>",
                "error_code": "bad&state",
            }
        ],
        daily_history=[
            {
                "day": "2026-04-18",
                "samples": 4,
                "min_voltage": 12.3,
                "max_voltage": 12.7,
                "avg_voltage": 12.5,
                "avg_soc": 79.0,
                "error_count": 1,
            },
            {
                "day": "2026-04-17",
                "samples": 4,
                "min_voltage": 12.4,
                "max_voltage": 12.8,
                "avg_voltage": 12.6,
                "avg_soc": 80.0,
                "error_count": 0,
            },
        ],
        monthly_history=[],
        yearly_history=[],
        analytics={"windows": []},
        device_summary={
            "name": "BM200 House",
            "soc": 81,
            "voltage": 12.7,
            "temperature": 17.2,
            "rssi": -71,
            "state": "normal",
            "error_code": None,
            "last_seen": "2026-04-18T12:30:00+02:00",
            "connected": True,
            "battery": {
                "brand": "NOCO",
                "model": "NLP5",
                "nominal_voltage": 12,
                "capacity_ah": 5.0,
                "production_year": 2025,
            },
            "installed_in_vehicle": False,
        },
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Historical Chart" in html
    assert "Battery Health" not in html
    assert "Last Seen" in html
    assert "summary-card timestamp-summary" in html
    assert "Battery Status" in html
    assert "Runtime Status" in html
    assert "Reported Status" in html
    assert "<h1>BM200 House</h1>" in html
    assert "NOCO NLP5 12 V 5.0 Ah 2025" in html
    assert "Bench" in html
    assert "What it means:" in html
    assert "Battery condition is stable and ready for normal use." in html
    assert "Latest sample" in html
    assert "Protocol code 2" not in html
    assert "Critical, Low, Normal, Charging, Floating" in html
    assert "status-explainer" in html
    assert "status-scale-active-segment" in html
    assert "status-scale-label" in html
    assert "Battery is full and is being maintained at float charge." in html
    assert 'data-label="Normal"' in html
    assert 'class="status-scale-region tone-ok active"' in html
    assert "status-scale-marker" not in html
    assert '<span class="status-badge ok">Normal</span>' not in html
    assert "State of Charge" in html
    assert "soc-progress-fill" in html
    assert "background:#17c45a" in html
    assert "status-scale-divider" in html
    assert html.index("status-scale-active-segment") < html.index("What it means:")
    assert "is the latest sample this device page is built from." not in html
    assert "Edit device" in html
    assert "/devices/edit?device_id=bm200_house" in html
    assert "History Tables" not in html
    assert 'aria-current="page"' in html
    assert "hero-shell" in html
    assert "chart-tooltip" in html
    assert "chart-overlay" in html
    assert "&quot;series&quot;:&quot;BM200 House&quot;" in html


def test_redirect_message_query_round_trips_special_characters() -> None:
    parsed = urlparse("/?" + urlencode({"message": "Run failed: bad&value"}))

    assert parse_qs(parsed.query)["message"] == ["Run failed: bad&value"]


def test_render_history_html_escapes_device_id_in_title() -> None:
    html = render_history_html(
        device_id='bm200_house"><script>alert(1)</script>',
        configured_devices=[
            {
                "id": "bm200_house",
                "name": "BM200 House",
            }
        ],
        raw_history=[
            {
                "ts": "2026-04-17T20:00:00+02:00",
                "voltage": 12.7,
                "soc": 81,
                "temperature": 17.2,
                "state": "normal",
                "error_code": None,
                "error_detail": None,
            },
            {
                "ts": "2026-04-17T20:05:00+02:00",
                "voltage": 0.0,
                "soc": 0,
                "temperature": None,
                "state": "error",
                "error_code": "timeout",
                "error_detail": "timeout",
            },
        ],
        daily_history=[],
        monthly_history=[],
    )

    assert "<h1>History</h1>" in html
    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt; History" not in html
    assert 'bm200_house"><script>alert(1)</script> History' not in html
    assert "Voltage" in html
    assert "SoC" in html
    assert "<th>Time</th>" in html
    assert "<th>Temp</th>" in html
    assert "<th>Err</th>" in html
    assert "raw-readings-scroll" in html
    assert "raw-readings-table" in html
    assert "1 day" in html
    assert "3 days" in html
    assert "5 days" in html
    assert "7 days" in html
    assert "2 years" in html
    assert "All" in html
    assert 'data-range="raw"' not in html
    assert "Valid samples" in html
    assert "Error count" in html
    assert "Average voltage" in html
    assert "Average SoC" in html
    assert "chart-card-header" in html
    assert "chart-metric-rail" in html
    assert "chart-range-rail" in html
    assert '<a class="secondary-button" href="/">Battery</a>' not in html
    assert "Device Detail" not in html
    assert 'aria-current="page"' in html
    assert "&quot;series&quot;:&quot;bm200_house" in html


def test_render_history_html_shows_device_selector_and_quick_switch_links() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[
            {
                "id": "bm200_house",
                "name": "BM200 House",
            },
            {
                "id": "starter_battery",
                "name": "Starter Battery",
            },
        ],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "History Device" in html
    assert 'action="/history"' not in html
    assert 'name="device_id"' not in html
    assert 'href="/history?device_id=bm200_house"' in html
    assert 'href="/history?device_id=starter_battery"' in html
    assert 'aria-current="page"' in html
    assert "Open History" not in html
    assert "Configured batteries" not in html
    assert "history-device-card" in html


def test_render_history_html_marks_single_selector_grid_layout() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[
            {
                "id": "bm200_house",
                "name": "BM200 House",
            }
        ],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert 'class="device-grid history-device-grid"' in html


def test_render_history_html_uses_compact_history_selector_cards() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[
            {
                "id": "bm200_house",
                "name": "House Battery",
                "icon_key": "lead_acid_battery",
                "battery": {
                    "brand": "NOCO",
                    "model": "NLP5",
                    "family": "lithium",
                    "profile": "lithium",
                },
                "installed_in_vehicle": True,
                "vehicle": {
                    "installed": True,
                    "type": "car",
                    "type_label": "Car",
                },
            }
        ],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "history-device-card" in html
    assert "history-device-badge" in html
    assert "House Battery" in html
    assert "NOCO" in html


def test_render_history_html_prefers_battery_identity_summary() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[
            {
                "id": "bm200_house",
                "name": "House Battery",
                "icon_key": "lead_acid_battery",
                "battery": {
                    "brand": "NOCO",
                    "model": "NLP5",
                    "family": "lithium",
                    "profile": "lithium",
                },
                "installed_in_vehicle": True,
                "vehicle": {
                    "installed": True,
                    "type": "car",
                    "type_label": "Car",
                },
            }
        ],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "NOCO · NLP5" in html or "NOCO NLP5 · lithium" in html
    assert "Bench / stationary battery" not in html
    assert "Installed in a vehicle" not in html


def test_render_history_html_composes_partial_battery_identity_summary() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[
            {
                "id": "bm200_house",
                "name": "House Battery",
                "battery": {
                    "brand": "NOCO",
                    "family": "lithium",
                    "profile": "lithium",
                },
                "installed_in_vehicle": True,
                "vehicle": {
                    "installed": True,
                    "type": "car",
                    "type_label": "Car",
                },
            }
        ],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "NOCO" in html
    assert "Lithium Battery" in html or "lithium" in html
    assert "NOCO · Lithium Battery" in html or "NOCO · lithium" in html
    assert "Installed in a vehicle" not in html
    assert "Bench / stationary battery" not in html


def test_render_history_html_handles_no_configured_devices() -> None:
    html = render_history_html(
        device_id="",
        configured_devices=[],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "No Devices Configured" in html
    assert 'href="/devices/new"' in html
    assert "History Device" not in html


def test_render_devices_html_explains_offline_device_not_found_state() -> None:
    html = render_devices_html(
        snapshot={
            "devices": [
                {
                    "id": "ancell_bm200",
                    "state": "offline",
                    "error_code": "device_not_found",
                    "error_detail": "No BLE advertisement seen during the scan window.",
                    "rssi": None,
                    "last_seen": "2026-04-19T15:20:39+02:00",
                    "connected": False,
                }
            ]
        },
        devices=[
            {
                "id": "ancell_bm200",
                "type": "bm200",
                "name": "Ancell BM200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
            }
        ],
    )

    assert "/devices/edit?device_id=ancell_bm200" in html
    assert 'href="/devices/new"' in html
    assert "Register new BM devices directly from the device registry." not in html
    assert "Serial / MAC: 3C:AB:72:82:86:EA" in html
    assert "Edit device" in html


def test_render_devices_html_uses_device_battery_profile_labels() -> None:
    html = render_devices_html(
        snapshot={"devices": []},
        devices=[
            {
                "id": "ancell_bm200",
                "type": "bm200",
                "name": "Ancell BM200",
                "mac": "3C:AB:72:82:86:EA",
                "enabled": True,
                "battery": {
                    "family": "lead_acid",
                    "profile": "agm",
                },
            }
        ],
    )

    assert "AGM Battery" in html
    assert "/devices/edit?device_id=ancell_bm200" in html
    assert "Add Device" in html
    assert "Configured Devices" in html
    assert "Serial / MAC" in html
    assert "Edit device settings" not in html


def test_render_add_device_html_is_dedicated_creation_surface() -> None:
    html = render_add_device_html(message="Validation failed")

    assert "Add Device" in html
    assert 'action="/devices/add"' in html
    assert 'href="/devices"' in html
    assert "Configured Devices" not in html
    assert "Edit device settings" not in html


def test_add_device_form_includes_vehicle_and_battery_metadata_fields() -> None:
    html = _add_device_form_html()

    assert 'name="installed_in_vehicle"' in html
    assert 'name="vehicle_type"' in html
    assert ">Car<" in html
    assert ">Scooter<" in html
    assert ">Electric Bike<" in html
    assert ">Truck<" in html
    assert ">Bus<" in html
    assert ">ATV / Quad<" in html
    assert 'name="battery_brand"' in html
    assert 'name="battery_model"' in html
    assert 'name="battery_nominal_voltage"' in html
    assert 'name="battery_capacity_ah"' in html
    assert 'name="battery_production_year"' in html
    assert 'name="device_id"' not in html
    assert 'name="icon_key"' not in html
    assert "color-preview-dot" in html


def test_battery_form_script_normalizes_compact_or_colon_mac_inputs() -> None:
    from bm_gateway.web import _battery_form_script

    script = _battery_form_script()

    assert "function normalizeMacLikeValue" in script
    assert "const macInput = form.querySelector(\"[name='device_mac']\");" in script
    assert 'macInput.addEventListener("blur"' in script
    assert 'form.addEventListener("submit"' in script
    assert "raw.length === 12" in script
    assert 'return raw.match(/.{1,2}/g).join(":");' in script


def test_render_edit_device_html_prefills_device_fields() -> None:
    html = render_edit_device_html(
        device={
            "id": "ancell_bm200",
            "type": "bm200",
            "name": "Ancell BM200",
            "mac": "3C:AB:72:82:86:EA",
            "enabled": True,
            "icon_key": "motorcycle_12v",
            "installed_in_vehicle": True,
            "vehicle": {"installed": True, "type": "motorcycle"},
            "battery": {
                "family": "lead_acid",
                "profile": "agm",
                "custom_soc_mode": "intelligent_algorithm",
                "brand": "Yuasa",
                "model": "YTX20L-BS",
                "nominal_voltage": 12,
                "capacity_ah": 18.0,
                "production_year": 2025,
                "custom_voltage_curve": [
                    {"percent": 100, "voltage": 12.9},
                    {"percent": 0, "voltage": 11.9},
                ],
            },
        },
        message="",
    )

    assert "Edit Device" in html
    assert 'action="/devices/update"' in html
    assert 'name="device_id"' in html
    assert 'value="ancell_bm200"' in html
    assert 'name="device_type"' in html
    assert '<a class="secondary-button" href="/devices">Devices</a>' not in html
    assert '<a class="secondary-button" href="/settings">Settings</a>' not in html
    assert "AGM Battery" in html
    assert 'name="installed_in_vehicle"' in html
    assert "checked" in html
    assert 'name="vehicle_type"' in html
    assert "Yuasa" in html
    assert "YTX20L-BS" in html
    assert 'name="battery_nominal_voltage"' in html
    assert ">12 V</option>" in html
    assert 'name="battery_capacity_ah"' in html
    assert 'name="battery_production_year"' in html
    assert 'name="icon_key"' not in html
    assert "Registry ID:" not in html


def test_render_edit_device_html_preserves_original_id_after_validation_error() -> None:
    html = render_edit_device_html(
        device={
            "id": "duplicate_id",
            "type": "bm200",
            "name": "Ancell BM200",
            "mac": "3C:AB:72:82:86:EA",
            "enabled": True,
            "battery": {
                "family": "lead_acid",
                "profile": "regular_lead_acid",
            },
        },
        message="Validation failed: duplicate device id: duplicate_id",
        original_device_id="ancell_bm200",
    )

    assert 'name="old_device_id" value="ancell_bm200"' in html
    assert 'name="device_id" value="duplicate_id"' in html
    assert "Validation failed: duplicate device id: duplicate_id" in html


def _write_edit_device_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "devices.toml").write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "bm200_house"',
                'type = "bm200"',
                'name = "BM200 House"',
                'mac = "AA:BB:CC:DD:EE:01"',
                'color_key = "green"',
                "",
                "[[devices]]",
                'id = "spare_nlp20"',
                'type = "bm200"',
                'name = "Spare NLP20"',
                'mac = "AA:BB:CC:DD:EE:02"',
                'color_key = "blue"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _persist_edit_device_snapshot(database_path: Path, *, device_id: str) -> None:
    persist_snapshot(
        database_path,
        GatewaySnapshot(
            generated_at="2024-01-01T00:00:00+00:00",
            gateway_name="BMGateway",
            active_adapter="hci0",
            mqtt_enabled=True,
            mqtt_connected=False,
            devices_total=1,
            devices_online=1,
            poll_interval_seconds=15,
            devices=[
                DeviceReading(
                    id=device_id,
                    type="bm200",
                    name="BM200 House",
                    mac="AA:BB:CC:DD:EE:01",
                    enabled=True,
                    connected=True,
                    voltage=12.73,
                    soc=58,
                    temperature=None,
                    rssi=None,
                    state="normal",
                    error_code=None,
                    error_detail=None,
                    last_seen="2024-01-01T00:00:00+00:00",
                    adapter="hci0",
                    driver="bm200",
                )
            ],
        ),
    )


def test_update_device_from_form_renames_device_id_and_history(tmp_path: Path) -> None:
    config_path = _write_edit_device_config(tmp_path)
    database_path = tmp_path / "gateway.db"
    _persist_edit_device_snapshot(database_path, device_id="bm200_house")

    errors = update_device_from_form(
        config_path=config_path,
        database_path=database_path,
        device_id="bm200_house",
        new_device_id="starter_battery",
        device_type="bm200",
        device_name="Starter Battery",
        device_mac="AA:BB:CC:DD:EE:01",
        battery_family="lead_acid",
        battery_profile="regular_lead_acid",
        custom_soc_mode="intelligent_algorithm",
        custom_voltage_curve=(),
        color_key="green",
        installed_in_vehicle=False,
        vehicle_type="",
        battery_brand="",
        battery_model="",
        battery_nominal_voltage=None,
        battery_capacity_ah=None,
        battery_production_year=None,
    )

    assert errors == []
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert [device.id for device in devices] == ["starter_battery", "spare_nlp20"]
    assert fetch_recent_history(database_path, device_id="bm200_house", limit=10) == []
    assert fetch_recent_history(database_path, device_id="starter_battery", limit=10)


def test_update_device_from_form_skips_history_rewrite_for_non_history_fields(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = _write_edit_device_config(tmp_path)
    database_path = tmp_path / "gateway.db"
    rewrite_calls: list[dict[str, object]] = []

    def _rename_history_device_id(**kwargs: object) -> None:
        rewrite_calls.append(kwargs)

    monkeypatch.setattr(
        "bm_gateway.web_actions.rename_history_device_id",
        _rename_history_device_id,
    )

    errors = update_device_from_form(
        config_path=config_path,
        database_path=database_path,
        device_id="bm200_house",
        new_device_id="bm200_house",
        device_type="bm200",
        device_name="BM200 House",
        device_mac="AA:BB:CC:DD:EE:01",
        battery_family="lead_acid",
        battery_profile="regular_lead_acid",
        custom_soc_mode="intelligent_algorithm",
        custom_voltage_curve=(),
        color_key="orange",
        installed_in_vehicle=True,
        vehicle_type="car",
        battery_brand="NOCO",
        battery_model="NLP20",
        battery_nominal_voltage=12,
        battery_capacity_ah=7.0,
        battery_production_year=2025,
    )

    assert errors == []
    assert rewrite_calls == []
    assert not database_path.exists()
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert devices[0].color_key == "orange"
    assert devices[0].vehicle_type == "car"


def test_update_device_from_form_rejects_duplicate_device_id(tmp_path: Path) -> None:
    config_path = _write_edit_device_config(tmp_path)

    errors = update_device_from_form(
        config_path=config_path,
        device_id="bm200_house",
        new_device_id="spare_nlp20",
        device_type="bm200",
        device_name="Starter Battery",
        device_mac="AA:BB:CC:DD:EE:01",
        battery_family="lead_acid",
        battery_profile="regular_lead_acid",
        custom_soc_mode="intelligent_algorithm",
        custom_voltage_curve=(),
        color_key="green",
        installed_in_vehicle=False,
        vehicle_type="",
        battery_brand="",
        battery_model="",
        battery_nominal_voltage=None,
        battery_capacity_ah=None,
        battery_production_year=None,
    )

    assert errors == ["duplicate device id: spare_nlp20"]
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert [device.id for device in devices] == ["bm200_house", "spare_nlp20"]


def test_devices_update_redirect_uses_normalized_renamed_device_id(tmp_path: Path) -> None:
    config_path = _write_edit_device_config(tmp_path)
    from bm_gateway.web import serve_management

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        host, port = handle.getsockname()

    server_thread = threading.Thread(
        target=serve_management,
        kwargs={
            "host": host,
            "port": port,
            "config_path": config_path,
            "state_dir": tmp_path,
        },
        daemon=True,
    )
    server_thread.start()

    request = urllib.request.Request(
        f"http://{host}:{port}/devices/update",
        data=urllib.parse.urlencode(
            {
                "old_device_id": "bm200_house",
                "device_id": " starter_battery ",
                "device_type": "bm200",
                "device_name": "Starter Battery",
                "device_mac": "AA:BB:CC:DD:EE:01",
                "battery_family": "lead_acid",
                "battery_profile": "regular_lead_acid",
                "custom_soc_mode": "intelligent_algorithm",
                "color_key": "green",
            }
        ).encode("utf-8"),
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5.0) as response:
        params = parse_qs(urlparse(response.url).query)
        assert response.status == 200
        assert urlparse(response.url).path == "/devices/edit"
        assert params["device_id"] == ["starter_battery"]
        assert params["message"] == ["Device saved"]


def test_update_device_from_form_rejects_history_collision(tmp_path: Path) -> None:
    config_path = _write_edit_device_config(tmp_path)
    database_path = tmp_path / "gateway.db"
    _persist_edit_device_snapshot(database_path, device_id="spare_history")

    errors = update_device_from_form(
        config_path=config_path,
        database_path=database_path,
        device_id="bm200_house",
        new_device_id="spare_history",
        device_type="bm200",
        device_name="Starter Battery",
        device_mac="AA:BB:CC:DD:EE:01",
        battery_family="lead_acid",
        battery_profile="regular_lead_acid",
        custom_soc_mode="intelligent_algorithm",
        custom_voltage_curve=(),
        color_key="green",
        installed_in_vehicle=False,
        vehicle_type="",
        battery_brand="",
        battery_model="",
        battery_nominal_voltage=None,
        battery_capacity_ah=None,
        battery_production_year=None,
    )

    assert errors == ["device id spare_history already has stored history; choose a different id"]
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert [device.id for device in devices] == ["bm200_house", "spare_nlp20"]


def test_bottom_nav_renders_generated_icons() -> None:
    html = render_history_html(
        device_id="bm200_house",
        configured_devices=[],
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "nav-icon" in html
    assert "nav-label" in html
    assert ">Home<" in html
