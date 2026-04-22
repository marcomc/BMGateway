"""Device archive sync helpers."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .device_registry import Device
from .drivers.bm200 import read_bm200_history
from .models import GatewaySnapshot
from .runtime import _active_adapter
from .state_store import import_archive_history, latest_history_timestamp


def sync_bm200_device_archive(
    *,
    config: AppConfig,
    device: Device,
    database_path: Path,
) -> dict[str, object]:
    if device.type != "bm200":
        raise ValueError(f"archive sync is only implemented for bm200 devices, got {device.type}")

    adapter = _active_adapter(config)
    history_timeout_seconds = max(float(config.bluetooth.connect_timeout_seconds) * 4.0, 180.0)
    history = asyncio.run(
        read_bm200_history(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=history_timeout_seconds,
            scan_timeout_seconds=float(config.bluetooth.scan_timeout_seconds),
        )
    )
    rows = [asdict(reading) for reading in history]
    inserted = import_archive_history(
        database_path,
        device_id=device.id,
        device_type=device.type,
        name=device.name,
        mac=device.mac,
        adapter=adapter,
        driver="bm200",
        profile="legacy_bm2_history",
        readings=rows,
    )
    return {
        "device_id": device.id,
        "fetched": len(rows),
        "inserted": inserted,
        "adapter": adapter,
        "profile": "legacy_bm2_history",
    }


def plan_archive_backfill(
    *,
    database_path: Path,
    snapshot: GatewaySnapshot,
    poll_interval_seconds: int,
) -> set[str]:
    threshold_seconds = max(poll_interval_seconds * 2, 30 * 60)
    candidates: set[str] = set()
    for reading in snapshot.devices:
        if not reading.connected or reading.error_code is not None or reading.type != "bm200":
            continue
        latest_ts = latest_history_timestamp(database_path, device_id=reading.id)
        if latest_ts is None:
            candidates.add(reading.id)
            continue
        current_seen = datetime.fromisoformat(reading.last_seen)
        latest_seen = datetime.fromisoformat(latest_ts)
        if (current_seen - latest_seen).total_seconds() > threshold_seconds:
            candidates.add(reading.id)
    return candidates


def sync_archive_backfill_candidates(
    *,
    config: AppConfig,
    devices: list[Device],
    database_path: Path,
    device_ids: set[str],
) -> list[dict[str, object]]:
    devices_by_id = {device.id: device for device in devices}
    results: list[dict[str, object]] = []
    for device_id in sorted(device_ids):
        device = devices_by_id.get(device_id)
        if device is None or device.type != "bm200" or not device.enabled:
            continue
        try:
            payload = sync_bm200_device_archive(
                config=config,
                device=device,
                database_path=database_path,
            )
        except Exception as exc:
            results.append(
                {
                    "device_id": device_id,
                    "synced": False,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc) or exc.__class__.__name__,
                }
            )
            continue
        payload["synced"] = True
        results.append(payload)
    return results
