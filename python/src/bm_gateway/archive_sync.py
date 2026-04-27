"""Device archive sync helpers."""

from __future__ import annotations

import asyncio
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .config import AppConfig
from .device_registry import Device, device_driver_type
from .drivers.bm200 import read_bm200_history
from .drivers.bm300 import read_bm300_history
from .models import GatewaySnapshot
from .runtime import _active_adapter
from .state_store import (
    import_archive_history,
    latest_archive_history_timestamp,
    latest_live_history_timestamp,
)

BM200_ARCHIVE_PROFILE = "bm6_d15505_b7_v1"
BM300_ARCHIVE_PROFILE = "bm7_d15505_b6_v1"
BM200_HISTORY_PAGE_SECONDS = 256 * 2 * 60
BM300_HISTORY_PAGE_SECONDS = 883 * 2 * 60
ArchiveSyncProgress = Callable[[int, int, str], None]


def sync_bm200_device_archive(
    *,
    config: AppConfig,
    device: Device,
    database_path: Path,
    page_count: int = 3,
    progress: ArchiveSyncProgress | None = None,
) -> dict[str, object]:
    if device.type != "bm200":
        raise ValueError(f"archive sync is only implemented for bm200 devices, got {device.type}")

    adapter = _active_adapter(config)
    history_timeout_seconds = max(float(config.bluetooth.connect_timeout_seconds) * 4.0, 180.0)
    if progress is not None:
        progress(0, max(1, page_count * 256), "Downloading history records")
    history = asyncio.run(
        read_bm200_history(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=history_timeout_seconds,
            scan_timeout_seconds=float(config.bluetooth.scan_timeout_seconds),
            page_count=page_count,
        )
    )
    rows = [asdict(reading) for reading in history]
    if progress is not None:
        progress(0, len(rows), "Importing history records")
    inserted = import_archive_history(
        database_path,
        device_id=device.id,
        device_type=device.type,
        name=device.name,
        mac=device.mac,
        adapter=adapter,
        driver="bm200",
        profile=BM200_ARCHIVE_PROFILE,
        readings=rows,
        progress=progress,
    )
    if progress is not None:
        progress(len(rows), len(rows), "History sync completed")
    return {
        "device_id": device.id,
        "fetched": len(rows),
        "inserted": inserted,
        "adapter": adapter,
        "profile": BM200_ARCHIVE_PROFILE,
        "page_count": page_count,
    }


def sync_bm300_device_archive(
    *,
    config: AppConfig,
    device: Device,
    database_path: Path,
    page_count: int = 3,
    progress: ArchiveSyncProgress | None = None,
) -> dict[str, object]:
    if device_driver_type(device.type) != "bm300pro":
        raise ValueError(
            f"BM7 archive sync is only implemented for bm300pro devices, got {device.type}"
        )

    adapter = _active_adapter(config)
    history_timeout_seconds = max(float(config.bluetooth.connect_timeout_seconds) * 4.0, 180.0)
    if progress is not None:
        progress(0, max(1, page_count * 883), "Downloading history records")
    history = asyncio.run(
        read_bm300_history(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=history_timeout_seconds,
            scan_timeout_seconds=float(config.bluetooth.scan_timeout_seconds),
            page_count=page_count,
        )
    )
    rows = [asdict(reading) for reading in history]
    if progress is not None:
        progress(0, len(rows), "Importing history records")
    inserted = import_archive_history(
        database_path,
        device_id=device.id,
        device_type=device.type,
        name=device.name,
        mac=device.mac,
        adapter=adapter,
        driver="bm300pro",
        profile=BM300_ARCHIVE_PROFILE,
        readings=rows,
        progress=progress,
    )
    if progress is not None:
        progress(len(rows), len(rows), "History sync completed")
    return {
        "device_id": device.id,
        "fetched": len(rows),
        "inserted": inserted,
        "adapter": adapter,
        "profile": BM300_ARCHIVE_PROFILE,
        "page_count": page_count,
    }


def bm200_history_pages_for_coverage_seconds(
    coverage_seconds: float,
    *,
    max_pages: int,
) -> int:
    page_limit = max(1, max_pages)
    requested_pages = math.ceil(max(1.0, coverage_seconds) / BM200_HISTORY_PAGE_SECONDS)
    return max(1, min(page_limit, requested_pages))


