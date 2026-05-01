from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, cast

import pytest
from bm_gateway import cli
from bm_gateway.archive_sync import (
    BM300_ARCHIVE_PROFILE,
    plan_archive_backfill,
    plan_archive_backfill_details,
    sync_archive_backfill_candidates,
    sync_bm200_device_archive,
    sync_bm300_device_archive,
)
from bm_gateway.bluetooth_recovery import BluetoothRecoveryRequiredError
from bm_gateway.config import load_config
from bm_gateway.device_registry import Device, load_device_registry
from bm_gateway.drivers.bm200 import BM200HistoryReading
from bm_gateway.drivers.bm300 import BM300HistoryReading
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.runtime import database_file_path
from bm_gateway.state_store import fetch_archive_history, import_archive_history, persist_snapshot


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

    def fake_sync(
        *,
        config: object,
        device: object,
        database_path: Path,
        page_count: int,
    ) -> dict[str, object]:
        assert database_path == state_dir / "runtime" / "gateway.db"
        assert page_count == 5
        return {
            "device_id": "bm200_house",
            "fetched": 12,
            "inserted": 10,
            "adapter": "hci0",
            "profile": "bm6_d15505_b7_v1",
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
                "--page-count",
                "5",
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


def test_history_sync_device_routes_bm300pro_to_bm7_archive_sync(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_example_files(tmp_path)
    (tmp_path / "devices.toml").write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "bm300_doc"',
                'type = "bm300pro"',
                'name = "BM300 DOC"',
                'mac = "AA:BB:CC:DD:EE:30"',
                "enabled = true",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"

    def fake_sync(
        *,
        config: object,
        device: object,
        database_path: Path,
        page_count: int,
    ) -> dict[str, object]:
        _ = config
        assert isinstance(device, Device)
        assert device.id == "bm300_doc"
        assert database_path == state_dir / "runtime" / "gateway.db"
        assert page_count == 2
        return {
            "device_id": "bm300_doc",
            "fetched": 32,
            "inserted": 30,
            "adapter": "hci0",
            "profile": BM300_ARCHIVE_PROFILE,
        }

    monkeypatch.setattr(cli, "sync_bm300_device_archive", fake_sync, raising=False)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "history",
            "sync-device",
            "--device-id",
            "bm300_doc",
            "--state-dir",
            str(state_dir),
            "--page-count",
            "2",
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["synced"] is True
    assert payload["profile"] == BM300_ARCHIVE_PROFILE
    assert payload["inserted"] == 30


def test_plan_archive_backfill_flags_connected_devices_with_real_history_gap(
    tmp_path: Path,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(
        config,
        archive_sync=replace(
            config.archive_sync,
            reconnect_min_gap_seconds=3600,
            safety_margin_seconds=7200,
            bm200_max_pages_per_sync=3,
        ),
    )
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
        config=config,
        database_path=database_path,
        snapshot=snapshot,
    )

    assert candidates == {"bm200_house": 1}


def test_plan_archive_backfill_includes_bm300_when_bm7_archive_sync_is_enabled(
    tmp_path: Path,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(
        config,
        archive_sync=replace(
            config.archive_sync,
            bm300_enabled=True,
            reconnect_min_gap_seconds=3600,
            safety_margin_seconds=7200,
            bm300_max_pages_per_sync=4,
        ),
    )
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
                    id="bm300_doc",
                    type="bm300pro",
                    name="BM300 DOC",
                    mac="AA:BB:CC:DD:EE:30",
                    enabled=True,
                    connected=True,
                    voltage=13.38,
                    soc=98,
                    temperature=15.0,
                    rssi=None,
                    state="normal",
                    error_code=None,
                    error_detail=None,
                    last_seen="2024-01-01T00:00:00+00:00",
                    adapter="hci0",
                    driver="bm300pro",
                )
            ],
        ),
    )
    snapshot = GatewaySnapshot(
        generated_at="2024-01-04T00:00:00+00:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=True,
        mqtt_connected=False,
        devices_total=1,
        devices_online=1,
        poll_interval_seconds=600,
        devices=[
            DeviceReading(
                id="bm300_doc",
                type="bm300pro",
                name="BM300 DOC",
                mac="AA:BB:CC:DD:EE:30",
                enabled=True,
                connected=True,
                voltage=13.39,
                soc=98,
                temperature=15.0,
                rssi=-66,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2024-01-04T00:00:00+00:00",
                adapter="hci0",
                driver="bm300pro",
            )
        ],
    )

    candidates = plan_archive_backfill(
        config=config,
        database_path=database_path,
        snapshot=snapshot,
    )

    assert candidates == {"bm300_doc": 3}


