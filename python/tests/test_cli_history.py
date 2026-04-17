from __future__ import annotations

import json
from pathlib import Path

import pytest
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
                "",
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


def test_history_daily_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"
    cli.main(
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
    capsys.readouterr()

    result = cli.main(
        [
            "--config",
            str(config_path),
            "history",
            "daily",
            "--device-id",
            "bm200_house",
            "--state-dir",
            str(state_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload[0]["device_id"] == "bm200_house"
    assert payload[0]["samples"] == 1


def test_history_monthly_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"
    cli.main(
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
    capsys.readouterr()

    result = cli.main(
        [
            "--config",
            str(config_path),
            "history",
            "monthly",
            "--device-id",
            "bm200_house",
            "--state-dir",
            str(state_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload[0]["device_id"] == "bm200_house"


def test_history_stats_emits_storage_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"
    cli.main(
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
    capsys.readouterr()

    result = cli.main(
        [
            "--config",
            str(config_path),
            "history",
            "stats",
            "--state-dir",
            str(state_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["counts"]["gateway_snapshots"] == 1
    assert payload["devices"][0]["device_id"] == "bm200_house"


def test_history_prune_uses_configured_retention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"
    cli.main(
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
    capsys.readouterr()

    result = cli.main(
        [
            "--config",
            str(config_path),
            "history",
            "prune",
            "--state-dir",
            str(state_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["before"]["device_readings"] == 1
    assert payload["after"]["device_readings"] == 1
