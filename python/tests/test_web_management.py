from __future__ import annotations

from pathlib import Path

from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry
from bm_gateway.web import (
    build_run_once_command,
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
