from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.state_store import (
    delete_archive_history_profiles,
    fetch_archive_history,
    fetch_counts,
    fetch_daily_history,
    fetch_daily_history_window,
    fetch_degradation_report,
    fetch_history_bounds,
    fetch_history_window,
    fetch_monthly_history,
    fetch_recent_history,
    fetch_recent_history_since,
    fetch_storage_summary,
    fetch_yearly_history,
    history_device_id_exists,
    import_archive_history,
    latest_history_timestamp,
    persist_snapshot,
    prune_history,
    rebuild_daily_rollups,
    rename_history_device_id,
    replace_archive_history_profiles,
)


def _snapshot(
    ts: str,
    *,
    connected: bool = True,
    voltage: float = 12.73,
    soc: int = 58,
    temperature: float | None = None,
    state: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    last_seen: str | None = None,
) -> GatewaySnapshot:
    return GatewaySnapshot(
        generated_at=ts,
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=True,
        mqtt_connected=False,
        devices_total=1,
        devices_online=1 if connected else 0,
        poll_interval_seconds=15,
        devices=[
            DeviceReading(
                id="bm200_house",
                type="bm200",
                name="BM200 House",
                mac="AA:BB:CC:DD:EE:01",
                enabled=True,
                connected=connected,
                voltage=voltage,
                soc=soc,
                temperature=temperature,
                rssi=None,
                state=state or ("normal" if connected else "error"),
                error_code=error_code,
                error_detail=error_detail,
                last_seen=ts if last_seen is None else last_seen,
                adapter="hci0",
                driver="bm200",
            )
        ],
    )


def test_persist_snapshot_uses_device_samples_as_canonical_raw_store(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"

    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))

    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            """
            SELECT device_id, sample_ts, source, source_profile, voltage, soc
            FROM device_samples
            """
        ).fetchall()
    finally:
        connection.close()

    assert rows == [("bm200_house", "2024-01-01T00:00:00+00:00", "live", "live", 12.73, 58)]
    assert (
        fetch_recent_history(database_path, device_id="bm200_house", limit=1)[0]["sample_source"]
        == "live"
    )


def test_schema_cache_recreates_database_after_file_replacement(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))

    for suffix in ("", "-shm", "-wal"):
        database_path.with_name(f"{database_path.name}{suffix}").unlink(missing_ok=True)

    counts = fetch_counts(database_path)

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert counts["device_samples"] == 0
    assert counts["device_readings"] == 0
    assert {"device_samples", "state_store_metadata"} <= tables


def test_persist_snapshot_does_not_double_count_duplicate_canonical_sample(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    snapshot = _snapshot("2024-01-01T00:00:00+00:00")

    persist_snapshot(database_path, snapshot)
    persist_snapshot(database_path, snapshot)

    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=10)
    connection = sqlite3.connect(database_path)
    try:
        sample_count = connection.execute("SELECT COUNT(*) FROM device_samples").fetchone()
    finally:
        connection.close()

    assert sample_count == (1,)
    assert daily[0]["samples"] == 1
    assert daily[0]["avg_voltage"] == 12.73


def test_persist_snapshot_rolls_up_error_attempts_by_sample_day(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T23:55:00+00:00"))

    persist_snapshot(
        database_path,
        _snapshot(
            "2024-01-02T00:05:00+00:00",
            connected=False,
            voltage=0.0,
            soc=0,
            error_code="timeout",
            error_detail="Device not found",
            last_seen="2024-01-01T23:55:00+00:00",
        ),
    )

    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=10)

    assert daily[0]["day"] == "2024-01-02"
    assert daily[0]["samples"] == 0
    assert daily[0]["error_count"] == 1
    assert daily[1]["day"] == "2024-01-01"
    assert daily[1]["samples"] == 1
    assert daily[1]["error_count"] == 0


def test_persist_snapshot_averages_temperature_over_non_null_values(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"

    persist_snapshot(
        database_path,
        _snapshot("2024-01-01T00:00:00+00:00", temperature=None),
    )
    persist_snapshot(
        database_path,
        _snapshot("2024-01-01T00:05:00+00:00", temperature=20.0),
    )
    persist_snapshot(
        database_path,
        _snapshot("2024-01-01T00:10:00+00:00", temperature=22.0),
    )

    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=10)

    assert daily[0]["samples"] == 3
    assert daily[0]["avg_temperature"] == 21.0


