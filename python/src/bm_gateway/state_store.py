"""Snapshot persistence for BMGateway."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, cast

from .models import GatewaySnapshot

ArchiveImportProgress = Callable[[int, int, str], None]

LIVE_SAMPLE_SOURCE = "live"
LIVE_SAMPLE_PROFILE = "live"
ARCHIVE_SAMPLE_SOURCE = "device_archive"
LIVE_SAMPLE_PRIORITY = 2
ARCHIVE_SAMPLE_PRIORITY = 1
LEGACY_HISTORY_MIGRATION_KEY = "legacy_history_imported_to_device_samples"
_REQUIRED_SCHEMA_TABLES = frozenset(
    {
        "gateway_snapshots",
        "device_readings",
        "device_daily_rollups",
        "device_archive_readings",
        "device_samples",
        "archive_import_batches",
        "state_store_metadata",
    }
)
_SCHEMA_READY_PATHS: set[Path] = set()


def write_snapshot(path: Path, snapshot: GatewaySnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def load_snapshot(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def fetch_latest_successful_seen(path: Path) -> dict[str, str]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT device_id, last_seen
            FROM device_samples
            WHERE connected = 1
              AND error_code IS NULL
              AND last_seen <> ''
              AND source = 'live'
            ORDER BY sample_ts DESC
            """
        ).fetchall()
    finally:
        connection.close()
    latest: dict[str, str] = {}
    for device_id, last_seen in rows:
        active_device_id = str(device_id)
        if active_device_id not in latest:
            latest[active_device_id] = str(last_seen)
    return latest


