"""Cross-process Bluetooth session locking."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Iterator, Mapping

from .config import AppConfig

DEFAULT_BLUETOOTH_LOCK_TIMEOUT_SECONDS = 600.0


class BluetoothOperationBusyError(RuntimeError):
    """Raised when another process is already using the Bluetooth session."""

    def __init__(
        self,
        *,
        operation: str,
        timeout_seconds: float,
        holder: Mapping[str, object] | None = None,
    ) -> None:
        detail = (
            f"Timed out waiting {timeout_seconds:.1f}s for Bluetooth session lock during "
            f"{operation}."
        )
        if holder:
            holder_operation = str(holder.get("operation") or "unknown")
            holder_pid = holder.get("pid")
            detail = f"{detail} Current holder: operation={holder_operation}, pid={holder_pid}."
        super().__init__(detail)
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        self.holder = dict(holder) if holder is not None else None


def bluetooth_lock_path(config: AppConfig, *, state_dir: Path | None = None) -> Path:
    base_dir = (
        state_dir
        if state_dir is not None
        else (config.source_path.parent / config.gateway.data_dir)
    )
    return base_dir / "runtime" / "bluetooth.lock"


def read_bluetooth_lock_holder(lock_path: Path) -> dict[str, object] | None:
    if not lock_path.exists():
        return None
    raw = lock_path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(payload, dict):
        return payload
    return {"raw": raw}


@contextmanager
def exclusive_bluetooth_operation(
    config: AppConfig,
    *,
    operation: str,
    state_dir: Path | None = None,
    timeout_seconds: float = DEFAULT_BLUETOOTH_LOCK_TIMEOUT_SECONDS,
    retry_interval_seconds: float = 0.25,
) -> Iterator[dict[str, object]]:
    lock_path = bluetooth_lock_path(config, state_dir=state_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    started = monotonic()
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                if monotonic() - started >= timeout_seconds:
                    raise BluetoothOperationBusyError(
                        operation=operation,
                        timeout_seconds=timeout_seconds,
                        holder=read_bluetooth_lock_holder(lock_path),
                    ) from exc
                sleep(retry_interval_seconds)

        payload = {
            "pid": os.getpid(),
            "operation": operation,
            "acquired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        try:
            yield payload
        finally:
            handle.seek(0)
            handle.truncate()
            handle.flush()
            if acquired:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
