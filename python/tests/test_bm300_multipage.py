from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, cast

import pytest
from bm_gateway import cli
from bm_gateway.bm300_multipage import (
    BM300_MULTIPAGE_PROFILE,
    BM300MultipageValidationError,
    run_bm300_multipage_import,
)
from bm_gateway.config import load_config
from bm_gateway.device_registry import Device
from bm_gateway.drivers.bm300 import BM300HistoryReading
from bm_gateway.runtime import database_file_path
from bm_gateway.state_store import fetch_archive_history


def _write_bm300_example_files(tmp_path: Path) -> Path:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
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


def _raw_record(index: int) -> str:
    voltage = 0x4B0 + (index % 200)
    soc = index % 101
    temperature = 10 + (index % 40)
    event = index % 10
    return f"{voltage:03x}{soc:02x}{temperature:02x}{event:x}"


def _history(selector: int, start: int, count: int) -> list[BM300HistoryReading]:
    reference_ts = datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)
    readings: list[BM300HistoryReading] = []
    for index in range(count):
        absolute_index = start + index
        raw_record = _raw_record(absolute_index)
        readings.append(
            BM300HistoryReading(
                ts=(reference_ts - timedelta(minutes=index * 2)).isoformat(timespec="seconds"),
                voltage=int(raw_record[0:3], 16) / 100,
                min_crank_voltage=None,
                event_type=int(raw_record[7], 16),
                soc=int(raw_record[3:5], 16),
                temperature=float(int(raw_record[5:7], 16)),
                raw_record=raw_record,
                page_selector=selector,
                record_index=index,
                timestamp_quality="estimated",
            )
        )
    return readings


def test_run_bm300_multipage_import_imports_selector_one_and_validated_older_prefixes(
    tmp_path: Path,
) -> None:
    output_db = tmp_path / "bm300-multipage.db"
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )
    selector_rows = {
        1: _history(1, 0, 130),
        2: _history(2, 0, 160),
        3: _history(3, 0, 180),
    }

    payload = run_bm300_multipage_import(
        device=device,
        output_database_path=output_db,
        adapter="hci0",
        selector_reader=lambda selector: selector_rows[selector],
    )

    archive_rows = fetch_archive_history(output_db, device_id="bm300_doc", limit=250)

    assert payload["device_id"] == "bm300_doc"
    assert payload["profile"] == BM300_MULTIPAGE_PROFILE
    assert payload["fetched_record_counts"] == {"1": 130, "2": 160, "3": 180}
    assert payload["validated_depth"] == 3
    assert payload["inserted"] == 180
    assert archive_rows[0]["raw_record"] == _raw_record(0)
    assert archive_rows[-1]["raw_record"] == _raw_record(179)
    assert archive_rows[0]["page_selector"] == 1
    assert archive_rows[129]["page_selector"] == 1
    assert archive_rows[130]["page_selector"] == 2
    assert archive_rows[-1]["page_selector"] == 3
    assert archive_rows[0]["profile"] == BM300_MULTIPAGE_PROFILE


def test_run_bm300_multipage_import_rejects_short_overlap_without_writing(
    tmp_path: Path,
) -> None:
    output_db = tmp_path / "bm300-multipage.db"
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )
    selector_rows = {
        1: _history(1, 0, 130),
        2: _history(2, 3, 127) + _history(2, 200, 20),
        3: _history(3, 0, 180),
    }

    with pytest.raises(BM300MultipageValidationError, match="128 consecutive"):
        run_bm300_multipage_import(
            device=device,
            output_database_path=output_db,
            adapter="hci0",
            selector_reader=lambda selector: selector_rows[selector],
        )

    assert not output_db.exists()


@pytest.mark.parametrize(
    ("selectors", "expected_inserted", "expected_depth"),
    [
        ((1,), 130, 1),
        ((1, 2), 160, 2),
    ],
)
def test_run_bm300_multipage_import_accepts_bounded_selector_depth(
    tmp_path: Path,
    selectors: tuple[int, ...],
    expected_inserted: int,
    expected_depth: int,
) -> None:
    output_db = tmp_path / "bm300-multipage.db"
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )
    selector_rows = {
        1: _history(1, 0, 130),
        2: _history(2, 0, 160),
        3: _history(3, 0, 180),
    }
    selector_calls: list[int] = []

    def selector_reader(selector: int) -> list[BM300HistoryReading]:
        selector_calls.append(selector)
        return selector_rows[selector]

    payload = run_bm300_multipage_import(
        device=device,
        output_database_path=output_db,
        adapter="hci0",
        selector_reader=selector_reader,
        selectors=selectors,
    )

    archive_rows = fetch_archive_history(output_db, device_id="bm300_doc", limit=250)

    assert selector_calls == list(selectors)
    assert payload["selectors"] == list(selectors)
    assert payload["validated_depth"] == expected_depth
    assert payload["inserted"] == expected_inserted
    assert len(archive_rows) == expected_inserted