def _connect_database(path: Path, *, migrate_legacy: bool = True) -> sqlite3.Connection:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_key = path.resolve(strict=False)
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA busy_timeout = 30000")
    if migrate_legacy:
        connection.execute("PRAGMA journal_mode = WAL")
    if schema_key in _SCHEMA_READY_PATHS and _database_schema_is_ready(connection):
        if migrate_legacy:
            if _migrate_legacy_history_to_device_samples(connection):
                _rebuild_daily_rollups(connection)
            connection.commit()
        return connection
    _SCHEMA_READY_PATHS.discard(schema_key)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gateway_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT NOT NULL,
            gateway_name TEXT NOT NULL,
            active_adapter TEXT NOT NULL,
            mqtt_enabled INTEGER NOT NULL,
            mqtt_connected INTEGER NOT NULL,
            devices_total INTEGER NOT NULL,
            devices_online INTEGER NOT NULL,
            poll_interval_seconds INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS device_readings (
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
        CREATE TABLE IF NOT EXISTS device_daily_rollups (
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
        CREATE TABLE IF NOT EXISTS device_archive_readings (
            device_id TEXT NOT NULL,
            device_type TEXT NOT NULL,
            name TEXT NOT NULL,
            mac TEXT NOT NULL,
            ts TEXT NOT NULL,
            voltage REAL NOT NULL,
            min_crank_voltage REAL,
            event_type INTEGER,
            soc INTEGER,
            temperature REAL,
            raw_record TEXT,
            page_selector INTEGER,
            record_index INTEGER,
            timestamp_quality TEXT NOT NULL DEFAULT 'estimated',
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
        CREATE TABLE IF NOT EXISTS device_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            sample_ts TEXT NOT NULL,
            source TEXT NOT NULL,
            source_profile TEXT NOT NULL,
            source_priority INTEGER NOT NULL,
            device_type TEXT NOT NULL,
            name TEXT NOT NULL,
            mac TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            connected INTEGER NOT NULL,
            voltage REAL NOT NULL,
            soc INTEGER,
            temperature REAL,
            rssi INTEGER,
            state TEXT NOT NULL,
            error_code TEXT,
            error_detail TEXT,
            last_seen TEXT NOT NULL,
            min_crank_voltage REAL,
            event_type INTEGER,
            raw_record TEXT,
            page_selector INTEGER,
            record_index INTEGER,
            timestamp_quality TEXT NOT NULL DEFAULT 'observed',
            imported_at TEXT NOT NULL,
            adapter TEXT NOT NULL,
            driver TEXT NOT NULL,
            UNIQUE(device_id, sample_ts, source, source_profile)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            profile TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            fetched_count INTEGER NOT NULL,
            inserted_count INTEGER NOT NULL,
            replaced_profiles TEXT NOT NULL DEFAULT '[]',
            error TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state_store_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_readings_device_ts
        ON device_readings (device_id, snapshot_generated_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_archive_readings_device_ts
        ON device_archive_readings (device_id, ts DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_samples_device_ts
        ON device_samples (device_id, sample_ts DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_samples_device_epoch
        ON device_samples (device_id, unixepoch(sample_ts) DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_samples_device_source_ts
        ON device_samples (device_id, source, source_profile, sample_ts DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_import_batches_device_started
        ON archive_import_batches (device_id, started_at DESC)
        """
    )
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(device_daily_rollups)").fetchall()
    }
    for column_name, definition in (
        ("min_temperature", "REAL"),
        ("max_temperature", "REAL"),
        ("avg_temperature", "REAL"),
    ):
        if column_name not in existing_columns:
            connection.execute(
                f"ALTER TABLE device_daily_rollups ADD COLUMN {column_name} {definition}"
            )
    _ensure_nullable_daily_avg_soc(connection)
    existing_archive_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(device_archive_readings)").fetchall()
    }
    for column_name, definition in (
        ("soc", "INTEGER"),
        ("temperature", "REAL"),
        ("raw_record", "TEXT"),
        ("page_selector", "INTEGER"),
        ("record_index", "INTEGER"),
        ("timestamp_quality", "TEXT NOT NULL DEFAULT 'estimated'"),
    ):
        if column_name not in existing_archive_columns:
            connection.execute(
                f"ALTER TABLE device_archive_readings ADD COLUMN {column_name} {definition}"
            )
    if migrate_legacy and _migrate_legacy_history_to_device_samples(connection):
        _rebuild_daily_rollups(connection)
    connection.commit()
    _SCHEMA_READY_PATHS.add(schema_key)
    return connection


def _database_schema_is_ready(connection: sqlite3.Connection) -> bool:
    placeholders = ", ".join("?" for _ in _REQUIRED_SCHEMA_TABLES)
    rows = connection.execute(
        f"""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN ({placeholders})
        """,
        tuple(_REQUIRED_SCHEMA_TABLES),
    ).fetchall()
    return {str(row[0]) for row in rows} == _REQUIRED_SCHEMA_TABLES


def _ensure_nullable_daily_avg_soc(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(device_daily_rollups)").fetchall()
    if not any(row[1] == "avg_soc" and int(row[3]) == 1 for row in columns):
        return

    legacy_columns = {str(row[1]) for row in columns}
    connection.execute("ALTER TABLE device_daily_rollups RENAME TO device_daily_rollups_legacy")
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

    def legacy_column(name: str, fallback: str) -> str:
        return name if name in legacy_columns else fallback

    connection.execute(
        f"""
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
        )
        SELECT
            device_id,
            day,
            samples,
            min_voltage,
            max_voltage,
            avg_voltage,
            avg_soc,
            {legacy_column("min_temperature", "NULL")},
            {legacy_column("max_temperature", "NULL")},
            {legacy_column("avg_temperature", "NULL")},
            error_count,
            last_seen
        FROM device_daily_rollups_legacy
        """
    )
    connection.execute("DROP TABLE device_daily_rollups_legacy")


def _migrate_legacy_history_to_device_samples(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT value FROM state_store_metadata WHERE key = ?",
        (LEGACY_HISTORY_MIGRATION_KEY,),
    ).fetchone()
    if row is not None and row[0] == "1":
        return False

    changes_before = connection.total_changes
    connection.execute(
        """
        INSERT OR IGNORE INTO device_samples (
            device_id,
            sample_ts,
            source,
            source_profile,
            source_priority,
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
            min_crank_voltage,
            event_type,
            raw_record,
            page_selector,
            record_index,
            timestamp_quality,
            imported_at,
            adapter,
            driver
        )
        SELECT
            device_id,
            snapshot_generated_at,
            'live',
            'live',
            2,
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
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            'observed',
            snapshot_generated_at,
            adapter,
            driver
        FROM device_readings
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO device_samples (
            device_id,
            sample_ts,
            source,
            source_profile,
            source_priority,
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
            min_crank_voltage,
            event_type,
            raw_record,
            page_selector,
            record_index,
            timestamp_quality,
            imported_at,
            adapter,
            driver
        )
        SELECT
            device_id,
            ts,
            'device_archive',
            profile,
            1,
            device_type,
            name,
            mac,
            1,
            1,
            voltage,
            soc,
            temperature,
            NULL,
            'archive',
            NULL,
            NULL,
            ts,
            min_crank_voltage,
            event_type,
            raw_record,
            page_selector,
            record_index,
            timestamp_quality,
            imported_at,
            adapter,
            driver
        FROM device_archive_readings
        """
    )
    migrated = connection.total_changes > changes_before
    connection.execute(
        """
        INSERT INTO state_store_metadata (key, value)
        VALUES (?, '1')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (LEGACY_HISTORY_MIGRATION_KEY,),
    )
    return migrated


def persist_snapshot(path: Path, snapshot: GatewaySnapshot) -> None:
    connection = _connect_database(path)
    try:
        connection.execute(
            """
            INSERT INTO gateway_snapshots (
                generated_at,
                gateway_name,
                active_adapter,
                mqtt_enabled,
                mqtt_connected,
                devices_total,
                devices_online,
                poll_interval_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.generated_at,
                snapshot.gateway_name,
                snapshot.active_adapter,
                int(snapshot.mqtt_enabled),
                int(snapshot.mqtt_connected),
                snapshot.devices_total,
                snapshot.devices_online,
                snapshot.poll_interval_seconds,
            ),
        )
        affected_device_days: set[tuple[str, str]] = set()
        for device in snapshot.devices:
            connection.execute(
                """
                INSERT OR IGNORE INTO device_samples (
                    device_id,
                    sample_ts,
                    source,
                    source_profile,
                    source_priority,
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
                    min_crank_voltage,
                    event_type,
                    raw_record,
                    page_selector,
                    record_index,
                    timestamp_quality,
                    imported_at,
                    adapter,
                    driver
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    device.id,
                    snapshot.generated_at,
                    LIVE_SAMPLE_SOURCE,
                    LIVE_SAMPLE_PROFILE,
                    LIVE_SAMPLE_PRIORITY,
                    device.type,
                    device.name,
                    device.mac,
                    int(device.enabled),
                    int(device.connected),
                    device.voltage,
                    device.soc,
                    device.temperature,
                    device.rssi,
                    device.state,
                    device.error_code,
                    device.error_detail,
                    device.last_seen,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "observed",
                    snapshot.generated_at,
                    device.adapter,
                    device.driver,
                ),
            )
            sample_day = snapshot.generated_at[:10]
            if sample_day:
                affected_device_days.add((device.id, sample_day))
            last_seen_day = device.last_seen[:10]
            if last_seen_day:
                affected_device_days.add((device.id, last_seen_day))
        _rebuild_daily_rollups_for_device_days(connection, affected_device_days)
        connection.commit()
    finally:
        connection.close()


def rebuild_daily_rollups(path: Path) -> None:
    connection = _connect_database(path)
    try:
        _rebuild_daily_rollups(connection)
        connection.commit()
    finally:
        connection.close()


def _rebuild_daily_rollups(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        WITH ranked_samples AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY device_id, sample_ts
                    ORDER BY source_priority DESC, imported_at DESC, id DESC
                ) AS row_rank
            FROM device_samples
        )
        SELECT
            device_id,
            substr(sample_ts, 1, 10) AS day,
            SUM(CASE WHEN error_code IS NULL AND voltage > 0 THEN 1 ELSE 0 END) AS samples,
            MIN(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END) AS min_voltage,
            MAX(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END) AS max_voltage,
            AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END) AS avg_voltage,
            AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN soc END) AS avg_soc,
            MIN(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                AS min_temperature,
            MAX(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                AS max_temperature,
            AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                AS avg_temperature,
            SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) AS error_count,
            MAX(last_seen) AS last_seen
        FROM ranked_samples
        WHERE row_rank = 1
        GROUP BY device_id, day
        ORDER BY device_id, day
        """
    ).fetchall()
    _insert_daily_rollup_rows(connection, rows)


def _daily_rollup_requires_retained_samples(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    day: str,
) -> bool:
    retained_rollup = connection.execute(
        """
        SELECT samples, error_count
        FROM device_daily_rollups
        WHERE device_id = ? AND day = ?
        """,
        (device_id, day),
    ).fetchone()
    if retained_rollup is None:
        return False
    raw_counts = connection.execute(
        """
        WITH ranked_samples AS (
            SELECT
                voltage,
                error_code,
                ROW_NUMBER() OVER (
                    PARTITION BY device_id, sample_ts
                    ORDER BY source_priority DESC, imported_at DESC, id DESC
                ) AS row_rank
            FROM device_samples
            WHERE device_id = ?
              AND substr(sample_ts, 1, 10) = ?
        )
        SELECT
            SUM(CASE WHEN error_code IS NULL AND voltage > 0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END)
        FROM ranked_samples
        WHERE row_rank = 1
        """,
        (device_id, day),
    ).fetchone()
    if raw_counts is None:
        return False
    retained_samples = int(retained_rollup[0] or 0)
    retained_errors = int(retained_rollup[1] or 0)
    raw_samples = int(raw_counts[0] or 0)
    raw_errors = int(raw_counts[1] or 0)
    return raw_samples < retained_samples or raw_errors < retained_errors


def _require_complete_daily_raw_history(
    connection: sqlite3.Connection,
    device_days: set[tuple[str, str]],
) -> None:
    protected_days = [
        f"{device_id}:{day}"
        for device_id, day in sorted(device_days)
        if _daily_rollup_requires_retained_samples(
            connection,
            device_id=device_id,
            day=day,
        )
    ]
    if protected_days:
        raise ValueError(
            "Cannot replace or delete archive history because retained daily history "
            f"cannot be rebuilt from raw samples for: {', '.join(protected_days)}"
        )


def _rebuild_daily_rollups_for_device_days(
    connection: sqlite3.Connection,
    device_days: set[tuple[str, str]],
    *,
    replace_retained_rollups: bool = False,
) -> None:
    """Rebuild selected daily rows from canonical samples.

    Callers may replace retained rollups only after checking that the pre-mutation
    raw rows completely cover every affected day.
    """
    for device_id, day in sorted(device_days):
        if not replace_retained_rollups and _daily_rollup_requires_retained_samples(
            connection,
            device_id=device_id,
            day=day,
        ):
            # Raw retention has already removed part of this day. Its rollup is
            # the only complete aggregate, so replacing it would lose history.
            continue
        connection.execute(
            "DELETE FROM device_daily_rollups WHERE device_id = ? AND day = ?",
            (device_id, day),
        )
        rows = connection.execute(
            """
            WITH ranked_samples AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY device_id, sample_ts
                        ORDER BY source_priority DESC, imported_at DESC, id DESC
                    ) AS row_rank
                FROM device_samples
                WHERE device_id = ?
                  AND substr(sample_ts, 1, 10) = ?
            )
            SELECT
                device_id,
                substr(sample_ts, 1, 10) AS day,
                SUM(CASE WHEN error_code IS NULL AND voltage > 0 THEN 1 ELSE 0 END)
                    AS samples,
                MIN(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END)
                    AS min_voltage,
                MAX(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END)
                    AS max_voltage,
                AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END)
                    AS avg_voltage,
                AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN soc END) AS avg_soc,
                MIN(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                    AS min_temperature,
                MAX(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                    AS max_temperature,
                AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                    AS avg_temperature,
                SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) AS error_count,
                MAX(last_seen) AS last_seen
            FROM ranked_samples
            WHERE row_rank = 1
            GROUP BY device_id, day
            """,
            (device_id, day),
        ).fetchall()
        _insert_daily_rollup_rows(connection, rows)


def _insert_daily_rollup_rows(
    connection: sqlite3.Connection,
    rows: list[tuple[Any, ...]],
) -> None:
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
            min_temperature,
            max_temperature,
            avg_temperature,
            error_count,
            last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, day) DO UPDATE SET
            samples = excluded.samples,
            min_voltage = excluded.min_voltage,
            max_voltage = excluded.max_voltage,
            avg_voltage = excluded.avg_voltage,
            avg_soc = excluded.avg_soc,
            min_temperature = excluded.min_temperature,
            max_temperature = excluded.max_temperature,
            avg_temperature = excluded.avg_temperature,
            error_count = excluded.error_count,
            last_seen = excluded.last_seen
        """,
        [
            (
                row[0],
                row[1],
                int(row[2] or 0),
                float(row[3] or 0.0),
                float(row[4] or 0.0),
                float(row[5] or 0.0),
                float(row[6]) if row[6] is not None else None,
                float(row[7]) if row[7] is not None else None,
                float(row[8]) if row[8] is not None else None,
                float(row[9]) if row[9] is not None else None,
                int(row[10] or 0),
                row[11],
            )
            for row in rows
        ],
    )