def test_plan_archive_backfill_uses_periodic_history_age_to_size_pages(
    tmp_path: Path,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(
        config,
        archive_sync=replace(
            config.archive_sync,
            periodic_interval_seconds=64800,
            reconnect_min_gap_seconds=28800,
            safety_margin_seconds=7200,
            bm200_max_pages_per_sync=3,
        ),
    )
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="bm6_d15505_b7_v1",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.7,
                "min_crank_voltage": None,
                "event_type": 0,
                "soc": 80,
                "temperature": 22.0,
                "raw_record": "4f614160",
                "page_selector": 3,
                "record_index": 0,
                "timestamp_quality": "estimated",
            }
        ],
    )
    snapshot = GatewaySnapshot(
        generated_at="2024-01-01T20:00:00+00:00",
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
                last_seen="2024-01-01T20:00:00+00:00",
                adapter="hci0",
                driver="bm200",
            )
        ],
    )

    candidates = plan_archive_backfill(
        config=config,
        database_path=database_path,
        snapshot=snapshot,
    )

    assert candidates == {"bm200_house": 3}


def test_plan_archive_backfill_details_distinguishes_periodic_and_reconnect(
    tmp_path: Path,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(
        config,
        archive_sync=replace(
            config.archive_sync,
            periodic_interval_seconds=64800,
            reconnect_min_gap_seconds=28800,
            safety_margin_seconds=7200,
            bm200_max_pages_per_sync=3,
        ),
    )
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="bm6_d15505_b7_v1",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.7,
                "min_crank_voltage": None,
                "event_type": 0,
                "soc": 80,
                "temperature": 22.0,
                "raw_record": "4f614160",
                "page_selector": 3,
                "record_index": 0,
                "timestamp_quality": "estimated",
            }
        ],
    )
    persist_snapshot(
        database_path,
        GatewaySnapshot(
            generated_at="2024-01-01T12:00:00+00:00",
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
                    voltage=12.75,
                    soc=60,
                    temperature=None,
                    rssi=-60,
                    state="normal",
                    error_code=None,
                    error_detail=None,
                    last_seen="2024-01-01T12:00:00+00:00",
                    adapter="hci0",
                    driver="bm200",
                )
            ],
        ),
    )
    snapshot = GatewaySnapshot(
        generated_at="2024-01-01T20:00:00+00:00",
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
                last_seen="2024-01-01T20:00:00+00:00",
                adapter="hci0",
                driver="bm200",
            )
        ],
    )

    details = plan_archive_backfill_details(
        config=config,
        database_path=database_path,
        snapshot=snapshot,
    )

    assert details == {
        "bm200_house": {
            "page_count": 3,
            "reasons": ["periodic", "reconnect"],
        }
    }


