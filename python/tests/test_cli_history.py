from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from bm_gateway import cli
from bm_gateway.archive_sync import plan_archive_backfill, sync_bm200_device_archive
from bm_gateway.config import load_config
from bm_gateway.device_registry import load_device_registry
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.runtime import database_file_path
from bm_gateway.state_store import persist_snapshot


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


def test_history_yearly_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
            "yearly",
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
    assert "year" in payload[0]


def test_history_compare_emits_degradation_report(
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
            "compare",
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
    assert payload["device_id"] == "bm200_house"
    assert "windows" in payload


def test_history_sync_device_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"

    def fake_sync(*, config: object, device: object, database_path: Path) -> dict[str, object]:
        assert database_path == state_dir / "runtime" / "gateway.db"
        return {
            "device_id": "bm200_house",
            "fetched": 12,
            "inserted": 10,
            "adapter": "hci0",
            "profile": "legacy_bm2_history",
        }

    from bm_gateway import cli as cli_module

    cli_module_any = cast(Any, cli_module)
    original = cli_module_any.sync_bm200_device_archive
    cli_module_any.sync_bm200_device_archive = fake_sync
    try:
        result = cli.main(
            [
                "--config",
                str(config_path),
                "history",
                "sync-device",
                "--device-id",
                "bm200_house",
                "--state-dir",
                str(state_dir),
                "--json",
            ]
        )
    finally:
        cli_module_any.sync_bm200_device_archive = original

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["synced"] is True
    assert payload["inserted"] == 10


def test_plan_archive_backfill_flags_connected_devices_with_real_history_gap(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
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
            poll_interval_seconds=600,
            devices=[
                DeviceReading(
                    id="bm200_house",
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

    snapshot = GatewaySnapshot(
        generated_at="2024-01-01T03:00:00+00:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=True,
        mqtt_connected=False,
        devices_total=1,
        devices_online=1,
        poll_interval_seconds=600,
        devices=[
            DeviceReading(
                id="bm200_house",
                type="bm200",
                name="BM200 House",
                mac="AA:BB:CC:DD:EE:01",
                enabled=True,
                connected=True,
                voltage=12.81,
                soc=61,
                temperature=None,
                rssi=-60,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2024-01-01T03:00:00+00:00",
                adapter="hci0",
                driver="bm200",
            )
        ],
    )

    candidates = plan_archive_backfill(
        database_path=database_path,
        snapshot=snapshot,
        poll_interval_seconds=600,
    )

    assert candidates == {"bm200_house"}


def test_sync_bm200_device_archive_uses_extended_history_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    database_path = tmp_path / "gateway.db"
    captured: dict[str, float] = {}

    async def fake_read_history(
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: object = None,
        transport: object = None,
    ) -> list[object]:
        _ = (address, adapter, scan_timeout_seconds, reference_ts, transport)
        captured["timeout_seconds"] = timeout_seconds
        return []

    monkeypatch.setattr("bm_gateway.archive_sync.read_bm200_history", fake_read_history)

    payload = sync_bm200_device_archive(
        config=config,
        device=devices[0],
        database_path=database_path,
    )

    assert payload["fetched"] == 0
    assert captured["timeout_seconds"] == 180.0


def test_run_cycle_triggers_archive_sync_after_gap(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(config, gateway=replace(config.gateway, reader_mode="live"))
    devices = load_device_registry(config.device_registry_path)
    state_dir = tmp_path / "state"

    persist_snapshot(
        database_file_path(config, state_dir=state_dir),
        GatewaySnapshot(
            generated_at="2024-01-01T00:00:00+00:00",
            gateway_name=config.gateway.name,
            active_adapter="hci0",
            mqtt_enabled=True,
            mqtt_connected=False,
            devices_total=1,
            devices_online=1,
            poll_interval_seconds=config.gateway.poll_interval_seconds,
            devices=[
                DeviceReading(
                    id="bm200_house",
                    type="bm200",
                    name="BM200 House",
                    mac="AA:BB:CC:DD:EE:01",
                    enabled=True,
                    connected=True,
                    voltage=12.73,
                    soc=58,
                    temperature=None,
                    rssi=-60,
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

    second_snapshot = GatewaySnapshot(
        generated_at="2024-01-01T03:00:00+00:00",
        gateway_name=config.gateway.name,
        active_adapter="hci0",
        mqtt_enabled=True,
        mqtt_connected=False,
        devices_total=1,
        devices_online=1,
        poll_interval_seconds=config.gateway.poll_interval_seconds,
        devices=[
            DeviceReading(
                id="bm200_house",
                type="bm200",
                name="BM200 House",
                mac="AA:BB:CC:DD:EE:01",
                enabled=True,
                connected=True,
                voltage=12.81,
                soc=61,
                temperature=None,
                rssi=-55,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2024-01-01T03:00:00+00:00",
                adapter="hci0",
                driver="bm200",
            )
        ],
    )

    from bm_gateway import cli as cli_module

    calls: list[set[str]] = []

    class StubPublisher:
        def publish_runtime(
            self,
            *,
            config: object,
            devices: object,
            snapshot: object,
            publish_discovery: bool,
        ) -> bool:
            _ = (config, devices, snapshot, publish_discovery)
            return False

    def fake_build_snapshot(_config: object, _devices: object) -> GatewaySnapshot:
        return second_snapshot

    def fake_sync(
        *,
        config: object,
        devices: object,
        database_path: Path,
        device_ids: set[str],
    ) -> list[dict[str, object]]:
        assert database_path == state_dir / "runtime" / "gateway.db"
        calls.append(set(device_ids))
        return []

    cli_module_any = cast(Any, cli_module)
    original_build_snapshot = cli_module_any.build_snapshot
    original_sync_candidates = cli_module_any.sync_archive_backfill_candidates
    cli_module_any.build_snapshot = fake_build_snapshot
    cli_module_any.sync_archive_backfill_candidates = fake_sync
    try:
        cli._run_cycle(
            config=config,
            devices=devices,
            publisher=StubPublisher(),
            publish_discovery=False,
            state_dir=state_dir,
        )
    finally:
        cli_module_any.build_snapshot = original_build_snapshot
        cli_module_any.sync_archive_backfill_candidates = original_sync_candidates

    assert calls == [{"bm200_house"}]


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