def test_cli_bm300_multipage_import_rejects_runtime_database_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_bm300_example_files(tmp_path)
    config = load_config(config_path)
    runtime_db = database_file_path(config)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "protocol",
            "bm300-multipage-import",
            "--device-id",
            "bm300_doc",
            "--output-db",
            str(runtime_db),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "refuses to write to the normal runtime database" in captured.err


def test_bm300_selector_reader_uses_byte_7_history_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    device = Device(
        id="bm300_doc",
        type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
    )

    class FakeTransport:
        async def read_history_request(
            self,
            *,
            address: str,
            adapter: str,
            timeout_seconds: float,
            scan_timeout_seconds: float,
            reference_ts: datetime,
            request: bytes,
            page_selector: int,
        ) -> list[BM300HistoryReading]:
            captured["address"] = address
            captured["adapter"] = adapter
            captured["timeout_seconds"] = timeout_seconds
            captured["scan_timeout_seconds"] = scan_timeout_seconds
            captured["reference_ts"] = reference_ts
            captured["request"] = request.hex()
            captured["page_selector"] = page_selector
            return []

    monkeypatch.setattr(cli, "BleakBM7HistoryTransport", FakeTransport)

    reader = cli._bm300_selector_reader(
        device=device,
        adapter="hci0",
        scan_timeout_seconds=8,
        connect_timeout_seconds=10,
    )
    reader(3)

    assert captured["address"] == "AA:BB:CC:DD:EE:30"
    assert captured["adapter"] == "hci0"
    assert captured["timeout_seconds"] == 180.0
    assert captured["scan_timeout_seconds"] == 8.0
    assert captured["page_selector"] == 3
    assert captured["request"] == "d1550500000000030000000000000000"


def test_cli_bm300_multipage_import_emits_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_bm300_example_files(tmp_path)
    output_db = tmp_path / "protocol-import.db"
    runtime_db = tmp_path / "state" / "runtime" / "gateway.db"
    calls: list[dict[str, object]] = []
    lock_calls: list[tuple[Path | None, str]] = []

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
        lock_calls.append((state_dir, operation))
        yield {}

    def fake_run(
        *,
        device: Device,
        output_database_path: Path,
        adapter: str,
        selector_reader: object | None = None,
    ) -> dict[str, object]:
        calls.append(
            {
                "device_id": device.id,
                "output_database_path": output_database_path,
                "adapter": adapter,
                "selector_reader": selector_reader,
            }
        )
        return {
            "device_id": device.id,
            "selectors": [1, 2, 3],
            "fetched_record_counts": {"1": 256, "2": 512, "3": 768},
            "validated_depth": 3,
            "inserted": 768,
            "adapter": adapter,
            "profile": BM300_MULTIPAGE_PROFILE,
            "output_db": str(output_database_path),
            "overlaps": [],
        }

    monkeypatch.setattr(cli, "database_file_path", lambda _config: runtime_db, raising=False)
    monkeypatch.setattr(cli, "exclusive_bluetooth_operation", fake_lock, raising=False)
    monkeypatch.setattr(cli, "run_bm300_multipage_import", fake_run, raising=False)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "protocol",
            "bm300-multipage-import",
            "--device-id",
            "bm300_doc",
            "--output-db",
            str(output_db),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert result == 0
    assert len(calls) == 1
    assert cast(str, calls[0]["device_id"]) == "bm300_doc"
    assert cast(Path, calls[0]["output_database_path"]) == output_db
    assert cast(str, calls[0]["adapter"]) == "hci0"
    assert lock_calls == [(tmp_path / "state", "protocol_bm300_multipage_import:bm300_doc")]
    assert payload["device_id"] == "bm300_doc"
    assert payload["output_db"] == str(output_db)
