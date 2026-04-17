from __future__ import annotations

from pathlib import Path

from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry
from bm_gateway.web import build_run_once_command, update_config_from_text


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

    command = build_run_once_command(config_path)

    assert command[1:4] == ["-m", "bm_gateway", "--config"]
    assert command[-2:] == ["run", "--once"]
