from __future__ import annotations

import sqlite3
from pathlib import Path

from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.state_store import fetch_daily_history, persist_snapshot, prune_history


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