def bm300_history_pages_for_coverage_seconds(
    coverage_seconds: float,
    *,
    max_pages: int,
) -> int:
    page_limit = max(1, max_pages)
    requested_pages = math.ceil(max(1.0, coverage_seconds) / BM300_HISTORY_PAGE_SECONDS)
    return max(1, min(page_limit, requested_pages))


def _archive_sync_profile_for_reading(device_type: str, bm300_enabled: bool) -> str | None:
    driver_type = device_driver_type(device_type)
    if driver_type == "bm200":
        return BM200_ARCHIVE_PROFILE
    if driver_type == "bm300pro" and bm300_enabled:
        return BM300_ARCHIVE_PROFILE
    return None


def _archive_sync_max_pages_for_reading(config: AppConfig, device_type: str) -> int:
    if device_driver_type(device_type) == "bm300pro":
        return max(1, config.archive_sync.bm300_max_pages_per_sync)
    return max(1, config.archive_sync.bm200_max_pages_per_sync)


def _archive_sync_pages_for_coverage_seconds(
    coverage_seconds: float,
    *,
    max_pages: int,
    device_type: str,
) -> int:
    if device_driver_type(device_type) == "bm300pro":
        return bm300_history_pages_for_coverage_seconds(coverage_seconds, max_pages=max_pages)
    return bm200_history_pages_for_coverage_seconds(coverage_seconds, max_pages=max_pages)


def plan_archive_backfill(
    *,
    config: AppConfig,
    database_path: Path,
    snapshot: GatewaySnapshot,
    poll_interval_seconds: int | None = None,
) -> dict[str, int]:
    _ = poll_interval_seconds
    if not config.archive_sync.enabled:
        return {}

    candidates: dict[str, int] = {}
    for reading in snapshot.devices:
        profile = _archive_sync_profile_for_reading(
            reading.type,
            bm300_enabled=config.archive_sync.bm300_enabled,
        )
        if not reading.connected or reading.error_code is not None or profile is None:
            continue
        max_pages = _archive_sync_max_pages_for_reading(config, reading.type)
        current_seen = datetime.fromisoformat(reading.last_seen)
        latest_archive_ts = latest_archive_history_timestamp(
            database_path,
            device_id=reading.id,
            profile=profile,
        )
        latest_live_ts = latest_live_history_timestamp(database_path, device_id=reading.id)
        archive_gap_seconds: float | None = None
        live_gap_seconds: float | None = None
        if latest_archive_ts is not None:
            archive_gap_seconds = (
                current_seen - datetime.fromisoformat(latest_archive_ts)
            ).total_seconds()
        if latest_live_ts is not None:
            live_gap_seconds = (
                current_seen - datetime.fromisoformat(latest_live_ts)
            ).total_seconds()

        periodic_due = latest_archive_ts is None or (
            archive_gap_seconds is not None
            and archive_gap_seconds >= config.archive_sync.periodic_interval_seconds
        )
        reconnect_due = (
            live_gap_seconds is not None
            and live_gap_seconds >= config.archive_sync.reconnect_min_gap_seconds
        )
        if not periodic_due and not reconnect_due:
            continue

        coverage_candidates = [
            seconds
            for seconds in (archive_gap_seconds, live_gap_seconds)
            if seconds is not None and seconds > 0
        ]
        if not coverage_candidates:
            candidates[reading.id] = max_pages
            continue

        coverage_seconds = max(coverage_candidates) + config.archive_sync.safety_margin_seconds
        candidates[reading.id] = _archive_sync_pages_for_coverage_seconds(
            coverage_seconds,
            max_pages=max_pages,
            device_type=reading.type,
        )
    return candidates


def sync_archive_backfill_candidates(
    *,
    config: AppConfig,
    devices: list[Device],
    database_path: Path,
    device_pages: Mapping[str, int],
) -> list[dict[str, object]]:
    devices_by_id = {device.id: device for device in devices}
    results: list[dict[str, object]] = []
    for device_id in sorted(device_pages):
        device = devices_by_id.get(device_id)
        if device is None or not device.enabled:
            continue
        try:
            driver_type = device_driver_type(device.type)
            if driver_type == "bm200":
                payload = sync_bm200_device_archive(
                    config=config,
                    device=device,
                    database_path=database_path,
                    page_count=device_pages[device_id],
                )
            elif driver_type == "bm300pro" and config.archive_sync.bm300_enabled:
                payload = sync_bm300_device_archive(
                    config=config,
                    device=device,
                    database_path=database_path,
                    page_count=device_pages[device_id],
                )
            else:
                continue
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