def _device_days_from_readings(
    *,
    device_id: str,
    readings: list[dict[str, object]],
) -> set[tuple[str, str]]:
    return {
        (device_id, str(reading["ts"])[:10])
        for reading in readings
        if str(reading.get("ts", ""))[:10]
    }


def _device_days_for_archive_profiles(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    profiles: tuple[str, ...],
) -> set[tuple[str, str]]:
    if not profiles:
        return set()
    placeholders = ", ".join("?" for _ in profiles)
    rows = connection.execute(
        f"""
        SELECT DISTINCT substr(sample_ts, 1, 10)
        FROM device_samples
        WHERE device_id = ?
          AND source = 'device_archive'
          AND source_profile IN ({placeholders})
        """,
        (device_id, *profiles),
    ).fetchall()
    return {(device_id, str(row[0])) for row in rows if row[0]}


def _cutoff_iso(days: int) -> str:
    return (datetime.now(tz=timezone.utc).astimezone() - timedelta(days=days)).isoformat(
        timespec="seconds"
    )


def prune_history(path: Path, *, raw_retention_days: int, daily_retention_days: int) -> None:
    connection = _connect_database(path)
    try:
        # Finalize daily summaries while the canonical raw rows still exist.
        # Thereafter daily retention, rather than raw retention, controls their lifetime.
        _rebuild_daily_rollups(connection)
        raw_cutoff = _cutoff_iso(raw_retention_days)
        connection.execute(
            "DELETE FROM device_readings WHERE snapshot_generated_at < ?",
            (raw_cutoff,),
        )
        connection.execute(
            "DELETE FROM gateway_snapshots WHERE generated_at < ?",
            (raw_cutoff,),
        )
        connection.execute(
            "DELETE FROM device_archive_readings WHERE ts < ?",
            (raw_cutoff,),
        )
        connection.execute(
            "DELETE FROM device_samples WHERE sample_ts < ?",
            (raw_cutoff,),
        )
        if daily_retention_days > 0:
            daily_cutoff = _cutoff_iso(daily_retention_days)[:10]
            connection.execute(
                "DELETE FROM device_daily_rollups WHERE day < ?",
                (daily_cutoff,),
            )
        connection.commit()
    finally:
        connection.close()


