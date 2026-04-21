from __future__ import annotations

import socket
import threading
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from bm_gateway import __version__
from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry, normalize_mac_address, validate_devices
from bm_gateway.web import (
    _add_device_form_html,
    _chart_points,
    _discover_bluetooth_adapters,
    add_device_from_form,
    build_run_once_command,
    render_add_device_html,
    render_device_html,
    render_devices_html,
    render_edit_device_html,
    render_history_html,
    render_management_html,
    render_settings_html,
    update_bluetooth_preferences,
    update_config_from_text,
    update_device_icon,
    update_gateway_preferences,
    update_web_preferences,
)
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


def test_chart_script_renders_multi_series_tooltip_rows() -> None:
    script = chart_script("history-chart")

    assert "function tooltipEntriesForX(chart, targetX)" in script
    assert "chart.seriesBuckets.map((series) => {" in script
    assert 'class="tooltip-series-row"' in script
    assert 'class="tooltip-series-swatch"' in script
    assert 'class="tooltip-series-value"' in script
    assert "const rows = entries.map((entry) => (" in script


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
        mqtt_enabled=False,
        home_assistant_enabled=False,
        raw_retention_days=90,
        daily_retention_days=30,
    )

    assert errors == []
    config = load_config(config_path)
    assert config.gateway.reader_mode == "live"
    assert config.gateway.poll_interval_seconds == 600
    assert config.mqtt.enabled is False
    assert config.home_assistant.enabled is False
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
        mqtt_enabled=True,
        home_assistant_enabled=True,
        raw_retention_days=0,
        daily_retention_days=-1,
    )

    assert "gateway.poll_interval_seconds must be greater than zero" in errors
    assert "retention.raw_retention_days must be greater than zero" in errors
    assert "retention.daily_retention_days must be zero or greater" in errors


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


def test_compact_mac_address_is_normalized() -> None:
    assert normalize_mac_address("A1B2C3D4E5F6") == "A1:B2:C3:D4:E5:F6"


def test_empty_device_registry_is_allowed() -> None:
    assert validate_devices([]) == []


def test_build_run_once_command_targets_module_entrypoint(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"

    command = build_run_once_command(config_path, state_dir=state_dir)

    assert command[1:4] == ["-m", "bm_gateway", "--config"]
    assert command[-4:] == ["run", "--once", "--state-dir", str(state_dir)]


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
    assert __version__ in html
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
        snapshot={"devices": []},
        devices=[],
    )

    assert "Gateway Settings" in html
    assert "Web Service" in html
    assert "Display Settings" in html
    assert "Visible overview cards" in html
    assert "Edit settings" in html
    assert 'href="/settings?edit=1"' in html
    assert "Save display settings" not in html
    assert "Save web service settings" not in html
    assert "Run One Collection Cycle" in html
    assert "Home Assistant Contract" in html
    assert "Storage Summary" in html
    assert "Configuration Files" in html
    assert 'id="config-toml-readonly"' in html
    assert 'id="devices-toml-readonly"' in html
    assert "readonly" in html
    assert html.index('section-title">Gateway Overview') < html.index('section-title">Actions')
    assert html.index('section-title">Actions') < html.index('section-title">Gateway Settings')
    assert html.index('section-title">Gateway Settings') < html.index(
        'section-title">Home Assistant Contract'
    )
    assert html.index('section-title">Home Assistant Contract') < html.index(
        'section-title">Storage Summary'
    )


def test_render_settings_html_summary_shows_appearance() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, web=replace(config.web, appearance="system"))
    html = render_settings_html(config=config, snapshot={}, devices=[], edit_mode=False)

    assert "Appearance" in html
    assert "System" in html


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
    assert "Web Service" in html
    assert "Display Settings" in html
    assert "Save gateway settings" in html
    assert "Save web service settings" in html
    assert "Save display settings" in html
    assert 'name="gateway_name"' in html
    assert 'name="timezone"' in html
    assert 'name="web_host"' in html
    assert 'name="web_enabled"' in html
    assert 'name="visible_device_limit"' in html
    assert 'name="bluetooth_adapter"' in html
    assert 'name="scan_timeout_seconds"' in html
    assert 'name="connect_timeout_seconds"' in html
    assert "Configuration Files" not in html
    assert "Home Assistant Contract" not in html
    assert "Storage Summary" not in html
    assert "Run One Collection Cycle" not in html
    assert "Recover Bluetooth Adapter" not in html
    assert 'href="/settings"' in html


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


