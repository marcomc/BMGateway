"""Device archive sync helpers."""

from __future__ import annotations

import asyncio
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, cast

from .audit_log import append_audit_event
from .bluetooth_lock import exclusive_bluetooth_operation
from .bluetooth_recovery import is_fatal_bluetooth_error, require_bluetooth_recovery
from .bm300_multipage import (
    BM300_LEGACY_PROFILE,
    BM300_STANDARD_PROFILE,
    run_bm300_multipage_import,
)
from .config import AppConfig
from .device_registry import Device, device_driver_type
from .drivers.bm200 import read_bm200_history
from .drivers.bm300 import BM300HistoryReading, BM300TimeoutError, read_bm300_history_selector
from .models import GatewaySnapshot
from .runtime import _active_adapter
from .state_store import (
    import_archive_history,
    latest_archive_history_timestamp,
    latest_live_history_timestamp,
)
from .subprocess_runner import run_in_subprocess_with_timeout

BM200_ARCHIVE_PROFILE = "bm6_d15505_b7_v1"
BM300_ARCHIVE_PROFILE = BM300_STANDARD_PROFILE
BM200_HISTORY_PAGE_SECONDS = 256 * 2 * 60
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
    state_dir = database_path.parent.parent
    if progress is not None:
        progress(0, max(1, page_count * 256), "Downloading history records")
    with exclusive_bluetooth_operation(
        config,
        state_dir=state_dir,
        operation=f"archive_sync:{device.id}",
    ):
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

    history_timeout_seconds = max(float(config.bluetooth.connect_timeout_seconds) * 4.0, 180.0)
    requested_depth = min(max(1, page_count), 3)
    state_dir = database_path.parent.parent

    with exclusive_bluetooth_operation(
        config,
        state_dir=state_dir,
        operation=f"archive_sync:{device.id}",
    ):
        if progress is not None:
            progress(0, requested_depth * 256, "Downloading history records")
        payload = run_in_subprocess_with_timeout(
            function=_run_bm300_device_archive_import,
            args=(
                config,
                device,
                database_path,
                requested_depth,
                history_timeout_seconds,
            ),
            timeout_seconds=(history_timeout_seconds * requested_depth) + 30.0,
            timeout_error=lambda: BM300TimeoutError(
                f"{device.mac} archive import exceeded the hard timeout."
            ),
        )
    fetched_record_counts = cast(dict[str, int], payload["fetched_record_counts"])
    payload["fetched"] = max(fetched_record_counts.values())
    payload["page_count"] = requested_depth
    if progress is not None:
        inserted = cast(int, payload["inserted"])
        progress(0, inserted, "Importing history records")
        progress(inserted, inserted, "History sync completed")
    return payload


def _run_bm300_device_archive_import(
    config: AppConfig,
    device: Device,
    database_path: Path,
    requested_depth: int,
    history_timeout_seconds: float,
    progress: ArchiveSyncProgress | None = None,
) -> dict[str, object]:
    adapter = _active_adapter(config)
    progress_state: dict[str, datetime | None] = {"reference_ts": None}

    def selector_reader(selector: int) -> list[BM300HistoryReading]:
        if selector > requested_depth:
            return []
        reference_ts = progress_state["reference_ts"]
        if reference_ts is None:
            from .drivers.bm300 import default_bm7_history_reference_ts

            reference_ts = default_bm7_history_reference_ts()
            progress_state["reference_ts"] = reference_ts
        return asyncio.run(
            read_bm300_history_selector(
                address=device.mac,
                adapter=adapter,
                timeout_seconds=history_timeout_seconds,
                scan_timeout_seconds=float(config.bluetooth.scan_timeout_seconds),
                selector_byte=7,
                selector_value=selector,
                reference_ts=reference_ts,
            )
        )

    return run_bm300_multipage_import(
        device=device,
        output_database_path=database_path,
        adapter=adapter,
        selector_reader=selector_reader,
        selectors=(1, 2, 3)[:requested_depth],
        profile=BM300_ARCHIVE_PROFILE,
        replace_profiles=(
            BM300_ARCHIVE_PROFILE,
            BM300_LEGACY_PROFILE,
            "bm7_d15505_b7_v1_experimental",
        ),
        progress=progress,
    )


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
    _ = coverage_seconds
    return min(max(1, max_pages), 3)


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