def fetch_counts(path: Path) -> dict[str, int]:
    connection = _connect_database(path)
    try:
        gateway_count = connection.execute("SELECT COUNT(*) FROM gateway_snapshots").fetchone()
        sample_count = connection.execute("SELECT COUNT(*) FROM device_samples").fetchone()
        device_count = connection.execute("SELECT COUNT(*) FROM device_readings").fetchone()
        daily_count = connection.execute("SELECT COUNT(*) FROM device_daily_rollups").fetchone()
        archive_count = connection.execute(
            "SELECT COUNT(*) FROM device_archive_readings"
        ).fetchone()
        import_batch_count = connection.execute(
            "SELECT COUNT(*) FROM archive_import_batches"
        ).fetchone()
    finally:
        connection.close()
    return {
        "gateway_snapshots": int(gateway_count[0]) if gateway_count is not None else 0,
        "device_samples": int(sample_count[0]) if sample_count is not None else 0,
        "device_readings": int(device_count[0]) if device_count is not None else 0,
        "device_daily_rollups": int(daily_count[0]) if daily_count is not None else 0,
        "device_archive_readings": int(archive_count[0]) if archive_count is not None else 0,
        "archive_import_batches": int(import_batch_count[0])
        if import_batch_count is not None
        else 0,
    }


def fetch_storage_summary(path: Path) -> dict[str, object]:
    connection = _connect_database(path)
    try:
        raw_rows = connection.execute(
            """
            SELECT
                device_id,
                COUNT(*) AS raw_samples,
                MIN(sample_ts) AS raw_first_ts,
                MAX(sample_ts) AS raw_last_ts
            FROM device_samples
            WHERE source = 'live'
            GROUP BY device_id
            ORDER BY device_id
            """
        ).fetchall()
        daily_rows = connection.execute(
            """
            SELECT
                device_id,
                COUNT(*) AS daily_days,
                MIN(day) AS daily_first_day,
                MAX(day) AS daily_last_day
            FROM device_daily_rollups
            GROUP BY device_id
            ORDER BY device_id
            """
        ).fetchall()
        archive_rows = connection.execute(
            """
            SELECT
                device_id,
                COUNT(*) AS archive_samples,
                MIN(sample_ts) AS archive_first_ts,
                MAX(sample_ts) AS archive_last_ts
            FROM device_samples
            WHERE source = 'device_archive'
            GROUP BY device_id
            ORDER BY device_id
            """
        ).fetchall()
    finally:
        connection.close()

    by_device: dict[str, dict[str, object]] = {}
    for row in raw_rows:
        device_id = cast(str, row[0])
        by_device[device_id] = {
            "device_id": device_id,
            "raw_samples": int(row[1]),
            "raw_first_ts": row[2],
            "raw_last_ts": row[3],
            "daily_days": 0,
            "daily_first_day": None,
            "daily_last_day": None,
            "archive_samples": 0,
            "archive_first_ts": None,
            "archive_last_ts": None,
        }
    for row in daily_rows:
        device_id = cast(str, row[0])
        summary = by_device.setdefault(
            device_id,
            {
                "device_id": device_id,
                "raw_samples": 0,
                "raw_first_ts": None,
                "raw_last_ts": None,
                "daily_days": 0,
                "daily_first_day": None,
                "daily_last_day": None,
                "archive_samples": 0,
                "archive_first_ts": None,
                "archive_last_ts": None,
            },
        )
        summary["daily_days"] = int(row[1])
        summary["daily_first_day"] = row[2]
        summary["daily_last_day"] = row[3]
    for row in archive_rows:
        device_id = cast(str, row[0])
        summary = by_device.setdefault(
            device_id,
            {
                "device_id": device_id,
                "raw_samples": 0,
                "raw_first_ts": None,
                "raw_last_ts": None,
                "daily_days": 0,
                "daily_first_day": None,
                "daily_last_day": None,
                "archive_samples": 0,
                "archive_first_ts": None,
                "archive_last_ts": None,
            },
        )
        summary["archive_samples"] = int(row[1])
        summary["archive_first_ts"] = row[2]
        summary["archive_last_ts"] = row[3]

    return {
        "counts": fetch_counts(path),
        "devices": [by_device[device_id] for device_id in sorted(by_device)],
    }


def history_device_id_exists(path: Path, device_id: str) -> bool:
    connection = _connect_database(path)
    try:
        for table_name in (
            "device_samples",
            "device_readings",
            "device_daily_rollups",
            "device_archive_readings",
        ):
            row = connection.execute(
                f"SELECT 1 FROM {table_name} WHERE device_id = ? LIMIT 1",
                (device_id,),
            ).fetchone()
            if row is not None:
                return True
    finally:
        connection.close()
    return False


def rename_history_device_id(
    path: Path,
    *,
    old_device_id: str,
    new_device_id: str,
    device_type: str | None = None,
    name: str | None = None,
    mac: str | None = None,
) -> None:
    metadata_supplied = device_type is not None or name is not None or mac is not None
    if old_device_id == new_device_id and not metadata_supplied:
        return

    connection = _connect_database(path)
    try:
        with connection:
            if old_device_id != new_device_id:
                for table_name in (
                    "device_samples",
                    "device_readings",
                    "device_daily_rollups",
                    "device_archive_readings",
                ):
                    connection.execute(
                        f"UPDATE {table_name} SET device_id = ? WHERE device_id = ?",
                        (new_device_id, old_device_id),
                    )
            if metadata_supplied:
                metadata_assignments: list[str] = []
                metadata_values: list[str] = []
                if device_type is not None:
                    metadata_assignments.append("device_type = ?")
                    metadata_values.append(device_type)
                if name is not None:
                    metadata_assignments.append("name = ?")
                    metadata_values.append(name)
                if mac is not None:
                    metadata_assignments.append("mac = ?")
                    metadata_values.append(mac)
                metadata_clause = ", ".join(metadata_assignments)
                for table_name in ("device_samples", "device_readings", "device_archive_readings"):
                    connection.execute(
                        f"UPDATE {table_name} SET {metadata_clause} WHERE device_id = ?",
                        (*metadata_values, new_device_id),
                    )
            _rebuild_daily_rollups(connection)
    finally:
        connection.close()