def test_plan_archive_backfill_skips_when_archive_and_live_history_are_recent(
    tmp_path: Path,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(
        config,
        archive_sync=replace(
            config.archive_sync,
            periodic_interval_seconds=64800,
            reconnect_min_gap_seconds=28800,
            safety_margin_seconds=7200,
            bm200_max_pages_per_sync=3,
        ),
    )
    database_path = tmp_path / "gateway.db"
    persist_snapshot(
        database_path,
        GatewaySnapshot(
            generated_at="2024-01-01T11:50:00+00:00",
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
                    last_seen="2024-01-01T11:50:00+00:00",
                    adapter="hci0",
                    driver="bm200",
                )
            ],
        ),
    )
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="bm6_d15505_b7_v1",
        readings=[
            {
                "ts": "2024-01-01T11:30:00+00:00",
                "voltage": 12.7,
                "min_crank_voltage": None,
                "event_type": 0,
                "soc": 80,
                "temperature": 22.0,
                "raw_record": "4f614160",
                "page_selector": 3,
                "record_index": 0,
                "timestamp_quality": "estimated",
            }
        ],
    )
    snapshot = GatewaySnapshot(
        generated_at="2024-01-01T12:00:00+00:00",
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
                last_seen="2024-01-01T12:00:00+00:00",
                adapter="hci0",
                driver="bm200",
            )
        ],
    )

    candidates = plan_archive_backfill(
        config=config,
        database_path=database_path,
        snapshot=snapshot,
    )

    assert candidates == {}


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
        page_count: int,
        reference_ts: object = None,
        transport: object = None,
    ) -> list[object]:
        _ = (address, adapter, scan_timeout_seconds, reference_ts, transport)
        captured["timeout_seconds"] = timeout_seconds
        captured["page_count"] = float(page_count)
        return []

    monkeypatch.setattr("bm_gateway.archive_sync.read_bm200_history", fake_read_history)

    payload = sync_bm200_device_archive(
        config=config,
        device=devices[0],
        database_path=database_path,
    )

    assert payload["fetched"] == 0
    assert captured["timeout_seconds"] == 180.0
    assert captured["page_count"] == 3.0
    assert payload["profile"] == "bm6_d15505_b7_v1"


def test_sync_bm200_device_archive_imports_bm6_history_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    database_path = tmp_path / "gateway.db"

    async def fake_read_history(
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        page_count: int,
        reference_ts: object = None,
        transport: object = None,
    ) -> list[BM200HistoryReading]:
        _ = (
            address,
            adapter,
            timeout_seconds,
            scan_timeout_seconds,
            page_count,
            reference_ts,
            transport,
        )
        return [
            BM200HistoryReading(
                ts="2026-04-26T18:00:00+00:00",
                voltage=13.23,
                min_crank_voltage=None,
                event_type=0,
                soc=76,
                temperature=23.0,
                raw_record="52b4c170",
                page_selector=3,
                record_index=0,
                timestamp_quality="estimated",
            )
        ]

    monkeypatch.setattr("bm_gateway.archive_sync.read_bm200_history", fake_read_history)

    payload = sync_bm200_device_archive(
        config=config,
        device=devices[0],
        database_path=database_path,
    )

    assert payload["inserted"] == 1
    archive = fetch_archive_history(database_path, device_id="bm200_house", limit=1)
    assert archive[0]["soc"] == 76
    assert archive[0]["raw_record"] == "52b4c170"


def test_sync_bm300_device_archive_imports_bm7_history_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )
    database_path = tmp_path / "gateway.db"

    selector_calls: list[int] = []

    async def fake_read_selector(
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        selector_byte: int,
        selector_value: int,
        reference_ts: object = None,
        transport: object = None,
    ) -> list[BM300HistoryReading]:
        _ = (
            address,
            adapter,
            timeout_seconds,
            scan_timeout_seconds,
            selector_byte,
            reference_ts,
            transport,
        )
        selector_calls.append(selector_value)
        counts = {1: 130, 2: 160, 3: 180}
        reference_ts = datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc)
        return [
            BM300HistoryReading(
                ts=(reference_ts - timedelta(minutes=index * 2)).isoformat(timespec="seconds"),
                voltage=(0x4B0 + index) / 100,
                min_crank_voltage=None,
                event_type=index % 10,
                soc=index % 101,
                temperature=float(10 + (index % 40)),
                raw_record=(
                    f"{0x4B0 + index:03x}{index % 101:02x}{10 + (index % 40):02x}{index % 10:x}"
                ),
                page_selector=selector_value,
                record_index=index,
                timestamp_quality="estimated",
            )
            for index in range(counts[selector_value])
        ]

    monkeypatch.setattr("bm_gateway.archive_sync.read_bm300_history_selector", fake_read_selector)

    payload = sync_bm300_device_archive(
        config=config,
        device=device,
        database_path=database_path,
        page_count=9,
        progress=lambda _current, _total, _message: None,
    )

    assert selector_calls == [1, 2, 3]
    assert payload["fetched"] == 180
    assert payload["inserted"] == 180
    assert payload["profile"] == BM300_ARCHIVE_PROFILE
    assert payload["page_count"] == 3
    archive = fetch_archive_history(database_path, device_id="bm300_doc", limit=200)
    assert archive[0]["soc"] == 0
    assert archive[0]["temperature"] == 10.0
    assert archive[0]["raw_record"] == "4b0000a0"
    assert archive[-1]["raw_record"] == "5634e1d9"