def plan_archive_backfill_details(
    *,
    config: AppConfig,
    database_path: Path,
    snapshot: GatewaySnapshot,
    poll_interval_seconds: int | None = None,
) -> dict[str, dict[str, object]]:
    _ = poll_interval_seconds
    if not config.archive_sync.enabled:
        return {}

    candidates: dict[str, dict[str, object]] = {}
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
            page_count = max_pages
        else:
            coverage_seconds = max(coverage_candidates) + config.archive_sync.safety_margin_seconds
            page_count = _archive_sync_pages_for_coverage_seconds(
                coverage_seconds,
                max_pages=max_pages,
                device_type=reading.type,
            )

        reasons: list[str] = []
        if periodic_due:
            reasons.append("periodic")
        if reconnect_due:
            reasons.append("reconnect")
        candidates[reading.id] = {
            "page_count": page_count,
            "reasons": reasons,
        }
    return candidates


def plan_archive_backfill(
    *,
    config: AppConfig,
    database_path: Path,
    snapshot: GatewaySnapshot,
    poll_interval_seconds: int | None = None,
) -> dict[str, int]:
    details = plan_archive_backfill_details(
        config=config,
        database_path=database_path,
        snapshot=snapshot,
        poll_interval_seconds=poll_interval_seconds,
    )
    return {
        device_id: int(cast(int, candidate["page_count"]))
        for device_id, candidate in details.items()
    }


def sync_archive_backfill_candidates(
    *,
    config: AppConfig,
    devices: list[Device],
    database_path: Path,
    device_pages: Mapping[str, int],
    source: str = "runtime",
    trigger: str = "automatic",
    device_reasons: Mapping[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    devices_by_id = {device.id: device for device in devices}
    results: list[dict[str, object]] = []
    state_dir = database_path.parent.parent
    for device_id in sorted(device_pages):
        device = devices_by_id.get(device_id)
        if device is None or not device.enabled:
            continue
        append_audit_event(
            config=config,
            state_dir=state_dir,
            source=source,
            trigger=trigger,
            action="archive_sync_started",
            status="started",
            details={
                "device_id": device_id,
                "device_type": device.type,
                "page_count": device_pages[device_id],
                "reasons": list(device_reasons.get(device_id, []))
                if device_reasons is not None
                else [],
            },
        )
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
            if is_fatal_bluetooth_error(exc):
                append_audit_event(
                    config=config,
                    state_dir=state_dir,
                    source=source,
                    trigger=trigger,
                    action="archive_sync_completed",
                    status="failed",
                    details={
                        "device_id": device_id,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc) or exc.__class__.__name__,
                        "fatal_bluetooth_error": True,
                        "reasons": list(device_reasons.get(device_id, []))
                        if device_reasons is not None
                        else [],
                    },
                )
                require_bluetooth_recovery(exc)
            failure = {
                "device_id": device_id,
                "synced": False,
                "error_type": exc.__class__.__name__,
                "error": str(exc) or exc.__class__.__name__,
                "reasons": list(device_reasons.get(device_id, []))
                if device_reasons is not None
                else [],
            }
            append_audit_event(
                config=config,
                state_dir=state_dir,
                source=source,
                trigger=trigger,
                action="archive_sync_completed",
                status="failed",
                details=failure,
            )
            results.append(failure)
            continue
        payload["synced"] = True
        append_audit_event(
            config=config,
            state_dir=state_dir,
            source=source,
            trigger=trigger,
            action="archive_sync_completed",
            status="completed",
            details=payload,
        )
        results.append(payload)
    return results