def fetch_recent_history(
    path: Path,
    *,
    device_id: str,
    limit: int = 200,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        buffered_limit = max(limit * 4, limit + 64)
        sample_rows = cast(
            list[tuple[Any, ...]],
            connection.execute(
                """
                SELECT
                    sample_ts AS ts,
                    voltage,
                    soc,
                    temperature,
                    state,
                    error_code,
                    error_detail,
                    source AS sample_source,
                    source_priority
                FROM device_samples
                WHERE device_id = ?
                ORDER BY sample_ts DESC, source_priority DESC
                LIMIT ?
                """,
                (device_id, buffered_limit),
            ).fetchall(),
        )
    finally:
        connection.close()
    rows = sorted(
        _dedupe_sample_history_rows(sample_rows),
        key=lambda item: str(item[0]),
        reverse=True,
    )[:limit]
    return _sample_history_dicts(rows)


def fetch_recent_history_since(
    path: Path,
    *,
    device_id: str,
    since_ts: str,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        sample_rows = cast(
            list[tuple[Any, ...]],
            connection.execute(
                """
                SELECT
                    sample_ts AS ts,
                    voltage,
                    soc,
                    temperature,
                    state,
                    error_code,
                    error_detail,
                    source AS sample_source,
                    source_priority
                FROM device_samples
                WHERE device_id = ?
                  AND sample_ts >= ?
                ORDER BY sample_ts DESC, source_priority DESC
                """,
                (device_id, since_ts),
            ).fetchall(),
        )
    finally:
        connection.close()
    rows = sorted(
        _dedupe_sample_history_rows(sample_rows),
        key=lambda item: str(item[0]),
        reverse=True,
    )
    return _sample_history_dicts(rows)


def fetch_history_window(
    path: Path,
    *,
    device_id: str,
    start_ts: str,
    end_ts: str,
) -> list[dict[str, object]]:
    """Return canonical raw samples for one inclusive history window."""
    connection = _connect_database(path)
    try:
        sample_rows = cast(
            list[tuple[Any, ...]],
            connection.execute(
                """
                SELECT
                    sample_ts AS ts,
                    voltage,
                    soc,
                    temperature,
                    state,
                    error_code,
                    error_detail,
                    source AS sample_source,
                    source_priority
                FROM device_samples
                WHERE device_id = ?
                  AND julianday(sample_ts) >= julianday(?)
                  AND julianday(sample_ts) <= julianday(?)
                ORDER BY unixepoch(sample_ts) ASC, source_priority DESC
                """,
                (device_id, start_ts, end_ts),
            ).fetchall(),
        )
    finally:
        connection.close()
    rows = _dedupe_sample_history_rows(sample_rows)
    return _sample_history_dicts(rows)


def fetch_history_day_sample_counts(
    path: Path,
    *,
    device_id: str,
    start_day: str,
    end_day: str,
) -> dict[str, int]:
    """Return canonical valid raw-sample counts for complete calendar days."""
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            WITH ranked_samples AS (
                SELECT
                    sample_ts,
                    voltage,
                    error_code,
                    ROW_NUMBER() OVER (
                        PARTITION BY device_id, sample_ts
                        ORDER BY source_priority DESC, imported_at DESC, id DESC
                    ) AS row_rank
                FROM device_samples
                WHERE device_id = ?
                  AND substr(sample_ts, 1, 10) >= ?
                  AND substr(sample_ts, 1, 10) <= ?
            )
            SELECT substr(sample_ts, 1, 10) AS day, COUNT(*)
            FROM ranked_samples
            WHERE row_rank = 1
              AND error_code IS NULL
              AND voltage > 0
            GROUP BY day
            """,
            (device_id, start_day, end_day),
        ).fetchall()
    finally:
        connection.close()
    return {str(day): int(count) for day, count in rows}


def fetch_history_bounds(path: Path, *, device_id: str) -> tuple[str, str] | None:
    """Return the first and latest valid canonical sample timestamps for a device."""
    connection = _connect_database(path)
    try:
        earliest_row = connection.execute(
            """
            SELECT sample_ts
            FROM device_samples
            WHERE device_id = ?
              AND error_code IS NULL
              AND voltage > 0
            ORDER BY unixepoch(sample_ts) ASC, source_priority DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        latest_row = connection.execute(
            """
            SELECT sample_ts
            FROM device_samples
            WHERE device_id = ?
              AND error_code IS NULL
              AND voltage > 0
            ORDER BY unixepoch(sample_ts) DESC, source_priority DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
    finally:
        connection.close()
    if earliest_row is None or latest_row is None:
        return None
    return (str(earliest_row[0]), str(latest_row[0]))


def fetch_daily_history_bounds(path: Path, *, device_id: str) -> tuple[str, str] | None:
    """Return calendar bounds for every valid day retained for chart history."""
    connection = _connect_database(path)
    try:
        row = connection.execute(
            """
            SELECT MIN(day), MAX(day)
            FROM (
                SELECT day
                FROM device_daily_rollups
                WHERE device_id = ?
                  AND samples > 0
                UNION
                SELECT substr(sample_ts, 1, 10) AS day
                FROM device_samples
                WHERE device_id = ?
                  AND error_code IS NULL
                  AND voltage > 0
            )
            """,
            (device_id, device_id),
        ).fetchone()
    finally:
        connection.close()
    if row is None or row[0] is None or row[1] is None:
        return None
    return (f"{row[0]}T00:00:00", f"{row[1]}T23:59:59")


def _dedupe_sample_history_rows(
    sample_rows: list[tuple[Any, ...]],
) -> list[tuple[Any, ...]]:
    merged_by_ts: dict[str, tuple[Any, ...]] = {}
    for row in sample_rows:
        ts = str(row[0])
        existing = merged_by_ts.get(ts)
        row_priority = cast(int, row[8])
        existing_priority = cast(int, existing[8]) if existing is not None else None
        if existing is None or (existing_priority is not None and row_priority > existing_priority):
            merged_by_ts[ts] = row
    return list(merged_by_ts.values())


def _sample_history_dicts(rows: list[tuple[Any, ...]]) -> list[dict[str, object]]:
    return [
        {
            "ts": row[0],
            "voltage": row[1],
            "soc": row[2],
            "temperature": row[3],
            "state": row[4],
            "error_code": row[5],
            "error_detail": row[6],
            "sample_source": row[7],
        }
        for row in rows
    ]


def import_archive_history(
    path: Path,
    *,
    device_id: str,
    device_type: str,
    name: str,
    mac: str,
    adapter: str,
    driver: str,
    profile: str,
    readings: list[dict[str, object]],
    progress: ArchiveImportProgress | None = None,
) -> int:
    connection = _connect_database(path)
    batch_id: int | None = None
    affected_device_days = _device_days_from_readings(device_id=device_id, readings=readings)
    try:
        batch_id = _start_archive_import_batch(
            connection,
            device_id=device_id,
            profile=profile,
            readings_count=len(readings),
            replace_profiles=(),
        )
        connection.commit()
        inserted = _import_archive_history_rows(
            connection,
            device_id=device_id,
            device_type=device_type,
            name=name,
            mac=mac,
            adapter=adapter,
            driver=driver,
            profile=profile,
            readings=readings,
            progress=progress,
        )
        _rebuild_daily_rollups_for_device_days(connection, affected_device_days)
        _finish_archive_import_batch(connection, batch_id=batch_id, inserted_count=inserted)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        if batch_id is not None:
            _fail_archive_import_batch(connection, batch_id=batch_id, error=str(exc))
            connection.commit()
        raise
    finally:
        connection.close()
    return inserted


def replace_archive_history_profiles(
    path: Path,
    *,
    device_id: str,
    device_type: str,
    name: str,
    mac: str,
    adapter: str,
    driver: str,
    profile: str,
    replace_profiles: tuple[str, ...],
    readings: list[dict[str, object]],
    progress: ArchiveImportProgress | None = None,
) -> int:
    connection = _connect_database(path)
    batch_id: int | None = None
    try:
        affected_device_days = _device_days_from_readings(
            device_id=device_id,
            readings=readings,
        )
        if replace_profiles:
            affected_device_days.update(
                _device_days_for_archive_profiles(
                    connection,
                    device_id=device_id,
                    profiles=replace_profiles,
                )
            )
            _require_complete_daily_raw_history(connection, affected_device_days)
        batch_id = _start_archive_import_batch(
            connection,
            device_id=device_id,
            profile=profile,
            readings_count=len(readings),
            replace_profiles=replace_profiles,
        )
        connection.commit()
        if replace_profiles:
            placeholders = ", ".join("?" for _ in replace_profiles)
            connection.execute(
                f"""
                DELETE FROM device_archive_readings
                WHERE device_id = ? AND profile IN ({placeholders})
                """,
                (device_id, *replace_profiles),
            )
            connection.execute(
                f"""
                DELETE FROM device_samples
                WHERE device_id = ?
                  AND source = 'device_archive'
                  AND source_profile IN ({placeholders})
                """,
                (device_id, *replace_profiles),
            )
        inserted = _import_archive_history_rows(
            connection,
            device_id=device_id,
            device_type=device_type,
            name=name,
            mac=mac,
            adapter=adapter,
            driver=driver,
            profile=profile,
            readings=readings,
            progress=progress,
        )
        _rebuild_daily_rollups_for_device_days(
            connection,
            affected_device_days,
            replace_retained_rollups=True,
        )
        _finish_archive_import_batch(connection, batch_id=batch_id, inserted_count=inserted)
        connection.commit()
        return inserted
    except Exception as exc:
        connection.rollback()
        if batch_id is not None:
            _fail_archive_import_batch(connection, batch_id=batch_id, error=str(exc))
            connection.commit()
        raise
    finally:
        connection.close()


def _start_archive_import_batch(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    profile: str,
    readings_count: int,
    replace_profiles: tuple[str, ...],
) -> int:
    started_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO archive_import_batches (
            device_id,
            profile,
            source,
            status,
            started_at,
            completed_at,
            fetched_count,
            inserted_count,
            replaced_profiles,
            error
        ) VALUES (?, ?, ?, 'running', ?, NULL, ?, 0, ?, NULL)
        """,
        (
            device_id,
            profile,
            ARCHIVE_SAMPLE_SOURCE,
            started_at,
            readings_count,
            json.dumps(list(replace_profiles), sort_keys=True),
        ),
    )
    batch_id = cursor.lastrowid
    if batch_id is None:
        raise RuntimeError("archive import batch insert did not return an id")
    return int(batch_id)


def _finish_archive_import_batch(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    inserted_count: int,
) -> None:
    completed_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    connection.execute(
        """
        UPDATE archive_import_batches
        SET status = 'completed',
            completed_at = ?,
            inserted_count = ?,
            error = NULL
        WHERE id = ?
        """,
        (completed_at, inserted_count, batch_id),
    )


def _fail_archive_import_batch(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    error: str,
) -> None:
    completed_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    connection.execute(
        """
        UPDATE archive_import_batches
        SET status = 'failed',
            completed_at = ?,
            inserted_count = 0,
            error = ?
        WHERE id = ?
        """,
        (completed_at, error, batch_id),
    )


def _import_archive_history_rows(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    device_type: str,
    name: str,
    mac: str,
    adapter: str,
    driver: str,
    profile: str,
    readings: list[dict[str, object]],
    progress: ArchiveImportProgress | None,
) -> int:
    imported_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    inserted = 0
    total = len(readings)
    if progress is not None:
        progress(0, total, "Importing history records")
    for index, reading in enumerate(readings, start=1):
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO device_samples (
                device_id,
                sample_ts,
                source,
                source_profile,
                source_priority,
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
                min_crank_voltage,
                event_type,
                raw_record,
                page_selector,
                record_index,
                timestamp_quality,
                imported_at,
                adapter,
                driver
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, NULL, ?, NULL, NULL,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                device_id,
                reading["ts"],
                ARCHIVE_SAMPLE_SOURCE,
                profile,
                ARCHIVE_SAMPLE_PRIORITY,
                device_type,
                name,
                mac,
                reading["voltage"],
                reading.get("soc"),
                reading.get("temperature"),
                "archive",
                reading["ts"],
                reading.get("min_crank_voltage"),
                reading.get("event_type"),
                reading.get("raw_record"),
                reading.get("page_selector"),
                reading.get("record_index"),
                reading.get("timestamp_quality", "estimated"),
                imported_at,
                adapter,
                driver,
            ),
        )
        inserted += int(cursor.rowcount or 0)
        if progress is not None:
            progress(index, total, "Importing history records")
    return inserted


def delete_archive_history_profiles(
    path: Path,
    *,
    device_id: str,
    profiles: tuple[str, ...],
) -> int:
    if not profiles:
        return 0
    connection = _connect_database(path)
    try:
        placeholders = ", ".join("?" for _ in profiles)
        affected_device_days = _device_days_for_archive_profiles(
            connection,
            device_id=device_id,
            profiles=profiles,
        )
        _require_complete_daily_raw_history(connection, affected_device_days)
        connection.execute(
            f"""
            DELETE FROM device_archive_readings
            WHERE device_id = ? AND profile IN ({placeholders})
            """,
            (device_id, *profiles),
        )
        cursor = connection.execute(
            f"""
            DELETE FROM device_samples
            WHERE device_id = ?
              AND source = 'device_archive'
              AND source_profile IN ({placeholders})
            """,
            (device_id, *profiles),
        )
        _rebuild_daily_rollups_for_device_days(
            connection,
            affected_device_days,
            replace_retained_rollups=True,
        )
        connection.commit()
        return int(cursor.rowcount or 0)
    finally:
        connection.close()


def fetch_archive_history(
    path: Path,
    *,
    device_id: str,
    limit: int = 2000,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT
                sample_ts,
                voltage,
                min_crank_voltage,
                event_type,
                soc,
                temperature,
                raw_record,
                page_selector,
                record_index,
                timestamp_quality,
                imported_at,
                adapter,
                driver,
                source_profile
            FROM device_samples
            WHERE device_id = ?
              AND source = 'device_archive'
            ORDER BY sample_ts DESC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "ts": row[0],
            "voltage": row[1],
            "min_crank_voltage": row[2],
            "event_type": row[3],
            "soc": row[4],
            "temperature": row[5],
            "raw_record": row[6],
            "page_selector": row[7],
            "record_index": row[8],
            "timestamp_quality": row[9],
            "imported_at": row[10],
            "adapter": row[11],
            "driver": row[12],
            "profile": row[13],
            "sample_source": "device_archive",
        }
        for row in rows
    ]


