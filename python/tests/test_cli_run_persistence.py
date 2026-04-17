from __future__ import annotations

import sqlite3
from pathlib import Path

from bm_gateway import cli


def _write_example_files(tmp_path: Path) -> Path:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "bm200_house"',
                'type = "bm200"',
                'name = "BM200 House"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "gateway.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 15",
                'device_registry = "devices.toml"',
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
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return config_path


def test_run_once_persists_sqlite_database(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
            "--dry-run",
            "--state-dir",
            str(state_dir),
        ]
    )

    assert result == 0

    connection = sqlite3.connect(state_dir / "runtime" / "gateway.db")
    try:
        gateway_count = connection.execute("SELECT COUNT(*) FROM gateway_snapshots").fetchone()
        device_count = connection.execute("SELECT COUNT(*) FROM device_readings").fetchone()
    finally:
        connection.close()

    assert gateway_count == (1,)
    assert device_count == (1,)