def test_prune_history_removes_old_raw_rows_and_retains_daily_rollups(
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
    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=30)
    assert daily[0]["day"] == "2024-01-01"


def test_prune_history_applies_daily_rollup_retention_independently_of_raw_retention(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    now = datetime.now(tz=timezone.utc).astimezone()
    expired_day = (now - timedelta(days=20)).isoformat(timespec="seconds")
    retained_day = (now - timedelta(days=2)).isoformat(timespec="seconds")
    persist_snapshot(database_path, _snapshot(expired_day))
    persist_snapshot(database_path, _snapshot(retained_day))

    prune_history(database_path, raw_retention_days=1, daily_retention_days=10)

    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=30)

    assert [row["day"] for row in daily] == [retained_day[:10]]


def test_daily_window_rebuilds_days_retained_only_as_raw_samples(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    timestamp = (datetime.now(tz=timezone.utc).astimezone() - timedelta(days=3)).isoformat(
        timespec="seconds"
    )
    persist_snapshot(database_path, _snapshot(timestamp))

    prune_history(database_path, raw_retention_days=30, daily_retention_days=1)

    daily = fetch_daily_history_window(
        database_path,
        device_id="bm200_house",
        start_day=timestamp[:10],
        end_day=timestamp[:10],
    )

    assert daily == [
        {
            "device_id": "bm200_house",
            "day": timestamp[:10],
            "samples": 1,
            "min_voltage": 12.73,
            "max_voltage": 12.73,
            "avg_voltage": 12.73,
            "avg_soc": 58.0,
            "avg_temperature": None,
            "error_count": 0,
            "last_seen": timestamp,
            "raw_history_complete": True,
        }
    ]


def test_prune_history_removes_old_archive_rows_with_raw_retention(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    now = datetime.now(tz=timezone.utc).astimezone()
    old_ts = (now - timedelta(days=3)).isoformat(timespec="seconds")
    kept_ts = (now - timedelta(hours=12)).isoformat(timespec="seconds")
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": old_ts,
                "voltage": 12.61,
                "min_crank_voltage": None,
                "event_type": 0,
            },
            {
                "ts": kept_ts,
                "voltage": 12.62,
                "min_crank_voltage": None,
                "event_type": 0,
            },
        ],
    )

    prune_history(database_path, raw_retention_days=1, daily_retention_days=0)

    archive_rows = fetch_archive_history(database_path, device_id="bm200_house", limit=10)
    assert [row["ts"] for row in archive_rows] == [kept_ts]


def test_archive_profile_changes_preserve_daily_rollup_when_raw_history_is_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "gateway.db"
    for timestamp, voltage in (
        ("2026-07-15T00:00:00+02:00", 12.0),
        ("2026-07-15T06:00:00+02:00", 13.0),
        ("2026-07-15T18:00:00+02:00", 14.0),
    ):
        persist_snapshot(database_path, _snapshot(timestamp, voltage=voltage))
    monkeypatch.setattr(
        "bm_gateway.state_store._cutoff_iso",
        lambda _days: "2026-07-15T12:00:00+02:00",
    )
    prune_history(database_path, raw_retention_days=1, daily_retention_days=0)
    connection = sqlite3.connect(database_path)
    try:
        # Existing databases receive the new marker with its complete-history
        # default, so the retained-versus-raw count fallback remains necessary.
        connection.execute("UPDATE device_daily_rollups SET raw_history_complete = 1")
        connection.commit()
    finally:
        connection.close()

    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2026-07-15T20:00:00+02:00",
                "voltage": 14.5,
                "min_crank_voltage": None,
                "event_type": 0,
            }
        ],
    )

    with pytest.raises(ValueError, match="Cannot replace or delete archive history"):
        delete_archive_history_profiles(
            database_path,
            device_id="bm200_house",
            profiles=("legacy_bm2_history",),
        )
    with pytest.raises(ValueError, match="Cannot replace or delete archive history"):
        replace_archive_history_profiles(
            database_path,
            device_id="bm200_house",
            device_type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            adapter="hci0",
            driver="bm200",
            profile="replacement_history",
            replace_profiles=("legacy_bm2_history",),
            readings=[
                {
                    "ts": "2026-07-15T21:00:00+02:00",
                    "voltage": 15.0,
                    "min_crank_voltage": None,
                    "event_type": 0,
                }
            ],
        )

    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=1)
    archive = fetch_archive_history(database_path, device_id="bm200_house", limit=1)

    assert daily[0]["samples"] == 3
    assert daily[0]["min_voltage"] == 12.0
    assert daily[0]["max_voltage"] == 14.0
    assert daily[0]["avg_voltage"] == 13.0
    assert archive[0]["profile"] == "legacy_bm2_history"