def fetch_daily_history(path: Path, *, device_id: str, limit: int = 365) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT
                day,
                samples,
                min_voltage,
                max_voltage,
                avg_voltage,
                avg_soc,
                avg_temperature,
                error_count,
                last_seen
            FROM device_daily_rollups
            WHERE device_id = ?
            ORDER BY day DESC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "device_id": device_id,
            "day": row[0],
            "samples": row[1],
            "min_voltage": row[2],
            "max_voltage": row[3],
            "avg_voltage": row[4],
            "avg_soc": row[5],
            "avg_temperature": row[6],
            "error_count": row[7],
            "last_seen": row[8],
        }
        for row in rows
    ]


def fetch_daily_history_window(
    path: Path,
    *,
    device_id: str,
    start_day: str,
    end_day: str,
) -> list[dict[str, object]]:
    """Return one daily window, rebuilding only daily rows absent from retained rollups."""
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            WITH ranked_samples AS (
                SELECT
                    sample_ts,
                    voltage,
                    soc,
                    temperature,
                    error_code,
                    last_seen,
                    ROW_NUMBER() OVER (
                        PARTITION BY device_id, sample_ts
                        ORDER BY source_priority DESC, imported_at DESC, id DESC
                    ) AS row_rank
                FROM device_samples
                WHERE device_id = ?
                  AND substr(sample_ts, 1, 10) >= ?
                  AND substr(sample_ts, 1, 10) <= ?
            ),
            raw_daily AS (
                SELECT
                    substr(sample_ts, 1, 10) AS day,
                    SUM(CASE WHEN error_code IS NULL AND voltage > 0 THEN 1 ELSE 0 END)
                        AS samples,
                    MIN(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END)
                        AS min_voltage,
                    MAX(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END)
                        AS max_voltage,
                    AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END)
                        AS avg_voltage,
                    AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN soc END) AS avg_soc,
                    AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END)
                        AS avg_temperature,
                    SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) AS error_count,
                    MAX(last_seen) AS last_seen
                FROM ranked_samples
                WHERE row_rank = 1
                GROUP BY day
            ),
            retained_daily AS (
                SELECT
                    day,
                    samples,
                    min_voltage,
                    max_voltage,
                    avg_voltage,
                    avg_soc,
                    avg_temperature,
                    error_count,
                    last_seen
                FROM device_daily_rollups
                WHERE device_id = ?
                  AND day >= ?
                  AND day <= ?
            )
            SELECT
                day,
                samples,
                min_voltage,
                max_voltage,
                avg_voltage,
                avg_soc,
                avg_temperature,
                error_count,
                last_seen
            FROM retained_daily
            UNION ALL
            SELECT
                raw_daily.day,
                raw_daily.samples,
                raw_daily.min_voltage,
                raw_daily.max_voltage,
                raw_daily.avg_voltage,
                raw_daily.avg_soc,
                raw_daily.avg_temperature,
                raw_daily.error_count,
                raw_daily.last_seen
            FROM raw_daily
            WHERE NOT EXISTS (
                SELECT 1
                FROM retained_daily
                WHERE retained_daily.day = raw_daily.day
            )
            ORDER BY day ASC
            """,
            (device_id, start_day, end_day, device_id, start_day, end_day),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "device_id": device_id,
            "day": row[0],
            "samples": row[1],
            "min_voltage": row[2],
            "max_voltage": row[3],
            "avg_voltage": row[4],
            "avg_soc": row[5],
            "avg_temperature": row[6],
            "error_count": row[7],
            "last_seen": row[8],
        }
        for row in rows
    ]


def latest_history_timestamp(path: Path, *, device_id: str) -> str | None:
    connection = _connect_database(path)
    try:
        row = connection.execute(
            """
            SELECT MAX(sample_ts)
            FROM device_samples
            WHERE device_id = ?
              AND error_code IS NULL
              AND voltage > 0
            """,
            (device_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def latest_live_history_timestamp(path: Path, *, device_id: str) -> str | None:
    connection = _connect_database(path)
    try:
        row = connection.execute(
            """
            SELECT MAX(sample_ts)
            FROM device_samples
            WHERE device_id = ?
              AND error_code IS NULL
              AND voltage > 0
              AND source = 'live'
            """,
            (device_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def latest_archive_history_timestamp(
    path: Path,
    *,
    device_id: str,
    profile: str | None = None,
) -> str | None:
    connection = _connect_database(path)
    try:
        if profile is None:
            row = connection.execute(
                """
                SELECT MAX(sample_ts)
                FROM device_samples
                WHERE device_id = ?
                  AND source = 'device_archive'
                """,
                (device_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT MAX(sample_ts)
                FROM device_samples
                WHERE device_id = ?
                  AND source = 'device_archive'
                  AND source_profile = ?
                """,
                (device_id, profile),
            ).fetchone()
    finally:
        connection.close()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def fetch_monthly_history(
    path: Path,
    *,
    device_id: str,
    limit: int = 24,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT
                substr(day, 1, 7) AS month,
                SUM(samples),
                MIN(min_voltage),
                MAX(max_voltage),
                COALESCE(SUM(avg_voltage * samples) / NULLIF(SUM(samples), 0), 0.0),
                CASE
                    WHEN SUM(CASE WHEN avg_soc IS NOT NULL THEN samples ELSE 0 END) = 0
                    THEN NULL
                    ELSE SUM(avg_soc * samples)
                        / SUM(CASE WHEN avg_soc IS NOT NULL THEN samples ELSE 0 END)
                END,
                CASE
                    WHEN SUM(CASE WHEN avg_temperature IS NOT NULL THEN samples ELSE 0 END) = 0
                    THEN NULL
                    ELSE SUM(avg_temperature * samples)
                        / SUM(CASE WHEN avg_temperature IS NOT NULL THEN samples ELSE 0 END)
                END,
                SUM(error_count),
                MAX(last_seen)
            FROM device_daily_rollups
            WHERE device_id = ?
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "device_id": device_id,
            "month": row[0],
            "samples": row[1],
            "min_voltage": row[2],
            "max_voltage": row[3],
            "avg_voltage": row[4],
            "avg_soc": row[5],
            "avg_temperature": row[6],
            "error_count": row[7],
            "last_seen": row[8],
        }
        for row in rows
    ]


