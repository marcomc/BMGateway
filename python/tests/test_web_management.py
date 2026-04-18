from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry, normalize_mac_address, validate_devices
from bm_gateway.web import (
    add_device_from_form,
    build_run_once_command,
    render_device_html,
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
        device_mac="3CAB728286EA",
    )

    assert errors == []
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    assert config.gateway.reader_mode == "live"
    assert devices[0].mac == "3C:AB:72:82:86:EA"


def test_compact_mac_address_is_normalized() -> None:
    assert normalize_mac_address("3CAB728286EA") == "3C:AB:72:82:86:EA"


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
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Historical Chart" in html


def test_redirect_message_query_round_trips_special_characters() -> None:
    parsed = urlparse("/?" + urlencode({"message": "Run failed: bad&value"}))

    assert parse_qs(parsed.query)["message"] == ["Run failed: bad&value"]


def test_render_history_html_escapes_device_id_in_title() -> None:
    html = render_history_html(
        device_id='bm200_house"><script>alert(1)</script>',
        raw_history=[],
        daily_history=[],
        monthly_history=[],
    )

    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt; History" in html
    assert 'bm200_house"><script>alert(1)</script> History' not in html
