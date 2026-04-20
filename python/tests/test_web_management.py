from __future__ import annotations

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
        device_id="bm200_ancell",
        device_type="bm200",
        device_name="Ancell BM200",
        device_mac="A1B2C3D4E5F6",
        icon_key="motorcycle_12v",
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
    assert devices[0].mac == "A1:B2:C3:D4:E5:F6"
    assert devices[0].icon_key == "motorcycle_12v"
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
        device_id='bm200_"quoted"',
        device_type="bm200",
        device_name='Ancell "Quoted" \\ Unit',
        device_mac="A1B2C3D4E5F6",
        icon_key="battery_monitor",
    )

    assert errors == []
    devices = load_device_registry(tmp_path / "devices.toml")
    assert devices[0].id == 'bm200_"quoted"'
    assert devices[0].name == 'Ancell "Quoted" \\ Unit'
    assert devices[0].icon_key == "battery_monitor"


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
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.port == 9091
    assert config.web.show_chart_markers is True


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
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.enabled is False
    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8088


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
    )

    assert errors == []
    config = load_config(config_path)
    assert config.web.port == 8088
    assert config.web.show_chart_markers is True


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
    assert 'name="bluetooth_adapter"' in html
    assert 'name="scan_timeout_seconds"' in html
    assert 'name="connect_timeout_seconds"' in html
    assert "Configuration Files" not in html
    assert "Home Assistant Contract" not in html
    assert "Storage Summary" not in html
    assert "Run One Collection Cycle" not in html
    assert "Recover Bluetooth Adapter" not in html
    assert 'href="/settings"' in html


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
                    "icon_key": "motorcycle_12v",
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
                "icon_key": "motorcycle_12v",
            }
        ],
        chart_points=[],
        legend=[],
    )

    assert "device-icon-frame" in html
    assert 'data-icon-key="motorcycle_12v"' in html
    assert "device-icon-frame hero-device-icon" in html
    assert "hero-soc hero-soc-battery" in html
    assert "battery-card-status" in html
    assert "Battery OK" in html
    assert "Open device" in html


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
    assert "battery-card-status charging" in html
    assert 'aria-label="Charging"' in html


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
    assert "Last Seen" in html
    assert "Runtime Status" in html
    assert "Reported Status" in html
    assert "This monitor reports the battery state directly over BM200/BM6." in html
    assert "Protocol code 2" in html
    assert "Critical" in html
    assert "Low" in html
    assert "Normal" in html
    assert "Charging" in html
    assert "Floating" in html
    assert "status-explainer" in html
    assert "status-scale-fill" in html
    assert '<a class="secondary-button" href="/">Battery</a>' in html
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

    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt; History" in html
    assert 'bm200_house"><script>alert(1)</script> History' not in html
    assert "Voltage" in html
    assert "SoC" in html
    assert "Temperature" in html
    assert "1 day" in html
    assert "7 days" in html
    assert "2 years" in html
    assert "Valid samples" in html
    assert "Error count" in html
    assert "Average voltage" in html
    assert "Average SoC" in html
    assert "history-controls" in html
    assert '<a class="secondary-button" href="/">Battery</a>' in html
    assert 'aria-current="page"' in html
    assert "&quot;series&quot;:&quot;bm200_house" in html


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
    assert "Not visible" in html
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
    assert ">Truck<" in html
    assert ">Bus<" in html
    assert ">ATV / Quad<" in html
    assert 'name="battery_brand"' in html
    assert 'name="battery_model"' in html
    assert 'name="battery_capacity_ah"' in html
    assert 'name="battery_production_year"' in html


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
    assert "AGM Battery" in html
    assert 'name="installed_in_vehicle"' in html
    assert "checked" in html
    assert 'value="motorcycle_12v"' in html
    assert 'name="vehicle_type"' in html
    assert "Yuasa" in html
    assert "YTX20L-BS" in html
    assert 'name="battery_capacity_ah"' in html
    assert 'name="battery_production_year"' in html


def test_bottom_nav_renders_generated_icons() -> None:
    html = render_history_html(
        device_id="bm200_house",
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "nav-icon" in html
    assert "nav-label" in html