def fetch_yearly_history(
    path: Path,
    *,
    device_id: str,
    limit: int = 10,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT
                substr(day, 1, 4) AS year,
                SUM(samples),
                MIN(min_voltage),
                MAX(max_voltage),
                COALESCE(SUM(avg_voltage * samples) / NULLIF(SUM(samples), 0), 0.0),
                CASE
                    WHEN SUM(CASE WHEN avg_soc IS NOT NULL THEN samples ELSE 0 END) = 0
                    THEN NULL
                    ELSE SUM(avg_soc * samples)
                        / SUM(CASE WHEN avg_soc IS NOT NULL THEN samples ELSE 0 END)
                END,
                CASE
                    WHEN SUM(CASE WHEN avg_temperature IS NOT NULL THEN samples ELSE 0 END) = 0
                    THEN NULL
                    ELSE SUM(avg_temperature * samples)
                        / SUM(CASE WHEN avg_temperature IS NOT NULL THEN samples ELSE 0 END)
                END,
                SUM(error_count),
                MAX(last_seen)
            FROM device_daily_rollups
            WHERE device_id = ?
            GROUP BY year
            ORDER BY year DESC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "device_id": device_id,
            "year": row[0],
            "samples": row[1],
            "min_voltage": row[2],
            "max_voltage": row[3],
            "avg_voltage": row[4],
            "avg_soc": row[5],
            "avg_temperature": row[6],
            "error_count": row[7],
            "last_seen": row[8],
        }
        for row in rows
    ]