def test_archive_import_does_not_replace_retained_rollup_when_raw_counts_tie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "gateway.db"
    for timestamp, voltage in (
        ("2026-07-15T00:00:00+02:00", 12.0),
        ("2026-07-15T06:00:00+02:00", 13.0),
        ("2026-07-15T18:00:00+02:00", 14.0),
    ):
        persist_snapshot(database_path, _snapshot(timestamp, voltage=voltage))
    monkeypatch.setattr(
        "bm_gateway.state_store._cutoff_iso",
        lambda _days: "2026-07-15T12:00:00+02:00",
    )
    prune_history(database_path, raw_retention_days=1, daily_retention_days=0)

    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2026-07-15T20:00:00+02:00",
                "voltage": 14.5,
                "min_crank_voltage": None,
                "event_type": 0,
            },
            {
                "ts": "2026-07-15T21:00:00+02:00",
                "voltage": 15.0,
                "min_crank_voltage": None,
                "event_type": 0,
            },
        ],
    )

    assert fetch_counts(database_path)["device_samples"] == 3
    assert (
        fetch_daily_history_window(
            database_path,
            device_id="bm200_house",
            start_day="2026-07-15",
            end_day="2026-07-15",
        )[0]["raw_history_complete"]
        is False
    )
    assert fetch_daily_history(database_path, device_id="bm200_house", limit=1) == [
        {
            "device_id": "bm200_house",
            "day": "2026-07-15",
            "samples": 3,
            "min_voltage": 12.0,
            "max_voltage": 14.0,
            "avg_voltage": 13.0,
            "avg_soc": 58.0,
            "avg_temperature": None,
            "error_count": 0,
            "last_seen": "2026-07-15T18:00:00+02:00",
        }
    ]


def test_archive_profile_changes_rebuild_daily_rollups_from_complete_raw_history(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    for profile, timestamp, voltage in (
        ("legacy_bm2_history", "2026-07-15T00:00:00+02:00", 12.0),
        ("secondary_history", "2026-07-15T06:00:00+02:00", 13.0),
    ):
        import_archive_history(
            database_path,
            device_id="bm200_house",
            device_type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            adapter="hci0",
            driver="bm200",
            profile=profile,
            readings=[
                {
                    "ts": timestamp,
                    "voltage": voltage,
                    "min_crank_voltage": None,
                    "event_type": 0,
                }
            ],
        )

    deleted = delete_archive_history_profiles(
        database_path,
        device_id="bm200_house",
        profiles=("legacy_bm2_history",),
    )
    daily_after_delete = fetch_daily_history(database_path, device_id="bm200_house", limit=1)

    replaced = replace_archive_history_profiles(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="replacement_history",
        replace_profiles=("secondary_history",),
        readings=[
            {
                "ts": "2026-07-15T12:00:00+02:00",
                "voltage": 15.0,
                "min_crank_voltage": None,
                "event_type": 0,
            }
        ],
    )
    daily_after_replace = fetch_daily_history(database_path, device_id="bm200_house", limit=1)

    assert deleted == 1
    assert len(daily_after_delete) == 1
    assert daily_after_delete[0]["day"] == "2026-07-15"
    assert daily_after_delete[0]["samples"] == 1
    assert daily_after_delete[0]["min_voltage"] == 13.0
    assert daily_after_delete[0]["max_voltage"] == 13.0
    assert daily_after_delete[0]["avg_voltage"] == 13.0
    assert daily_after_delete[0]["last_seen"] == "2026-07-15T06:00:00+02:00"
    assert replaced == 1
    assert len(daily_after_replace) == 1
    assert daily_after_replace[0]["day"] == "2026-07-15"
    assert daily_after_replace[0]["samples"] == 1
    assert daily_after_replace[0]["min_voltage"] == 15.0
    assert daily_after_replace[0]["max_voltage"] == 15.0
    assert daily_after_replace[0]["avg_voltage"] == 15.0
    assert daily_after_replace[0]["last_seen"] == "2026-07-15T12:00:00+02:00"


def test_prune_history_removes_old_canonical_samples_with_raw_retention(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    now = datetime.now(tz=timezone.utc).astimezone()
    old_ts = (now - timedelta(days=3)).isoformat(timespec="seconds")
    kept_ts = (now - timedelta(hours=12)).isoformat(timespec="seconds")
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": old_ts,
                "voltage": 12.61,
                "min_crank_voltage": None,
                "event_type": 0,
            },
            {
                "ts": kept_ts,
                "voltage": 12.62,
                "min_crank_voltage": None,
                "event_type": 0,
            },
        ],
    )

    prune_history(database_path, raw_retention_days=1, daily_retention_days=0)

    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            "SELECT sample_ts FROM device_samples ORDER BY sample_ts"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [(kept_ts,)]


