"""Device archive sync helpers."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

from .config import AppConfig
from .device_registry import Device
from .drivers.bm200 import read_bm200_history
from .runtime import _active_adapter
from .state_store import import_archive_history


def sync_bm200_device_archive(
    *,
    config: AppConfig,
    device: Device,
    database_path: Path,
) -> dict[str, object]:
    if device.type != "bm200":
        raise ValueError(f"archive sync is only implemented for bm200 devices, got {device.type}")

    adapter = _active_adapter(config)
    history = asyncio.run(
        read_bm200_history(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=float(config.bluetooth.connect_timeout_seconds),
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