def _load_daily_rows_for_analytics(
    path: Path, *, device_id: str
) -> list[tuple[date, float, float | None, int, int]]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT day, avg_voltage, avg_soc, error_count, samples
            FROM device_daily_rollups
            WHERE device_id = ?
            ORDER BY day ASC
            """,
            (device_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        (
            date.fromisoformat(cast(str, row[0])),
            float(row[1]),
            float(row[2]) if row[2] is not None else None,
            int(row[3]),
            int(row[4]),
        )
        for row in rows
    ]


def _weighted_average(
    rows: list[tuple[date, float, float | None, int, int]],
    value_index: int,
) -> float | None:
    if value_index == 1:
        values = [(row[1], row[4]) for row in rows]
    elif value_index == 2:
        values = [(row[2], row[4]) for row in rows if row[2] is not None]
    else:
        raise ValueError(f"unsupported weighted average index: {value_index}")
    total_samples = sum(samples for _value, samples in values)
    if total_samples <= 0:
        return None
    weighted_sum = sum(value * samples for value, samples in values)
    return round(weighted_sum / total_samples, 2)


def fetch_degradation_report(path: Path, *, device_id: str) -> dict[str, object]:
    rows = _load_daily_rows_for_analytics(path, device_id=device_id)
    if not rows:
        return {
            "device_id": device_id,
            "latest_day": None,
            "windows": [],
        }

    latest_day = rows[-1][0]
    windows: list[dict[str, object]] = []
    durations = (30, 90, 180, 365, 730)
    for days in durations:
        current_start = latest_day - timedelta(days=days - 1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)

        current_rows = [row for row in rows if current_start <= row[0] <= latest_day]
        previous_rows = [row for row in rows if previous_start <= row[0] <= previous_end]
        if not current_rows:
            continue

        current_avg_voltage = _weighted_average(current_rows, 1)
        current_avg_soc = _weighted_average(current_rows, 2)
        previous_avg_voltage = _weighted_average(previous_rows, 1) if previous_rows else None
        previous_avg_soc = _weighted_average(previous_rows, 2) if previous_rows else None
        if current_avg_voltage is None or current_avg_soc is None:
            continue
        windows.append(
            {
                "days": days,
                "current_start_day": current_rows[0][0].isoformat(),
                "current_end_day": current_rows[-1][0].isoformat(),
                "current_days": len(current_rows),
                "current_avg_voltage": current_avg_voltage,
                "current_avg_soc": current_avg_soc,
                "current_error_count": sum(row[3] for row in current_rows),
                "current_samples": sum(row[4] for row in current_rows),
                "previous_start_day": previous_rows[0][0].isoformat() if previous_rows else None,
                "previous_end_day": previous_rows[-1][0].isoformat() if previous_rows else None,
                "previous_days": len(previous_rows),
                "previous_avg_voltage": previous_avg_voltage,
                "previous_avg_soc": previous_avg_soc,
                "previous_error_count": sum(row[3] for row in previous_rows),
                "previous_samples": sum(row[4] for row in previous_rows),
                "delta_avg_voltage": (
                    round(current_avg_voltage - previous_avg_voltage, 2)
                    if previous_avg_voltage is not None
                    else None
                ),
                "delta_avg_soc": (
                    round(current_avg_soc - previous_avg_soc, 2)
                    if previous_avg_soc is not None
                    else None
                ),
            }
        )

    return {
        "device_id": device_id,
        "latest_day": latest_day.isoformat(),
        "windows": windows,
    }