def test_import_archive_history_uses_device_samples_as_canonical_store(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"

    inserted = import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.61,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            }
        ],
    )

    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            """
            SELECT device_id, sample_ts, source, source_profile, voltage, min_crank_voltage
            FROM device_samples
            """
        ).fetchall()
    finally:
        connection.close()

    assert inserted == 1
    assert rows == [
        (
            "bm200_house",
            "2024-01-01T00:00:00+00:00",
            "device_archive",
            "legacy_bm2_history",
            12.61,
            11.95,
        )
    ]


def test_import_archive_history_records_completed_batch(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"

    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.61,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            }
        ],
    )

    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            """
            SELECT device_id, profile, status, fetched_count, inserted_count
            FROM archive_import_batches
            """
        ).fetchall()
    finally:
        connection.close()

    assert rows == [("bm200_house", "legacy_bm2_history", "completed", 1, 1)]


def test_history_readers_use_canonical_samples_when_legacy_tables_are_empty(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00"))
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.61,
                "soc": 70,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            }
        ],
    )
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DELETE FROM device_readings")
        connection.execute("DELETE FROM device_archive_readings")
        connection.commit()
    finally:
        connection.close()

    recent_rows = fetch_recent_history(database_path, device_id="bm200_house", limit=10)
    archive_rows = fetch_archive_history(database_path, device_id="bm200_house", limit=10)

    assert [row["sample_source"] for row in recent_rows] == ["live", "device_archive"]
    assert archive_rows[0]["ts"] == "2024-01-01T00:00:00+00:00"
    assert latest_history_timestamp(database_path, device_id="bm200_house") == (
        "2024-01-02T00:00:00+00:00"
    )


def test_fetch_storage_summary_reports_raw_and_daily_ranges(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00"))

    summary = fetch_storage_summary(database_path)

    assert summary["counts"] == {
        "gateway_snapshots": 2,
        "device_samples": 2,
        "device_readings": 0,
        "device_daily_rollups": 2,
        "device_archive_readings": 0,
        "archive_import_batches": 0,
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


def test_rename_history_device_id_updates_canonical_daily_and_archive_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.7,
                "min_crank_voltage": None,
                "event_type": None,
            }
        ],
    )

    rename_history_device_id(
        database_path,
        old_device_id="bm200_house",
        new_device_id="starter",
        device_type="bm200",
        name="Starter Battery",
        mac="AA:BB:CC:DD:EE:99",
    )

    assert not history_device_id_exists(database_path, "bm200_house")
    assert history_device_id_exists(database_path, "starter")
    assert (
        fetch_recent_history(database_path, device_id="starter", limit=10)[0]["sample_source"]
        == "live"
    )
    assert (
        fetch_daily_history(database_path, device_id="starter", limit=10)[0]["day"] == "2024-01-01"
    )
    assert (
        fetch_archive_history(database_path, device_id="starter", limit=10)[0]["sample_source"]
        == "device_archive"
    )
    connection = sqlite3.connect(database_path)
    try:
        sample_metadata = connection.execute(
            """
            SELECT DISTINCT source, device_type, name, mac
            FROM device_samples
            WHERE device_id = ?
            ORDER BY source
            """,
            ("starter",),
        ).fetchall()
    finally:
        connection.close()

    assert sample_metadata == [
        ("device_archive", "bm200", "Starter Battery", "AA:BB:CC:DD:EE:99"),
        ("live", "bm200", "Starter Battery", "AA:BB:CC:DD:EE:99"),
    ]


