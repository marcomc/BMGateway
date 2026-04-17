"""Snapshot persistence for BMGateway."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
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
            error_count INTEGER NOT NULL,
            last_seen TEXT NOT NULL,
            PRIMARY KEY (device_id, day)
        )
        """
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
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, day) DO UPDATE SET
                    samples = samples + 1,
                    min_voltage = MIN(min_voltage, excluded.min_voltage),
                    max_voltage = MAX(max_voltage, excluded.max_voltage),
                    avg_voltage = ((avg_voltage * samples) + excluded.avg_voltage) / (samples + 1),
                    avg_soc = ((avg_soc * samples) + excluded.avg_soc) / (samples + 1),
                    error_count = error_count + excluded.error_count,
                    last_seen = excluded.last_seen
                """,
                (
                    device.id,
                    day,
                    device.voltage,
                    device.voltage,
                    device.voltage,
                    float(device.soc),
                    1 if device.error_code is not None else 0,
                    device.last_seen,
                ),
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
    finally:
        connection.close()
    return {
        "gateway_snapshots": int(gateway_count[0]) if gateway_count is not None else 0,
        "device_readings": int(device_count[0]) if device_count is not None else 0,
        "device_daily_rollups": int(daily_count[0]) if daily_count is not None else 0,
    }


def fetch_recent_history(
    path: Path,
    *,
    device_id: str,
    limit: int = 200,
) -> list[dict[str, object]]:
    connection = _connect_database(path)
    try:
        rows = connection.execute(
            """
            SELECT snapshot_generated_at, voltage, soc, state, error_code, error_detail
            FROM device_readings
            WHERE device_id = ?
            ORDER BY snapshot_generated_at DESC
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
            "soc": row[2],
            "state": row[3],
            "error_code": row[4],
            "error_detail": row[5],
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
            "day": row[0],
            "samples": row[1],
            "min_voltage": row[2],
            "max_voltage": row[3],
            "avg_voltage": row[4],
            "avg_soc": row[5],
            "error_count": row[6],
            "last_seen": row[7],
        }
        for row in rows
    ]
