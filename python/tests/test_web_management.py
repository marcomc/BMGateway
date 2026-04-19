from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from bm_gateway import __version__
from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry, normalize_mac_address, validate_devices
from bm_gateway.web import (
    _chart_points,
    add_device_from_form,
    build_run_once_command,
    render_device_html,
    render_devices_html,
    render_history_html,
    render_management_html,
    update_config_from_text,
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
    )

    assert errors == []
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert config.gateway.reader_mode == "live"
    assert devices[0].mac == "A1:B2:C3:D4:E5:F6"


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
    )

    assert errors == []
    devices = load_device_registry(tmp_path / "devices.toml")
    assert devices[0].id == 'bm200_"quoted"'
    assert devices[0].name == 'Ancell "Quoted" \\ Unit'


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
    html = render_management_html(
        snapshot={"generated_at": "2026-04-17T20:00:00+02:00", "devices": []},
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

    assert "Configured Devices" in html
    assert "Home Assistant Contract" in html
    assert "Storage Summary" in html
    assert "/api/ha/contract" in html
    assert "Prune History Using Retention Settings" in html
    assert "Add Device and Enable Live Polling" in html
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert 'aria-live="polite"' in html
    assert 'for="device-id-input"' in html
    assert 'id="device-id-input"' in html
    assert 'autocomplete="off"' in html
    assert 'spellcheck="false"' in html
    assert 'aria-describedby="device-mac-help"' in html
    assert 'aria-label="Primary"' in html
    assert "control-plane" in html
    assert "api-chip" in html
    assert "config-grid" in html
    assert __version__ in html
    assert "build" in html


def test_render_management_html_includes_analytics_and_device_links() -> None:
    html = render_management_html(
        snapshot={
            "generated_at": "2026-04-17T20:00:00+02:00",
            "devices": [{"id": "bm200_house", "name": "BM200 House"}],
        },
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
            }
        ],
        config_text='[gateway]\nname = "BMGateway"\n',
        devices_text='[[devices]]\nid = "bm200_house"\n',
        contract={"gateway": {}, "devices": []},
        message="ok",
    )

    assert "/device?device_id=bm200_house" in html
    assert "/api/analytics?device_id=" in html
    assert "Gateway Overview" in html
    assert "Device Dashboard" in html
    assert "Operational Surfaces" in html
    assert "Recover Bluetooth Adapter" in html


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
    assert "Last Seen" in html
    assert "Runtime Status" in html
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