def test_import_archive_history_preserves_bm6_history_fields(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"

    inserted = import_archive_history(
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
                "ts": "2026-04-26T18:00:00+00:00",
                "voltage": 13.23,
                "soc": 76,
                "temperature": 23.0,
                "event_type": 0,
                "raw_record": "52b4c170",
                "page_selector": 2,
                "record_index": 0,
                "timestamp_quality": "estimated",
            },
            {
                "ts": "2026-04-26T17:58:00+00:00",
                "voltage": 13.23,
                "soc": 77,
                "temperature": 22.0,
                "event_type": 0,
                "raw_record": "52b4d160",
                "page_selector": 2,
                "record_index": 1,
                "timestamp_quality": "estimated",
            },
        ],
    )

    assert inserted == 2
    archive = fetch_archive_history(database_path, device_id="bm200_house", limit=10)
    assert archive[0]["soc"] == 76
    assert archive[0]["temperature"] == 23.0
    assert archive[0]["raw_record"] == "52b4c170"
    assert archive[0]["page_selector"] == 2
    assert archive[0]["record_index"] == 0
    assert archive[0]["timestamp_quality"] == "estimated"
    assert fetch_recent_history(database_path, device_id="bm200_house", limit=1)[0] == {
        "ts": "2026-04-26T18:00:00+00:00",
        "voltage": 13.23,
        "soc": 76,
        "temperature": 23.0,
        "state": "archive",
        "error_code": None,
        "error_detail": None,
        "sample_source": "device_archive",
    }
    daily = fetch_daily_history(database_path, device_id="bm200_house", limit=1)
    assert daily[0]["avg_soc"] == 76.5
    assert daily[0]["avg_temperature"] == 22.5


def test_history_device_id_exists_detects_existing_storage_identity(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))

    assert history_device_id_exists(database_path, "bm200_house")
    assert not history_device_id_exists(database_path, "starter")


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


def test_fetch_yearly_history_uses_archive_samples_after_import(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.6,
                "soc": 70,
                "temperature": 20.0,
                "min_crank_voltage": None,
                "event_type": 0,
            },
            {
                "ts": "2024-01-01T00:02:00+00:00",
                "voltage": 12.8,
                "soc": 74,
                "temperature": 22.0,
                "min_crank_voltage": None,
                "event_type": 0,
            },
        ],
    )

    yearly = fetch_yearly_history(database_path, device_id="bm200_house", limit=5)

    assert yearly == [
        {
            "device_id": "bm200_house",
            "year": "2024",
            "samples": 2,
            "min_voltage": 12.6,
            "max_voltage": 12.8,
            "avg_voltage": 12.7,
            "avg_soc": 72.0,
            "avg_temperature": 21.0,
            "error_count": 0,
            "last_seen": "2024-01-01T00:02:00+00:00",
        }
    ]


def test_monthly_and_yearly_history_ignore_days_without_soc(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.6,
                "min_crank_voltage": None,
                "event_type": 0,
            },
            {
                "ts": "2024-01-01T00:02:00+00:00",
                "voltage": 12.8,
                "min_crank_voltage": None,
                "event_type": 0,
            },
        ],
    )
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00", soc=80))

    monthly = fetch_monthly_history(database_path, device_id="bm200_house", limit=5)
    yearly = fetch_yearly_history(database_path, device_id="bm200_house", limit=5)

    assert monthly[0]["samples"] == 3
    assert monthly[0]["avg_soc"] == 80.0
    assert yearly[0]["samples"] == 3
    assert yearly[0]["avg_soc"] == 80.0