def test_sync_bm300_device_archive_serializes_cross_process_bluetooth_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )
    database_path = tmp_path / "state" / "runtime" / "gateway.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    calls: list[tuple[Path | None, str]] = []

    @contextmanager
    def fake_lock(
        _config: object,
        *,
        operation: str,
        state_dir: Path | None = None,
        timeout_seconds: float = 600.0,
        retry_interval_seconds: float = 0.25,
    ) -> Iterator[dict[str, object]]:
        _ = (timeout_seconds, retry_interval_seconds)
        calls.append((state_dir, operation))
        yield {}

    async def fake_read_selector(
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        selector_byte: int,
        selector_value: int,
        reference_ts: object = None,
        transport: object = None,
    ) -> list[BM300HistoryReading]:
        _ = (
            address,
            adapter,
            timeout_seconds,
            scan_timeout_seconds,
            selector_byte,
            reference_ts,
            transport,
        )
        reference_ts = datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc)
        counts = {1: 130, 2: 160, 3: 180}
        return [
            BM300HistoryReading(
                ts=(reference_ts - timedelta(minutes=index * 2)).isoformat(timespec="seconds"),
                voltage=(0x4B0 + index) / 100,
                min_crank_voltage=None,
                event_type=index % 10,
                soc=index % 101,
                temperature=float(10 + (index % 40)),
                raw_record=(
                    f"{0x4B0 + index:03x}{index % 101:02x}{10 + (index % 40):02x}{index % 10:x}"
                ),
                page_selector=selector_value,
                record_index=index,
                timestamp_quality="estimated",
            )
            for index in range(counts[selector_value])
        ]

    monkeypatch.setattr("bm_gateway.archive_sync.exclusive_bluetooth_operation", fake_lock)
    monkeypatch.setattr("bm_gateway.archive_sync.read_bm300_history_selector", fake_read_selector)

    payload = sync_bm300_device_archive(
        config=config,
        device=device,
        database_path=database_path,
        page_count=3,
        progress=lambda _current, _total, _message: None,
    )

    assert payload["inserted"] == 180
    assert calls == [(tmp_path / "state", "archive_sync:bm300_doc")]


def test_sync_bm300_device_archive_uses_hard_timeout_runner_without_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )
    database_path = tmp_path / "state" / "runtime" / "gateway.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    calls: list[tuple[Path | None, str]] = []
    captured: dict[str, Any] = {}

    @contextmanager
    def fake_lock(
        _config: object,
        *,
        operation: str,
        state_dir: Path | None = None,
        timeout_seconds: float = 600.0,
        retry_interval_seconds: float = 0.25,
    ) -> Iterator[dict[str, object]]:
        _ = (timeout_seconds, retry_interval_seconds)
        calls.append((state_dir, operation))
        yield {}

    def fake_run_in_subprocess_with_timeout(
        *,
        function: object,
        args: tuple[object, ...],
        timeout_seconds: float,
        timeout_error: object,
    ) -> dict[str, object]:
        _ = timeout_error
        captured["function"] = function
        captured["args"] = args
        captured["timeout_seconds"] = timeout_seconds
        return {
            "device_id": device.id,
            "inserted": 180,
            "profile": BM300_ARCHIVE_PROFILE,
            "fetched_record_counts": {"b7=01": 130, "b7=02": 160, "b7=03": 180},
        }

    monkeypatch.setattr("bm_gateway.archive_sync.exclusive_bluetooth_operation", fake_lock)
    monkeypatch.setattr(
        "bm_gateway.archive_sync.run_in_subprocess_with_timeout",
        fake_run_in_subprocess_with_timeout,
    )

    payload = sync_bm300_device_archive(
        config=config,
        device=device,
        database_path=database_path,
        page_count=9,
    )

    assert payload["inserted"] == 180
    assert payload["fetched"] == 180
    assert payload["page_count"] == 3
    assert calls == [(tmp_path / "state", "archive_sync:bm300_doc")]
    assert captured["function"].__name__ == "_run_bm300_device_archive_import"
    assert captured["args"] == (config, device, database_path, 3, 180.0)
    assert captured["timeout_seconds"] == 570.0


