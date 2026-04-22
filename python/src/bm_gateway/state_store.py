"""Snapshot persistence for BMGateway."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from .models import GatewaySnapshot


def write_snapshot(path: Path, snapshot: GatewaySnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def load_snapshot(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
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
            avg_soc REAL NOT NULL,
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
            imported_at TEXT NOT NULL,
            adapter TEXT NOT NULL,
            driver TEXT NOT NULL,
            profile TEXT NOT NULL,
            PRIMARY KEY (device_id, ts, profile)
        )
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
    connection.commit()
    return connection


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
        for device in snapshot.devices:
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
                    snapshot.generated_at,
                    device.id,
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
                    device.adapter,
                    device.driver,
                ),
            )
            day = device.last_seen[:10]
            if device.error_code is None and device.voltage > 0:
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
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(device_id, day) DO UPDATE SET
                        samples = samples + 1,
                        min_voltage = CASE
                            WHEN samples = 0 THEN excluded.min_voltage
                            ELSE MIN(min_voltage, excluded.min_voltage)
                        END,
                        max_voltage = CASE
                            WHEN samples = 0 THEN excluded.max_voltage
                            ELSE MAX(max_voltage, excluded.max_voltage)
                        END,
                        avg_voltage = CASE
                            WHEN samples = 0 THEN excluded.avg_voltage
                            ELSE ((avg_voltage * samples) + excluded.avg_voltage) / (samples + 1)
                        END,
                        avg_soc = CASE
                            WHEN samples = 0 THEN excluded.avg_soc
                            ELSE ((avg_soc * samples) + excluded.avg_soc) / (samples + 1)
                        END,
                        min_temperature = CASE
                            WHEN excluded.min_temperature IS NULL THEN min_temperature
                            WHEN min_temperature IS NULL THEN excluded.min_temperature
                            ELSE MIN(min_temperature, excluded.min_temperature)
                        END,
                        max_temperature = CASE
                            WHEN excluded.max_temperature IS NULL THEN max_temperature
                            WHEN max_temperature IS NULL THEN excluded.max_temperature
                            ELSE MAX(max_temperature, excluded.max_temperature)
                        END,
                        avg_temperature = CASE
                            WHEN excluded.avg_temperature IS NULL THEN avg_temperature
                            WHEN avg_temperature IS NULL THEN excluded.avg_temperature
                            ELSE (
                                (avg_temperature * samples) + excluded.avg_temperature
                            ) / (samples + 1)
                        END,
                        last_seen = excluded.last_seen
                    """,
                    (
                        device.id,
                        day,
                        device.voltage,
                        device.voltage,
                        device.voltage,
                        float(device.soc),
                        device.temperature,
                        device.temperature,
                        device.temperature,
                        device.last_seen,
                    ),
                )
            else:
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
                    ) VALUES (?, ?, 0, 0.0, 0.0, 0.0, 0.0, NULL, NULL, NULL, 1, ?)
                    ON CONFLICT(device_id, day) DO UPDATE SET
                        error_count = error_count + 1,
                        last_seen = excluded.last_seen
                    """,
                    (
                        device.id,
                        day,
                        device.last_seen,
                    ),
                )
        connection.commit()
    finally:
        connection.close()


def rebuild_daily_rollups(path: Path) -> None:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT
                device_id,
                substr(last_seen, 1, 10) AS day,
                SUM(CASE WHEN error_code IS NULL AND voltage > 0 THEN 1 ELSE 0 END) AS samples,
                MIN(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END) AS min_voltage,
                MAX(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END) AS max_voltage,
                AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN voltage END) AS avg_voltage,
                AVG(CASE WHEN error_code IS NULL AND voltage > 0 THEN soc END) AS avg_soc,
                MIN(
                    CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END
                ) AS min_temperature,
                MAX(
                    CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END
                ) AS max_temperature,
                AVG(
                    CASE WHEN error_code IS NULL AND voltage > 0 THEN temperature END
                ) AS avg_temperature,
                SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) AS error_count,
                MAX(last_seen) AS last_seen
            FROM device_readings
            GROUP BY device_id, day
            ORDER BY device_id, day
            """
        ).fetchall()
        connection.execute("DELETE FROM device_daily_rollups")
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
            """,
            [
                (
                    row[0],
                    row[1],
                    int(row[2] or 0),
                    float(row[3] or 0.0),
                    float(row[4] or 0.0),
                    float(row[5] or 0.0),
                    float(row[6] or 0.0),
                    float(row[7]) if row[7] is not None else None,
                    float(row[8]) if row[8] is not None else None,
                    float(row[9]) if row[9] is not None else None,
                    int(row[10] or 0),
                    row[11],
                )
                for row in rows
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _cutoff_iso(days: int) -> str:
    return (datetime.now(tz=timezone.utc).astimezone() - timedelta(days=days)).isoformat(
        timespec="seconds"
    )


def prune_history(path: Path, *, raw_retention_days: int, daily_retention_days: int) -> None:
    connection = _connect_database(path)
    try:
        raw_cutoff = _cutoff_iso(raw_retention_days)
        connection.execute(
            "DELETE FROM device_readings WHERE snapshot_generated_at < ?",
            (raw_cutoff,),
        )
        connection.execute(
            "DELETE FROM gateway_snapshots WHERE generated_at < ?",
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
        device_count = connection.execute("SELECT COUNT(*) FROM device_readings").fetchone()
        daily_count = connection.execute("SELECT COUNT(*) FROM device_daily_rollups").fetchone()
        archive_count = connection.execute(
            "SELECT COUNT(*) FROM device_archive_readings"
        ).fetchone()
    finally:
        connection.close()
    return {
        "gateway_snapshots": int(gateway_count[0]) if gateway_count is not None else 0,
        "device_readings": int(device_count[0]) if device_count is not None else 0,
        "device_daily_rollups": int(daily_count[0]) if daily_count is not None else 0,
        "device_archive_readings": int(archive_count[0]) if archive_count is not None else 0,
    }


def fetch_storage_summary(path: Path) -> dict[str, object]:
    connection = _connect_database(path)
    try:
        raw_rows = connection.execute(
            """
            SELECT
                device_id,
                COUNT(*) AS raw_samples,
                MIN(snapshot_generated_at) AS raw_first_ts,
                MAX(snapshot_generated_at) AS raw_last_ts
            FROM device_readings
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
                MIN(ts) AS archive_first_ts,
                MAX(ts) AS archive_last_ts
            FROM device_archive_readings
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