def test_render_battery_html_renders_device_icon() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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
    assert "Device Details" in html
    assert "Open device" not in html
    assert "All" in html
    assert "battery-overview-scroller" in html
    assert 'aria-label="Show previous battery cards"' not in html
    assert 'aria-label="Show next battery cards"' not in html
    assert "battery-overview-page" in html
    assert "--overview-columns:" in html
    assert "Add Device" in html
    assert (
        '<div class="hero-actions"><a class="secondary-button" href="/settings">Settings</a>'
        not in html
    )


def test_render_battery_html_threads_appearance_to_document_root() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
        appearance="dark",
    )

    assert 'data-theme-preference="dark"' in html


def test_render_battery_html_defaults_chart_to_seven_days_and_soc() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
        snapshot={"devices": []},
        devices=[],
        chart_points=[],
        legend=[],
    )

    assert 'data-range="7" data-range-label="7 days" class="active"' in html
    assert 'data-metric="soc" class="active"' in html


def test_render_battery_html_uses_shared_icon_badge_markup() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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


def test_render_battery_html_prefers_registry_name_over_stale_snapshot_name() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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


def test_render_battery_html_places_badge_outside_gauge_and_identity_below() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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

    top_index = html.index("<div class='battery-card-top'>")
    hero_index = html.index("<div class='battery-tile-hero'>")
    footer_index = html.index("<div class='footer-row'>")

    assert top_index < hero_index < footer_index
    assert "device-badge-stack" in html[top_index:hero_index]
    assert "battery-card-gauge-value" in html[hero_index:footer_index]
    assert "battery-card-status-inline" in html[hero_index:footer_index]
    assert "battery-card-gauge-label" in html[hero_index:footer_index]
    assert "meta-name" in html[top_index:hero_index]
    assert "meta-context" in html[top_index:hero_index]
    assert "battery-card-reading" in html[top_index:hero_index]


def test_base_css_stacks_battery_badges_next_to_identity_copy() -> None:
    css = base_css()

    assert ".battery-card-top {" in css
    assert ".device-badge-stack {" in css
    assert ".device-icon-frame {" in css
    assert "aspect-ratio: 1 / 1;" in css
    assert "min-width: 72px;" in css
    assert "min-height: 72px;" in css
    assert ".battery-tile-hero {" in css
    assert ".battery-card-badge {" in css
    assert "position: static;" in css
    assert "place-items: center;" in css
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
    assert ".battery-overview-page.is-single-page.page-two-cards {" in css
    assert "justify-content: flex-start;" in css
    assert "background: var(--bg-surface);" in css
    assert ".banner-strip {" in css
    assert "@media (max-width: 640px)" in css
    assert "width: 132px;" in css
    assert "width: 38px;" in css
    assert "height: 38px;" in css
    assert "flex: 0 0 38px;" in css
    assert "inline-size: 38px;" in css
    assert "block-size: 38px;" in css
    assert "max-inline-size: 38px;" in css
    assert "overflow: hidden;" in css
    assert ".device-icon-frame.history-device-badge {" in css
    assert "inline-size: 40px;" in css
    assert "max-inline-size: 40px;" in css
    assert "width: 42px;" in css
    assert "height: 42px;" in css
    assert "width: 34px;" in css
    assert "height: 34px;" in css
    assert "width: 30px;" in css
    assert "height: 30px;" in css
    assert "font-size: clamp(1.8rem, 4.4vw, 2.55rem);" in css
    assert "font-size: 0.72rem;" in css
    assert "font-size: 0.74rem;" in css
    assert "padding: 0.75rem 0.8rem 0.75rem 0.95rem;" in css
    assert ".battery-overview-page.is-single-page.page-two-cards," in css


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

    assert 'class="device-grid devices-grid single-card-grid"' in html


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