def test_run_cycle_triggers_archive_sync_after_gap(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    config = replace(
        config,
        gateway=replace(config.gateway, reader_mode="live"),
        archive_sync=replace(
            config.archive_sync,
            reconnect_min_gap_seconds=3600,
            safety_margin_seconds=7200,
            bm200_max_pages_per_sync=3,
        ),
    )
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

    calls: list[dict[str, int]] = []

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

    def fake_build_snapshot(
        _config: object,
        _devices: object,
        *,
        state_dir: Path | None = None,
    ) -> GatewaySnapshot:
        _ = state_dir
        return second_snapshot

    def fake_sync(
        *,
        config: object,
        devices: object,
        database_path: Path,
        device_pages: dict[str, int],
        device_reasons: dict[str, list[str]],
    ) -> list[dict[str, object]]:
        _ = (config, devices, device_reasons)
        assert database_path == state_dir / "runtime" / "gateway.db"
        calls.append(dict(device_pages))
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

    assert calls == [{"bm200_house": 1}]


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


def test_run_cycle_writes_machine_audit_log(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    state_dir = tmp_path / "state"
    snapshot = GatewaySnapshot(
        generated_at="2026-05-01T12:05:00+02:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=True,
        mqtt_connected=False,
        devices_total=1,
        devices_online=1,
        poll_interval_seconds=15,
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
                temperature=18.5,
                rssi=-67,
                state="charging",
                error_code=None,
                error_detail=None,
                last_seen="2026-05-01T12:05:00+02:00",
                adapter="hci0",
                driver="bm200",
            )
        ],
    )

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

    def fake_build_snapshot(
        _config: object,
        _devices: object,
        *,
        state_dir: Path | None = None,
    ) -> GatewaySnapshot:
        _ = state_dir
        return snapshot

    cli_module_any = cast(Any, cli)
    original_build_snapshot = cli_module_any.build_snapshot
    original_sync_candidates = cli_module_any.sync_archive_backfill_candidates
    cli_module_any.build_snapshot = fake_build_snapshot
    cli_module_any.sync_archive_backfill_candidates = lambda **_kwargs: []
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

    audit_files = list((state_dir / "runtime" / "audit").glob("*.jsonl"))
    assert len(audit_files) == 1
    payloads = [
        json.loads(line) for line in audit_files[0].read_text(encoding="utf-8").splitlines()
    ]
    assert payloads[-2]["action"] == "device_poll_completed"
    assert payloads[-2]["details"]["device_id"] == "bm200_house"
    assert payloads[-1]["action"] == "run_cycle_completed"
    assert payloads[-1]["details"]["devices_online"] == 1
    assert payloads[-1]["details"]["archive_backfill_reasons"] == {}


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


def test_sync_archive_backfill_candidates_raises_for_fatal_bluetooth_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = _write_example_files(tmp_path)
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)

    def failing_sync(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError(
            "[org.freedesktop.DBus.Error.AccessDenied] Client tried to send a message "
            "other than Hello without being registered"
        )

    monkeypatch.setattr("bm_gateway.archive_sync.sync_bm200_device_archive", failing_sync)
    monkeypatch.setattr(
        "bm_gateway.bluetooth_recovery.restart_bluetooth_service",
        lambda: type(
            "Completed",
            (),
            {"returncode": 0, "stderr": ""},
        )(),
    )

    with pytest.raises(BluetoothRecoveryRequiredError):
        sync_archive_backfill_candidates(
            config=config,
            devices=devices,
            database_path=tmp_path / "gateway.db",
            device_pages={"bm200_house": 1},
        )
