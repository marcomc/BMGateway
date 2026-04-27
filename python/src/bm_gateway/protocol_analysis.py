"""Offline analysis helpers for protocol-probe history captures."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SELECTOR_RE = re.compile(r"_(b[0-9]+_[0-9a-fA-F]{2})$")


@dataclass(frozen=True)
class DecodedHistoryRecord:
    raw: str
    voltage: float
    soc: int
    temperature: int
    event: int
    plausible: bool
    marker: bool


@dataclass(frozen=True)
class ProbeCommandRecords:
    capture_path: Path
    command: str
    selector: str
    records: tuple[DecodedHistoryRecord, ...]


def decode_history_record(raw: str) -> DecodedHistoryRecord:
    normalized = raw.lower()
    if len(normalized) != 8:
        raise ValueError("history record must be 4 bytes encoded as 8 hex characters")
    voltage = int(normalized[0:3], 16) / 100
    soc = int(normalized[3:5], 16)
    temperature = int(normalized[5:7], 16)
    event = int(normalized[7], 16)
    marker = voltage == 0.0
    plausible = 8.0 <= voltage <= 16.5 and 0 <= soc <= 100 and 0 <= temperature <= 80
    return DecodedHistoryRecord(
        raw=normalized,
        voltage=voltage,
        soc=soc,
        temperature=temperature,
        event=event,
        plausible=plausible,
        marker=marker,
    )


def analyze_history_captures(paths: list[Path]) -> dict[str, Any]:
    commands = [command for path in paths for command in load_history_capture(path)]
    overlaps = _compare_same_selector(commands)
    return {
        "captures": [str(path) for path in paths],
        "commands": [_summarize_command(command) for command in commands],
        "overlaps": [_overlap_to_dict(overlap) for overlap in overlaps],
        "selector_recommendations": _selector_recommendations(commands, overlaps),
    }


def load_history_capture(path: Path) -> list[ProbeCommandRecords]:
    results: list[ProbeCommandRecords] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            if event.get("event") != "command_result":
                continue
            command = str(event.get("command") or "")
            records = tuple(decode_history_record(raw) for raw in _history_raw_records(event))
            results.append(
                ProbeCommandRecords(
                    capture_path=path,
                    command=command,
                    selector=_selector_from_command(command),
                    records=records,
                )
            )
    return results


def _history_raw_records(event: dict[str, Any]) -> list[str]:
    payload = bytearray()
    seen_header = False
    for packet in event.get("packets") or []:
        plaintexts = _packet_plaintexts(packet)
        for plaintext_hex in plaintexts:
            plaintext = bytes.fromhex(plaintext_hex)
            if plaintext.startswith(bytes.fromhex("d15505")):
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("fffffe")):
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("fffefe")):
                continue
            if plaintext.startswith(bytes.fromhex("fefefe")):
                continue
            if plaintext.startswith(bytes.fromhex("d15507")):
                continue
            if seen_header:
                payload.extend(plaintext)
    records = []
    for index in range(0, len(payload), 4):
        item = payload[index : index + 4]
        if len(item) == 4 and item != bytes(4):
            records.append(item.hex())
    return records


def _packet_plaintexts(packet: dict[str, Any]) -> list[str]:
    frames = packet.get("frames")
    if isinstance(frames, list) and frames:
        return [
            str(frame["plaintext"]) for frame in frames if isinstance(frame.get("plaintext"), str)
        ]
    plaintext = packet.get("plaintext")
    return [str(plaintext)] if isinstance(plaintext, str) else []


def _selector_from_command(command: str) -> str:
    match = SELECTOR_RE.search(command)
    return match.group(1).lower() if match else command


def _summarize_command(command: ProbeCommandRecords) -> dict[str, Any]:
    event_counts = Counter(str(record.event) for record in command.records)
    plausible_records = [record for record in command.records if record.plausible]
    marker_records = [record for record in command.records if record.marker]
    voltages = [record.voltage for record in plausible_records]
    soc_values = [record.soc for record in plausible_records]
    temperatures = [record.temperature for record in plausible_records]
    summary: dict[str, Any] = {
        "capture": str(command.capture_path),
        "command": command.command,
        "selector": command.selector,
        "record_count": len(command.records),
        "plausible_count": len(plausible_records),
        "marker_count": len(marker_records),
        "event_counts": dict(sorted(event_counts.items())),
        "first_raw": command.records[0].raw if command.records else None,
        "last_raw": command.records[-1].raw if command.records else None,
    }
    if plausible_records:
        summary.update(
            {
                "voltage_range": [min(voltages), max(voltages)],
                "soc_range": [min(soc_values), max(soc_values)],
                "temperature_range": [min(temperatures), max(temperatures)],
            }
        )
    return summary


@dataclass(frozen=True)
class SequenceOverlap:
    selector: str
    old_capture: Path
    new_capture: Path
    old_record_count: int
    new_record_count: int
    old_in_new_offset: int | None
    new_in_old_offset: int | None
    best_run_length: int
    best_run_old_offset: int | None
    best_run_new_offset: int | None
    classification: str


def _compare_same_selector(commands: list[ProbeCommandRecords]) -> list[SequenceOverlap]:
    overlaps: list[SequenceOverlap] = []
    by_selector: dict[str, list[ProbeCommandRecords]] = {}
    for command in commands:
        if not command.records:
            continue
        by_selector.setdefault(command.selector, []).append(command)
    for selector_commands in by_selector.values():
        for old, new in zip(selector_commands, selector_commands[1:], strict=False):
            overlaps.append(_compare_sequences(old, new))
    return overlaps


def _compare_sequences(old: ProbeCommandRecords, new: ProbeCommandRecords) -> SequenceOverlap:
    old_raw = [record.raw for record in old.records]
    new_raw = [record.raw for record in new.records]
    old_in_new = _find_subsequence(new_raw, old_raw)
    new_in_old = _find_subsequence(old_raw, new_raw)
    best_length, best_old_offset, best_new_offset = _best_common_run(old_raw, new_raw)
    if old_in_new is not None and old_in_new > 0:
        classification = "rolling_window"
    elif new_in_old is not None:
        classification = "shrinking_or_duplicate_window"
    elif best_length >= max(32, min(len(old_raw), len(new_raw)) // 2):
        classification = "partial_overlap"
    elif best_length > 0:
        classification = "weak_overlap"
    else:
        classification = "no_overlap"
    return SequenceOverlap(
        selector=old.selector,
        old_capture=old.capture_path,
        new_capture=new.capture_path,
        old_record_count=len(old.records),
        new_record_count=len(new.records),
        old_in_new_offset=old_in_new,
        new_in_old_offset=new_in_old,
        best_run_length=best_length,
        best_run_old_offset=best_old_offset,
        best_run_new_offset=best_new_offset,
        classification=classification,
    )


def _find_subsequence(haystack: list[str], needle: list[str]) -> int | None:
    if not needle or len(needle) > len(haystack):
        return None
    first = needle[0]
    for index, item in enumerate(haystack):
        if item == first and haystack[index : index + len(needle)] == needle:
            return index
    return None


def _best_common_run(left: list[str], right: list[str]) -> tuple[int, int | None, int | None]:
    positions: dict[str, list[int]] = {}
    for index, item in enumerate(right):
        positions.setdefault(item, []).append(index)
    best_length = 0
    best_left: int | None = None
    best_right: int | None = None
    previous: dict[int, int] = {}
    for left_index, item in enumerate(left):
        current: dict[int, int] = {}
        for right_index in positions.get(item, []):
            length = previous.get(right_index - 1, 0) + 1
            current[right_index] = length
            if length > best_length:
                best_length = length
                best_left = left_index - length + 1
                best_right = right_index - length + 1
        previous = current
    return best_length, best_left, best_right


def _overlap_to_dict(overlap: SequenceOverlap) -> dict[str, Any]:
    return {
        "selector": overlap.selector,
        "old_capture": str(overlap.old_capture),
        "new_capture": str(overlap.new_capture),
        "old_record_count": overlap.old_record_count,
        "new_record_count": overlap.new_record_count,
        "old_in_new_offset": overlap.old_in_new_offset,
        "new_in_old_offset": overlap.new_in_old_offset,
        "best_run_length": overlap.best_run_length,
        "best_run_old_offset": overlap.best_run_old_offset,
        "best_run_new_offset": overlap.best_run_new_offset,
        "classification": overlap.classification,
    }


def _selector_recommendations(
    commands: list[ProbeCommandRecords],
    overlaps: list[SequenceOverlap],
) -> list[dict[str, str]]:
    max_counts: dict[str, int] = {}
    for command in commands:
        max_counts[command.selector] = max(
            max_counts.get(command.selector, 0), len(command.records)
        )

    recommendations: list[dict[str, str]] = []
    seen: set[str] = set()
    for overlap in overlaps:
        if overlap.selector in seen:
            continue
        if overlap.classification == "rolling_window":
            if max_counts.get(overlap.selector, 0) >= 8192:
                status = "capped_stitch_candidate"
                reason = (
                    "same selector shifts, but at least one capture reached the 8192-record cap"
                )
            else:
                status = "stitch_candidate"
                reason = (
                    "same selector contains an earlier full window "
                    f"at offset {overlap.old_in_new_offset}"
                )
        elif (
            overlap.classification == "partial_overlap"
            and overlap.best_run_old_offset == 0
            and overlap.best_run_new_offset is not None
        ):
            status = "trimmed_stitch_candidate"
            reason = (
                "newer capture keeps the earlier prefix at "
                f"offset {overlap.best_run_new_offset} and trims the oldest tail"
            )
        elif overlap.classification == "partial_overlap":
            status = "caution"
            reason = (
                "long overlap exists, but the aligned run starts at old offset "
                f"{overlap.best_run_old_offset}"
            )
        else:
            status = "unknown"
            reason = f"overlap classification is {overlap.classification}"
        recommendations.append(
            {
                "selector": overlap.selector,
                "status": status,
                "reason": reason,
            }
        )
        seen.add(overlap.selector)
    return recommendations