def test_render_battery_html_pages_cards_by_visible_device_limit() -> None:
    from bm_gateway.web import render_battery_html

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
    html = render_battery_html(
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

    assert html.count('class="battery-overview-page page-multi-cards"') == 2
    assert 'class="battery-overview-page page-one-card"' not in html
    assert "--overview-columns: 2;" in html
    assert "--overview-rows: 2;" in html
    assert "Battery 7" in html
    assert 'data-direction="previous"' in html
    assert 'data-direction="next"' in html
    assert "battery-overview-add-tile" not in html
    assert "icon-button" in html


def test_render_battery_html_marks_single_page_card_count() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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

    assert "battery-overview-page is-single-page page-one-card" in html


def test_render_battery_html_uses_four_by_two_layout_for_eight_visible_cards() -> None:
    from bm_gateway.web import render_battery_html

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

    html = render_battery_html(
        snapshot={"devices": snapshot_devices},
        devices=registry_devices,
        chart_points=[],
        legend=[],
        visible_device_limit=8,
    )

    assert 'class="battery-overview-page is-single-page page-multi-cards"' in html
    assert "--overview-columns: 4;" in html
    assert "--overview-rows: 2;" in html
    assert 'class="battery-overview-controls"' not in html


def test_render_battery_html_keeps_registry_only_devices_visible() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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


def test_render_battery_html_shows_charging_status_with_explicit_icon() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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


def test_render_battery_html_shows_connection_failure_as_red_warning() -> None:
    from bm_gateway.web import render_battery_html

    html = render_battery_html(
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
        },
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Historical Chart" in html
    assert "Battery Health" in html
    assert "Signal Quality" in html
    assert "Good" in html
    assert "58%" in html
    assert "RSSI -71 dBm" in html
    assert html.count("RSSI -71 dBm") == 1
    assert "Last Seen" in html
    assert "summary-card timestamp-summary" in html
    assert "Battery Status" in html
    assert "Runtime Status" in html
    assert "Reported Status" in html
    assert "What it means:" in html
    assert "This state comes directly from the BM200/BM6 monitor protocol." in html
    assert "BMGateway does not derive it from voltage, SoC, temperature" in html
    assert "Latest sample" in html
    assert "Protocol code 2" in html
    assert "Critical, Low, Normal, Charging, Floating" in html
    assert "status-explainer" in html
    assert "status-scale-fill" in html
    assert "status-scale-divider" in html
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
    assert "Temperature" in html
    assert "1 day" in html
    assert "7 days" in html
    assert "2 years" in html
    assert "All" in html
    assert "Valid samples" in html
    assert "Error count" in html
    assert "Average voltage" in html
    assert "Average SoC" in html
    assert "history-controls" in html
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
    assert "Switch the history surface between configured batteries" in html
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
    assert "Add a battery monitor before using the history dashboard." in html
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

    assert "Offline" in html
    assert "No BLE advertisement seen during the latest scan window." in html
    assert "No recent sample" in html
    assert "The adapter did not see this monitor in the latest scan." in html
    assert "/devices/edit?device_id=ancell_bm200" in html
    assert 'href="/devices/new"' in html
    assert "Register new BM devices directly from the device registry." not in html


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
    assert "Lead-Acid Battery" in html
    assert "/devices/edit?device_id=ancell_bm200" in html
    assert "Add Device" in html
    assert "Configured Devices" in html
    assert "Serial / MAC" in html


def test_render_add_device_html_is_dedicated_creation_surface() -> None:
    html = render_add_device_html(message="Validation failed")

    assert "Add Device" in html
    assert "Register a new BM device without the configured-device list getting in the way." in html
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
    assert 'name="battery_capacity_ah"' in html
    assert 'name="battery_production_year"' in html
    assert 'name="icon_key"' not in html
    assert "Registry ID:" not in html


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