def test_monthly_and_yearly_history_return_null_soc_when_no_days_have_soc(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.6,
                "min_crank_voltage": None,
                "event_type": 0,
            }
        ],
    )

    monthly = fetch_monthly_history(database_path, device_id="bm200_house", limit=5)
    yearly = fetch_yearly_history(database_path, device_id="bm200_house", limit=5)

    assert monthly[0]["avg_soc"] is None
    assert yearly[0]["avg_soc"] is None


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


def test_fetch_degradation_report_ignores_days_without_soc(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.61,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            },
            {
                "ts": "2024-01-01T00:02:00+00:00",
                "voltage": 12.58,
                "min_crank_voltage": 11.92,
                "event_type": 1,
            },
        ],
    )

    report = fetch_degradation_report(database_path, device_id="bm200_house")

    assert report == {
        "device_id": "bm200_house",
        "latest_day": "2024-01-01",
        "windows": [],
    }


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


def test_history_readers_migrate_legacy_rows_before_canonical_reads(tmp_path: Path) -> None:
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
        )
        connection.execute(
            """
            CREATE TABLE device_archive_readings (
                device_id TEXT NOT NULL,
                device_type TEXT NOT NULL,
                name TEXT NOT NULL,
                mac TEXT NOT NULL,
                ts TEXT NOT NULL,
                voltage REAL NOT NULL,
                min_crank_voltage REAL,
                event_type INTEGER,
                imported_at TEXT NOT NULL,
                adapter TEXT NOT NULL,
                driver TEXT NOT NULL,
                profile TEXT NOT NULL,
                PRIMARY KEY (device_id, ts, profile)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO device_archive_readings (
                device_id,
                device_type,
                name,
                mac,
                ts,
                voltage,
                min_crank_voltage,
                event_type,
                imported_at,
                adapter,
                driver,
                profile
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bm200_house",
                "bm200",
                "BM200 House",
                "AA:BB:CC:DD:EE:01",
                "2023-12-31T23:50:00+00:00",
                12.61,
                None,
                None,
                "2024-01-01T00:10:00+00:00",
                "hci0",
                "bm200",
                "history",
            ),
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
                avg_soc REAL,
                min_temperature REAL,
                max_temperature REAL,
                avg_temperature REAL,
                error_count INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (device_id, day)
            )
            """
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
                min_temperature,
                max_temperature,
                avg_temperature,
                error_count,
                last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bm200_house",
                "2024-01-01",
                1,
                12.73,
                12.73,
                12.73,
                58.0,
                None,
                None,
                None,
                0,
                "2024-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    recent_rows = fetch_recent_history(database_path, device_id="bm200_house", limit=5)
    archive_rows = fetch_archive_history(database_path, device_id="bm200_house", limit=5)
    daily_rows = fetch_daily_history(database_path, device_id="bm200_house", limit=5)

    connection = sqlite3.connect(database_path)
    try:
        sample_count = connection.execute("SELECT COUNT(*) FROM device_samples").fetchone()
        migration_flag = connection.execute(
            "SELECT value FROM state_store_metadata WHERE key = ?",
            ("legacy_history_imported_to_device_samples",),
        ).fetchone()
    finally:
        connection.close()

    assert [row["sample_source"] for row in recent_rows] == ["live", "device_archive"]
    assert archive_rows[0]["profile"] == "history"
    assert [row["day"] for row in daily_rows] == ["2024-01-01", "2023-12-31"]
    assert sample_count == (2,)
    assert migration_flag == ("1",)

    rebuild_daily_rollups(database_path)

    connection = sqlite3.connect(database_path)
    try:
        sample_count = connection.execute("SELECT COUNT(*) FROM device_samples").fetchone()
        migration_flag = connection.execute(
            "SELECT value FROM state_store_metadata WHERE key = ?",
            ("legacy_history_imported_to_device_samples",),
        ).fetchone()
    finally:
        connection.close()

    assert sample_count == (2,)
    assert migration_flag == ("1",)


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
    assert summary_counts["device_samples"] == 2
    assert summary_counts["device_archive_readings"] == 0
    assert summary_devices[0]["archive_samples"] == 2


def test_delete_archive_history_profiles_removes_only_selected_profiles(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    readings = [
        {
            "ts": "2024-01-01T00:00:00+00:00",
            "voltage": 12.61,
            "min_crank_voltage": None,
            "event_type": 0,
        }
    ]

    import_archive_history(
        database_path,
        device_id="bm300_doc",
        device_type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
        adapter="hci0",
        driver="bm300pro",
        profile="bm7_d15505_b6_v1",
        readings=readings,
    )
    import_archive_history(
        database_path,
        device_id="bm300_doc",
        device_type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
        adapter="hci0",
        driver="bm300pro",
        profile="bm7_d15505_b7_v1",
        readings=readings,
    )

    deleted = delete_archive_history_profiles(
        database_path,
        device_id="bm300_doc",
        profiles=("bm7_d15505_b6_v1",),
    )

    archive_rows = fetch_archive_history(database_path, device_id="bm300_doc", limit=10)

    assert deleted == 1
    assert len(archive_rows) == 1
    assert archive_rows[0]["profile"] == "bm7_d15505_b7_v1"


def test_replace_archive_history_profiles_rolls_back_when_import_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    original_readings = [
        {
            "ts": "2024-01-01T00:00:00+00:00",
            "voltage": 12.61,
            "min_crank_voltage": None,
            "event_type": 0,
        }
    ]
    import_archive_history(
        database_path,
        device_id="bm300_doc",
        device_type="bm300pro",
        name="BM300 DOC",
        mac="AA:BB:CC:DD:EE:30",
        adapter="hci0",
        driver="bm300pro",
        profile="bm7_d15505_b6_v1",
        readings=original_readings,
    )

    replacement_readings: list[dict[str, object]] = [
        {
            "ts": "2024-01-01T00:02:00+00:00",
            "voltage": 12.7,
            "min_crank_voltage": None,
            "event_type": 1,
        },
        {
            "ts": "2024-01-01T00:04:00+00:00",
            "min_crank_voltage": None,
            "event_type": 2,
        },
    ]

    with pytest.raises(KeyError, match="voltage"):
        replace_archive_history_profiles(
            database_path,
            device_id="bm300_doc",
            device_type="bm300pro",
            name="BM300 DOC",
            mac="AA:BB:CC:DD:EE:30",
            adapter="hci0",
            driver="bm300pro",
            profile="bm7_d15505_b7_v1",
            replace_profiles=("bm7_d15505_b6_v1",),
            readings=replacement_readings,
        )

    archive_rows = fetch_archive_history(database_path, device_id="bm300_doc", limit=10)
    connection = sqlite3.connect(database_path)
    try:
        batches = connection.execute(
            """
            SELECT profile, status, fetched_count, inserted_count
            FROM archive_import_batches
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()

    assert len(archive_rows) == 1
    assert archive_rows[0]["profile"] == "bm7_d15505_b6_v1"
    assert archive_rows[0]["ts"] == "2024-01-01T00:00:00+00:00"
    assert batches[-1] == ("bm7_d15505_b7_v1", "failed", 2, 0)


def test_fetch_recent_history_prefers_live_rows_over_archive_rows_with_same_timestamp(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.61,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            }
        ],
    )

    rows = fetch_recent_history(database_path, device_id="bm200_house", limit=10)

    assert len(rows) == 1
    assert rows[0]["sample_source"] == "live"
    assert rows[0]["voltage"] == 12.73
    assert rows[0]["soc"] == 58


def test_fetch_recent_history_since_reads_time_window_without_recent_count_limit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-01T00:00:00+00:00"))
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00", soc=59))
    persist_snapshot(database_path, _snapshot("2024-01-03T00:00:00+00:00", soc=60))
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-03T00:00:00+00:00",
                "voltage": 12.61,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            }
        ],
    )

    rows = fetch_recent_history_since(
        database_path,
        device_id="bm200_house",
        since_ts="2024-01-02T00:00:00+00:00",
    )

    assert [row["ts"] for row in rows] == [
        "2024-01-03T00:00:00+00:00",
        "2024-01-02T00:00:00+00:00",
    ]
    assert rows[0]["sample_source"] == "live"
    assert rows[0]["soc"] == 60


def test_history_window_uses_chronological_order_across_dst_offset_change(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    before_fallback = "2025-10-26T02:30:00+02:00"
    after_fallback = "2025-10-26T02:00:00+01:00"
    persist_snapshot(database_path, _snapshot(before_fallback, voltage=12.61))
    persist_snapshot(database_path, _snapshot(after_fallback, voltage=12.72))

    assert fetch_history_bounds(database_path, device_id="bm200_house") == (
        before_fallback,
        after_fallback,
    )
    rows = fetch_history_window(
        database_path,
        device_id="bm200_house",
        start_ts="2025-10-26T00:00:00+00:00",
        end_ts="2025-10-26T02:00:00+00:00",
    )

    assert [row["ts"] for row in rows] == [before_fallback, after_fallback]


def test_history_window_preserves_millisecond_boundaries_between_raw_pages(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    previous_page_end = "2026-07-11T12:00:00.000+00:00"
    next_page_start = "2026-07-11T12:00:00.001+00:00"
    persist_snapshot(database_path, _snapshot(previous_page_end, voltage=12.61))
    persist_snapshot(database_path, _snapshot(next_page_start, voltage=12.72))

    previous_page = fetch_history_window(
        database_path,
        device_id="bm200_house",
        start_ts="2026-07-11T00:00:00+00:00",
        end_ts=previous_page_end,
    )
    next_page = fetch_history_window(
        database_path,
        device_id="bm200_house",
        start_ts=next_page_start,
        end_ts="2026-07-11T23:59:59+00:00",
    )

    assert [row["ts"] for row in previous_page] == [previous_page_end]
    assert [row["ts"] for row in next_page] == [next_page_start]


def test_history_window_and_bounds_order_millisecond_samples_across_offsets(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gateway.db"
    first_sample = "2026-07-11T14:00:00.000+02:00"
    second_sample = "2026-07-11T12:00:00.001+00:00"
    persist_snapshot(database_path, _snapshot(second_sample, voltage=12.72))
    persist_snapshot(database_path, _snapshot(first_sample, voltage=12.61))

    assert fetch_history_bounds(database_path, device_id="bm200_house") == (
        first_sample,
        second_sample,
    )
    rows = fetch_history_window(
        database_path,
        device_id="bm200_house",
        start_ts="2026-07-11T12:00:00.000+00:00",
        end_ts=second_sample,
    )

    assert [row["ts"] for row in rows] == [first_sample, second_sample]


def test_fetch_daily_history_merges_archive_only_days(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00"))
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:00:00+00:00",
                "voltage": 12.61,
                "min_crank_voltage": 11.95,
                "event_type": 1,
            },
            {
                "ts": "2024-01-01T00:02:00+00:00",
                "voltage": 12.58,
                "min_crank_voltage": 11.92,
                "event_type": 1,
            },
        ],
    )

    rows = fetch_daily_history(database_path, device_id="bm200_house", limit=10)

    assert rows[0]["day"] == "2024-01-02"
    assert rows[0]["avg_soc"] == 58.0
    assert rows[1] == {
        "device_id": "bm200_house",
        "day": "2024-01-01",
        "samples": 2,
        "min_voltage": 12.58,
        "max_voltage": 12.61,
        "avg_voltage": 12.594999999999999,
        "avg_soc": None,
        "avg_temperature": None,
        "error_count": 0,
        "last_seen": "2024-01-01T00:02:00+00:00",
    }


def test_latest_history_timestamp_prefers_newest_live_or_archive_row(tmp_path: Path) -> None:
    database_path = tmp_path / "gateway.db"
    import_archive_history(
        database_path,
        device_id="bm200_house",
        device_type="bm200",
        name="BM200 House",
        mac="AA:BB:CC:DD:EE:01",
        adapter="hci0",
        driver="bm200",
        profile="legacy_bm2_history",
        readings=[
            {
                "ts": "2024-01-01T00:02:00+00:00",
                "voltage": 12.58,
                "min_crank_voltage": 11.92,
                "event_type": 1,
            }
        ],
    )
    persist_snapshot(database_path, _snapshot("2024-01-02T00:00:00+00:00"))

    latest = latest_history_timestamp(database_path, device_id="bm200_house")

    assert latest == "2024-01-02T00:00:00+00:00"