def fetch_recent_history(
    path: Path,
    *,
    device_id: str,
    limit: int = 200,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        buffered_limit = max(limit * 4, limit + 64)
        live_rows = connection.execute(
            """
            SELECT
                snapshot_generated_at AS ts,
                voltage,
                soc,
                temperature,
                state,
                error_code,
                error_detail,
                'live' AS sample_source,
                2 AS source_priority
            FROM device_readings
            WHERE device_id = ?
            ORDER BY snapshot_generated_at DESC
            LIMIT ?
            """,
            (device_id, buffered_limit),
        ).fetchall()
        archive_rows = connection.execute(
            """
            SELECT
                ts,
                voltage,
                NULL AS soc,
                NULL AS temperature,
                'archive' AS state,
                NULL AS error_code,
                NULL AS error_detail,
                'device_archive' AS sample_source,
                1 AS source_priority
            FROM device_archive_readings
            WHERE device_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (device_id, buffered_limit),
        ).fetchall()
    finally:
        connection.close()
    merged_by_ts: dict[str, tuple[object, ...]] = {}
    for row in [*live_rows, *archive_rows]:
        ts = str(row[0])
        existing = merged_by_ts.get(ts)
        row_priority = cast(int, row[8])
        existing_priority = cast(int, existing[8]) if existing is not None else None
        if existing is None or (existing_priority is not None and row_priority > existing_priority):
            merged_by_ts[ts] = row
    rows = sorted(merged_by_ts.values(), key=lambda item: str(item[0]), reverse=True)[:limit]
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
) -> int:
    connection = _connect_database(path)
    imported_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    inserted = 0
    try:
        for reading in readings:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO device_archive_readings (
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
                    device_id,
                    device_type,
                    name,
                    mac,
                    reading["ts"],
                    reading["voltage"],
                    reading.get("min_crank_voltage"),
                    reading.get("event_type"),
                    imported_at,
                    adapter,
                    driver,
                    profile,
                ),
            )
            inserted += int(cursor.rowcount or 0)
        connection.commit()
    finally:
        connection.close()
    return inserted


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
                ts,
                voltage,
                min_crank_voltage,
                event_type,
                imported_at,
                adapter,
                driver,
                profile
            FROM device_archive_readings
            WHERE device_id = ?
            ORDER BY ts DESC
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
            "imported_at": row[4],
            "adapter": row[5],
            "driver": row[6],
            "profile": row[7],
            "sample_source": "device_archive",
        }
        for row in rows
    ]


def fetch_daily_history(path: Path, *, device_id: str, limit: int = 365) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        live_rows = connection.execute(
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
        archive_rows = connection.execute(
            """
            SELECT
                substr(ts, 1, 10) AS day,
                COUNT(*) AS samples,
                MIN(voltage) AS min_voltage,
                MAX(voltage) AS max_voltage,
                AVG(voltage) AS avg_voltage,
                MAX(ts) AS last_seen
            FROM device_archive_readings
            WHERE device_id = ?
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (device_id, limit * 2),
        ).fetchall()
    finally:
        connection.close()
    rows_by_day = {
        str(row[0]): {
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
        for row in live_rows
    }
    for row in archive_rows:
        day = str(row[0])
        if day in rows_by_day:
            continue
        rows_by_day[day] = {
            "device_id": device_id,
            "day": row[0],
            "samples": row[1],
            "min_voltage": row[2],
            "max_voltage": row[3],
            "avg_voltage": row[4],
            "avg_soc": None,
            "avg_temperature": None,
            "error_count": 0,
            "last_seen": row[5],
        }
    return sorted(rows_by_day.values(), key=lambda item: str(item["day"]), reverse=True)[:limit]


def latest_history_timestamp(path: Path, *, device_id: str) -> str | None:
    connection = _connect_database(path)
    try:
        row = connection.execute(
            """
            SELECT ts
            FROM (
                SELECT MAX(snapshot_generated_at) AS ts
                FROM device_readings
                WHERE device_id = ?
                  AND error_code IS NULL
                  AND voltage > 0
                UNION ALL
                SELECT MAX(ts) AS ts
                FROM device_archive_readings
                WHERE device_id = ?
            )
            WHERE ts IS NOT NULL
            ORDER BY ts DESC
            LIMIT 1
            """,
            (device_id, device_id),
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
                COALESCE(SUM(avg_soc * samples) / NULLIF(SUM(samples), 0), 0.0),
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
                COALESCE(SUM(avg_soc * samples) / NULLIF(SUM(samples), 0), 0.0),
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
) -> list[tuple[date, float, float, int, int]]:
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
            float(row[2]),
            int(row[3]),
            int(row[4]),
        )
        for row in rows
    ]


def _weighted_average(
    rows: list[tuple[date, float, float, int, int]],
    value_index: int,
) -> float | None:
    total_samples = sum(row[4] for row in rows)
    if total_samples <= 0:
        return None
    if value_index == 1:
        weighted_sum = sum(row[1] * row[4] for row in rows)
    elif value_index == 2:
        weighted_sum = sum(row[2] * row[4] for row in rows)
    else:
        raise ValueError(f"unsupported weighted average index: {value_index}")
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
