"""Experimental BM300 Pro / BM7 multipage history import helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .device_registry import Device, device_driver_type
from .drivers.bm300 import BM300HistoryReading
from .state_store import delete_archive_history_profiles, import_archive_history

BM300_MULTIPAGE_SELECTORS = (1, 2, 3)
BM300_MULTIPAGE_MIN_OVERLAP = 128
BM300_MULTIPAGE_PROFILE = "bm7_d15505_b7_v1_experimental"
BM300_STANDARD_PROFILE = "bm7_d15505_b7_v1"
BM300_LEGACY_PROFILE = "bm7_d15505_b6_v1"
BM300_MULTIPAGE_DRIVER = "bm300pro"
BM300_SELECTOR_BYTE = 7
BM300SelectorReader = Callable[[int], list[BM300HistoryReading]]
ArchiveImportProgress = Callable[[int, int, str], None]


class BM300MultipageError(Exception):
    """Base error for experimental BM300 multipage imports."""


class BM300MultipageValidationError(BM300MultipageError):
    """Raised when selector overlap is not strong enough to import safely."""

    def __init__(self, message: str, *, report: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


@dataclass(frozen=True)
class BM300SelectorFetch:
    selector: int
    readings: tuple[BM300HistoryReading, ...]

    @property
    def record_count(self) -> int:
        return len(self.readings)


@dataclass(frozen=True)
class BM300SelectorOverlap:
    previous_selector: int
    current_selector: int
    previous_record_count: int
    current_record_count: int
    best_run_length: int
    previous_offset: int | None
    current_offset: int | None
    accepted: bool
    imported_older_count: int
    failure_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "previous_selector": self.previous_selector,
            "current_selector": self.current_selector,
            "previous_record_count": self.previous_record_count,
            "current_record_count": self.current_record_count,
            "best_run_length": self.best_run_length,
            "previous_offset": self.previous_offset,
            "current_offset": self.current_offset,
            "accepted": self.accepted,
            "imported_older_count": self.imported_older_count,
            "failure_reason": self.failure_reason,
        }


def run_bm300_multipage_import(
    *,
    device: Device,
    output_database_path: Path,
    adapter: str,
    selector_reader: BM300SelectorReader,
    selectors: tuple[int, ...] = BM300_MULTIPAGE_SELECTORS,
    profile: str = BM300_MULTIPAGE_PROFILE,
    replace_profiles: tuple[str, ...] = (),
    progress: ArchiveImportProgress | None = None,
) -> dict[str, object]:
    if device_driver_type(device.type) != "bm300pro":
        raise ValueError(
            f"BM300 multipage import requires a BM300 Pro/BM7 device, got {device.type}"
        )
    if not selectors:
        raise ValueError("BM300 multipage import requires at least one selector.")
    if selectors[0] != BM300_MULTIPAGE_SELECTORS[0]:
        raise ValueError("BM300 multipage import must start from selector 1.")
    if any(selector not in BM300_MULTIPAGE_SELECTORS for selector in selectors):
        raise ValueError("BM300 multipage import selectors must be within 1..3.")

    expected_total = len(selectors) * 256
    if progress is not None:
        progress(0, expected_total, "Downloading history records")
    fetched_items: list[BM300SelectorFetch] = []
    for selector in selectors:
        fetch = BM300SelectorFetch(selector=selector, readings=tuple(selector_reader(selector)))
        fetched_items.append(fetch)
        if progress is not None:
            progress(
                min(fetch.record_count, expected_total),
                expected_total,
                "Downloading history records",
            )
    fetches = tuple(fetched_items)
    if not fetches[0].readings:
        raise BM300MultipageValidationError(
            "Selector b7=01 returned no history records.",
            report=_report(
                device=device,
                adapter=adapter,
                output_database_path=output_database_path,
                fetches=fetches,
                overlaps=[],
                inserted=0,
                validated_depth=0,
                profile=profile,
            ),
        )

    stitched = list(fetches[0].readings)
    overlaps: list[BM300SelectorOverlap] = []
    validated_depth = fetches[0].selector
    for previous_fetch, current_fetch in zip(fetches, fetches[1:], strict=False):
        overlap, older_extension = _validate_selector_overlap(previous_fetch, current_fetch)
        overlaps.append(overlap)
        if not overlap.accepted:
            raise BM300MultipageValidationError(
                overlap.failure_reason or "BM300 selector overlap validation failed.",
                report=_report(
                    device=device,
                    adapter=adapter,
                    output_database_path=output_database_path,
                    fetches=fetches,
                    overlaps=overlaps,
                    inserted=0,
                    validated_depth=validated_depth,
                    profile=profile,
                ),
            )
        stitched.extend(older_extension)
        validated_depth = current_fetch.selector

    rebuilt_readings = _rebuild_stitched_timestamps(stitched)
    if replace_profiles:
        delete_archive_history_profiles(
            output_database_path,
            device_id=device.id,
            profiles=replace_profiles,
        )
    if progress is not None:
        progress(0, len(rebuilt_readings), "Importing history records")
    inserted = import_archive_history(
        output_database_path,
        device_id=device.id,
        device_type=device.type,
        name=device.name,
        mac=device.mac,
        adapter=adapter,
        driver=BM300_MULTIPAGE_DRIVER,
        profile=profile,
        readings=[asdict(reading) for reading in rebuilt_readings],
        progress=progress,
    )
    if progress is not None:
        progress(len(rebuilt_readings), len(rebuilt_readings), "History sync completed")
    return _report(
        device=device,
        adapter=adapter,
        output_database_path=output_database_path,
        fetches=fetches,
        overlaps=overlaps,
        inserted=inserted,
        validated_depth=validated_depth,
        profile=profile,
    )


def _report(
    *,
    device: Device,
    adapter: str,
    output_database_path: Path,
    fetches: tuple[BM300SelectorFetch, ...],
    overlaps: list[BM300SelectorOverlap],
    inserted: int,
    validated_depth: int,
    profile: str = BM300_MULTIPAGE_PROFILE,
) -> dict[str, object]:
    return {
        "device_id": device.id,
        "selectors": [fetch.selector for fetch in fetches],
        "selector_byte": BM300_SELECTOR_BYTE,
        "fetched_record_counts": {str(fetch.selector): fetch.record_count for fetch in fetches},
        "validated_depth": validated_depth,
        "inserted": inserted,
        "adapter": adapter,
        "profile": profile,
        "output_db": str(output_database_path),
        "overlaps": [overlap.to_dict() for overlap in overlaps],
    }


def _validate_selector_overlap(
    previous_fetch: BM300SelectorFetch,
    current_fetch: BM300SelectorFetch,
) -> tuple[BM300SelectorOverlap, tuple[BM300HistoryReading, ...]]:
    previous_raw = _raw_sequence(previous_fetch.readings)
    current_raw = _raw_sequence(current_fetch.readings)
    best_run_length, previous_offset, current_offset = _best_common_run(previous_raw, current_raw)

    failure_reason: str | None = None
    older_extension: tuple[BM300HistoryReading, ...] = ()
    accepted = (
        best_run_length >= BM300_MULTIPAGE_MIN_OVERLAP
        and previous_offset == 0
        and current_offset is not None
    )
    if accepted and current_offset is not None:
        older_extension = current_fetch.readings[current_offset + best_run_length :]
    elif best_run_length < BM300_MULTIPAGE_MIN_OVERLAP:
        failure_reason = (
            "BM300 selector overlap failed: need at least 128 consecutive identical raw "
            f"records, found {best_run_length} between b7={previous_fetch.selector:02x} "
            f"and b7={current_fetch.selector:02x}."
        )
    elif previous_offset != 0:
        failure_reason = (
            "BM300 selector overlap failed: the strongest raw overlap does not start at the "
            f"newest record of b7={previous_fetch.selector:02x}."
        )
    else:
        failure_reason = (
            "BM300 selector overlap failed: the deeper selector does not contain a usable "
            f"raw overlap run for b7={current_fetch.selector:02x}."
        )

    overlap = BM300SelectorOverlap(
        previous_selector=previous_fetch.selector,
        current_selector=current_fetch.selector,
        previous_record_count=len(previous_raw),
        current_record_count=len(current_raw),
        best_run_length=best_run_length,
        previous_offset=previous_offset,
        current_offset=current_offset,
        accepted=accepted,
        imported_older_count=len(older_extension),
        failure_reason=failure_reason,
    )
    return overlap, older_extension


def _raw_sequence(readings: tuple[BM300HistoryReading, ...]) -> list[str]:
    raw_values: list[str] = []
    for reading in readings:
        raw_record = reading.raw_record
        if raw_record is None or len(raw_record) != 8:
            raise BM300MultipageValidationError("BM300 history reading is missing a raw_record.")
        raw_values.append(raw_record.lower())
    return raw_values


def _best_common_run(left: list[str], right: list[str]) -> tuple[int, int | None, int | None]:
    positions: dict[str, list[int]] = {}
    for index, value in enumerate(right):
        positions.setdefault(value, []).append(index)
    best_length = 0
    best_left: int | None = None
    best_right: int | None = None
    previous: dict[int, int] = {}
    for left_index, value in enumerate(left):
        current: dict[int, int] = {}
        for right_index in positions.get(value, []):
            length = previous.get(right_index - 1, 0) + 1
            current[right_index] = length
            if length > best_length:
                best_length = length
                best_left = left_index - length + 1
                best_right = right_index - length + 1
        previous = current
    return best_length, best_left, best_right


def _rebuild_stitched_timestamps(
    readings: list[BM300HistoryReading],
) -> list[BM300HistoryReading]:
    if not readings:
        return []
    anchor_ts = datetime.fromisoformat(readings[0].ts)
    rebuilt: list[BM300HistoryReading] = []
    for index, reading in enumerate(readings):
        rebuilt.append(
            replace(
                reading,
                ts=(anchor_ts - timedelta(minutes=index * 2)).isoformat(timespec="seconds"),
            )
        )
    return rebuilt
