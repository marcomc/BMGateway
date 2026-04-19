from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import cast

from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.state_store import (
    fetch_archive_history,
    fetch_daily_history,
    fetch_degradation_report,
    fetch_storage_summary,
    fetch_yearly_history,
    import_archive_history,
    persist_snapshot,
    prune_history,
    rebuild_daily_rollups,
)


def _snapshot(ts: str) -> GatewaySnapshot:
    return GatewaySnapshot(
        generated_at=ts,
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
                temperature=None,
                rssi=None,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen=ts,
                adapter="hci0",
                driver="bm200",
            )
        ],
    )


def test_prune_history_removes_old_raw_rows_but_keeps_daily_rollup_when_unlimited(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))

    prune_history(database_path, raw_retention_days=1, daily_retention_days=0)

    connection = sqlite3.connect(database_path)
    try:
        raw_count = connection.execute("SELECT COUNT(*) FROM device_readings").fetchone()
        daily_count = connection.execute("SELECT COUNT(*) FROM device_daily_rollups").fetchone()
    finally:
        connection.close()

    assert raw_count == (0,)
    assert daily_count == (1,)
    assert (
        fetch_daily_history(database_path, device_id="bm200_house", limit=30)[0]["day"]
        == "2024-01-01"
    )


def test_fetch_storage_summary_reports_raw_and_daily_ranges(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00"))

    summary = fetch_storage_summary(database_path)

    assert summary["counts"] == {
        "gateway_snapshots": 2,
        "device_readings": 2,
        "device_daily_rollups": 2,
        "device_archive_readings": 0,
    }
    assert summary["devices"] == [
        {
            "device_id": "bm200_house",
            "raw_samples": 2,
            "raw_first_ts": "2024-01-01T00:00:00+00:00",
            "raw_last_ts": "2024-01-02T00:00:00+00:00",
            "daily_days": 2,
            "daily_first_day": "2024-01-01",
            "daily_last_day": "2024-01-02",
            "archive_samples": 0,
            "archive_first_ts": None,
            "archive_last_ts": None,
        }
    ]


def test_fetch_yearly_history_groups_daily_rollups_by_year(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    persist_snapshot(database_path, _snapshot("2025-01-01T00:00:00+00:00"))

    yearly = fetch_yearly_history(database_path, device_id="bm200_house", limit=5)

    assert yearly == [
        {
            "device_id": "bm200_house",
            "year": "2025",
            "samples": 1,
            "min_voltage": 12.73,
            "max_voltage": 12.73,
            "avg_voltage": 12.73,
            "avg_soc": 58.0,
            "avg_temperature": None,
            "error_count": 0,
            "last_seen": "2025-01-01T00:00:00+00:00",
        },
        {
            "device_id": "bm200_house",
            "year": "2024",
            "samples": 1,
            "min_voltage": 12.73,
            "max_voltage": 12.73,
            "avg_voltage": 12.73,
            "avg_soc": 58.0,
            "avg_temperature": None,
            "error_count": 0,
            "last_seen": "2024-01-01T00:00:00+00:00",
        },
    ]


def test_fetch_yearly_history_uses_sample_weighted_averages(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_daily_rollups (
                device_id TEXT NOT NULL,
                day TEXT NOT NULL,
                samples INTEGER NOT NULL,
                min_voltage REAL NOT NULL,
                max_voltage REAL NOT NULL,
                avg_voltage REAL NOT NULL,
                avg_soc REAL NOT NULL,
                error_count INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (device_id, day)
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO device_daily_rollups (
                device_id,
                day,
                samples,
                min_voltage,
                max_voltage,
                avg_voltage,
                avg_soc,
                error_count,
                last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "bm200_house",
                    "2025-01-01",
                    1,
                    12.9,
                    13.1,
                    13.0,
                    90.0,
                    0,
                    "2025-01-01T23:55:00+00:00",
                ),
                (
                    "bm200_house",
                    "2025-01-02",
                    9,
                    11.9,
                    12.1,
                    12.0,
                    50.0,
                    0,
                    "2025-01-02T23:55:00+00:00",
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    yearly = fetch_yearly_history(database_path, device_id="bm200_house", limit=5)

    assert yearly[0]["samples"] == 10
    assert yearly[0]["avg_voltage"] == 12.1
    assert yearly[0]["avg_soc"] == 54.0


def test_fetch_degradation_report_compares_recent_window_with_previous_window(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_daily_rollups (
                device_id TEXT NOT NULL,
                day TEXT NOT NULL,
                samples INTEGER NOT NULL,
                min_voltage REAL NOT NULL,
                max_voltage REAL NOT NULL,
                avg_voltage REAL NOT NULL,
                avg_soc REAL NOT NULL,
                error_count INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (device_id, day)
            )
            """
        )
        start_day = date(2024, 1, 1)
        for day in range(60):
            avg_voltage = 12.9 if day < 30 else 12.4
            avg_soc = 88.0 if day < 30 else 72.0
            iso_day = (start_day + timedelta(days=day)).isoformat()
            connection.execute(
                """
                INSERT INTO device_daily_rollups (
                    device_id,
                    day,
                    samples,
                    min_voltage,
                    max_voltage,
                    avg_voltage,
                    avg_soc,
                    error_count,
                    last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bm200_house",
                    iso_day,
                    4,
                    avg_voltage - 0.1,
                    avg_voltage + 0.1,
                    avg_voltage,
                    avg_soc,
                    0,
                    f"{iso_day}T23:55:00+00:00",
                ),
            )
        connection.commit()
    finally:
        connection.close()

    report = fetch_degradation_report(database_path, device_id="bm200_house")
    windows = cast(list[dict[str, object]], report["windows"])

    assert report["latest_day"] == "2024-02-29"
    assert windows[0]["days"] == 30
    assert windows[0]["current_avg_voltage"] == 12.4
    assert windows[0]["previous_avg_voltage"] == 12.9
    assert windows[0]["delta_avg_voltage"] == -0.5
    assert windows[0]["current_avg_soc"] == 72.0
    assert windows[0]["previous_avg_soc"] == 88.0
    assert windows[0]["delta_avg_soc"] == -16.0


def test_fetch_degradation_report_uses_sample_weighted_averages(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_daily_rollups (
                device_id TEXT NOT NULL,
                day TEXT NOT NULL,
                samples INTEGER NOT NULL,
                min_voltage REAL NOT NULL,
                max_voltage REAL NOT NULL,
                avg_voltage REAL NOT NULL,
                avg_soc REAL NOT NULL,
                error_count INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (device_id, day)
            )
            """
        )
        start_day = date(2025, 1, 1)
        for offset in range(60):
            is_previous = offset < 30
            avg_voltage = 12.8 if is_previous else (13.0 if offset == 30 else 12.0)
            avg_soc = 80.0 if is_previous else (90.0 if offset == 30 else 50.0)
            samples = 1 if is_previous else (50 if offset == 30 else 1)
            iso_day = (start_day + timedelta(days=offset)).isoformat()
            connection.execute(
                """
                INSERT INTO device_daily_rollups (
                    device_id,
                    day,
                    samples,
                    min_voltage,
                    max_voltage,
                    avg_voltage,
                    avg_soc,
                    error_count,
                    last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bm200_house",
                    iso_day,
                    samples,
                    avg_voltage - 0.1,
                    avg_voltage + 0.1,
                    avg_voltage,
                    avg_soc,
                    0,
                    f"{iso_day}T23:55:00+00:00",
                ),
            )
        connection.commit()
    finally:
        connection.close()

    report = fetch_degradation_report(database_path, device_id="bm200_house")
    windows = cast(list[dict[str, object]], report["windows"])

    assert windows[0]["days"] == 30
    assert windows[0]["current_avg_voltage"] == 12.63
    assert windows[0]["current_avg_soc"] == 75.32


def test_persist_snapshot_keeps_daily_rollups_weighted_only_by_valid_samples(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    persist_snapshot(
        database_path,
        GatewaySnapshot(
            generated_at="2024-01-01T00:05:00+00:00",
            gateway_name="BMGateway",
            active_adapter="hci0",
            mqtt_enabled=True,
            mqtt_connected=False,
            devices_total=1,
            devices_online=0,
            poll_interval_seconds=300,
            devices=[
                DeviceReading(
                    id="bm200_house",
                    type="bm200",
                    name="BM200 House",
                    mac="AA:BB:CC:DD:EE:01",
                    enabled=True,
                    connected=False,
                    voltage=0.0,
                    soc=0,
                    temperature=None,
                    rssi=None,
                    state="error",
                    error_code="timeout",
                    error_detail="Device not found",
                    last_seen="2024-01-01T00:05:00+00:00",
                    adapter="hci0",
                    driver="bm200",
                )
            ],
        ),
    )

    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=5)

    assert daily == [
        {
            "device_id": "bm200_house",
            "day": "2024-01-01",
            "samples": 1,
            "min_voltage": 12.73,
            "max_voltage": 12.73,
            "avg_voltage": 12.73,
            "avg_soc": 58.0,
            "avg_temperature": None,
            "error_count": 1,
            "last_seen": "2024-01-01T00:05:00+00:00",
        }
    ]


def test_rebuild_daily_rollups_repairs_error_polluted_rollups(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE device_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_generated_at TEXT NOT NULL,
                device_id TEXT NOT NULL,
                device_type TEXT NOT NULL,
                name TEXT NOT NULL,
                mac TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                connected INTEGER NOT NULL,
                voltage REAL NOT NULL,
                soc INTEGER NOT NULL,
                temperature REAL,
                rssi INTEGER,
                state TEXT NOT NULL,
                error_code TEXT,
                error_detail TEXT,
                last_seen TEXT NOT NULL,
                adapter TEXT NOT NULL,
                driver TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE device_daily_rollups (
                device_id TEXT NOT NULL,
                day TEXT NOT NULL,
                samples INTEGER NOT NULL,
                min_voltage REAL NOT NULL,
                max_voltage REAL NOT NULL,
                avg_voltage REAL NOT NULL,
                avg_soc REAL NOT NULL,
                error_count INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (device_id, day)
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO device_readings (
                snapshot_generated_at,
                device_id,
                device_type,
                name,
                mac,
                enabled,
                connected,
                voltage,
                soc,
                temperature,
                rssi,
                state,
                error_code,
                error_detail,
                last_seen,
                adapter,
                driver
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2024-01-01T00:00:00+00:00",
                    "bm200_house",
                    "bm200",
                    "BM200 House",
                    "AA:BB:CC:DD:EE:01",
                    1,
                    1,
                    12.73,
                    58,
                    None,
                    None,
                    "normal",
                    None,
                    None,
                    "2024-01-01T00:00:00+00:00",
                    "hci0",
                    "bm200",
                ),
                (
                    "2024-01-01T00:05:00+00:00",
                    "bm200_house",
                    "bm200",
                    "BM200 House",
                    "AA:BB:CC:DD:EE:01",
                    1,
                    0,
                    0.0,
                    0,
                    None,
                    None,
                    "error",
                    "timeout",
                    "Device not found",
                    "2024-01-01T00:05:00+00:00",
                    "hci0",
                    "bm200",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO device_daily_rollups (
                device_id,
                day,
                samples,
                min_voltage,
                max_voltage,
                avg_voltage,
                avg_soc,
                error_count,
                last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bm200_house",
                "2024-01-01",
                2,
                0.0,
                12.73,
                6.365,
                29.0,
                1,
                "2024-01-01T00:05:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    rebuild_daily_rollups(database_path)

    assert fetch_daily_history(database_path, device_id="bm200_house", limit=5) == [
        {
            "device_id": "bm200_house",
            "day": "2024-01-01",
            "samples": 1,
            "min_voltage": 12.73,
            "max_voltage": 12.73,
            "avg_voltage": 12.73,
            "avg_soc": 58.0,
            "avg_temperature": None,
            "error_count": 1,
            "last_seen": "2024-01-01T00:05:00+00:00",
        }
    ]


def test_import_archive_history_is_idempotent_and_queryable(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    readings = [
        {
            "ts": "2024-01-01T00:00:00",
            "voltage": 12.61,
            "min_crank_voltage": 11.95,
            "event_type": 1,
        },
        {
            "ts": "2024-01-01T00:02:00",
            "voltage": 12.58,
            "min_crank_voltage": 11.92,
            "event_type": 1,
        },
    ]

    inserted_first = import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=readings,
    )
    inserted_second = import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=readings,
    )

    archive_rows = fetch_archive_history(database_path, device_id="bm200_house", limit=10)
    summary = fetch_storage_summary(database_path)
    summary_counts = cast(dict[str, object], summary["counts"])
    summary_devices = cast(list[dict[str, object]], summary["devices"])

    assert inserted_first == 2
    assert inserted_second == 0
    assert archive_rows[0]["ts"] == "2024-01-01T00:02:00"
    assert archive_rows[0]["sample_source"] == "device_archive"
    assert summary_counts["device_archive_readings"] == 2
    assert summary_devices[0]["archive_samples"] == 2
