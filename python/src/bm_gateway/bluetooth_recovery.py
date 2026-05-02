"""Bluetooth transport failure detection and host recovery helpers."""

from __future__ import annotations

import re
import shutil
import subprocess

_FATAL_ERROR_SUBSTRINGS = (
    "Client tried to send a message other than Hello without being registered",
    "No Bluetooth adapters found.",
    "Bad file descriptor",
)
_FATAL_ERROR_CLASS_NAMES = {
    "BleakBluetoothNotAvailableError",
}
_ADAPTER_NOT_FOUND_PATTERN = re.compile(r"""adapter ['"][^'"]+['"] not found""")


class BluetoothRecoveryRequiredError(RuntimeError):
    """Raised when BLE transport corruption requires service recovery."""

    def __init__(
        self,
        *,
        error: BaseException,
        recovery_attempted: bool,
        recovery_detail: str | None = None,
    ) -> None:
        self.error = error
        self.recovery_attempted = recovery_attempted
        self.recovery_detail = recovery_detail
        detail = f": {recovery_detail}" if recovery_detail else ""
        super().__init__(f"Bluetooth recovery required after {error.__class__.__name__}{detail}")


def _iter_exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        next_error = current.__cause__ or current.__context__
        current = next_error if isinstance(next_error, BaseException) else None
    return chain


def is_fatal_bluetooth_error(error: BaseException) -> bool:
    for item in _iter_exception_chain(error):
        if item.__class__.__name__ in _FATAL_ERROR_CLASS_NAMES:
            return True
        message = str(item)
        if _ADAPTER_NOT_FOUND_PATTERN.search(message):
            return True
        if any(fragment in message for fragment in _FATAL_ERROR_SUBSTRINGS):
            return True
    return False


def restart_bluetooth_service() -> subprocess.CompletedProcess[str] | None:
    if shutil.which("sudo") is None or shutil.which("systemctl") is None:
        return None
    return subprocess.run(
        ["sudo", "-n", "systemctl", "restart", "bluetooth.service"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def require_bluetooth_recovery(error: BaseException) -> None:
    result = restart_bluetooth_service()
    detail: str | None = None
    attempted = result is not None
    if result is not None:
        detail_parts = []
        if result.returncode != 0:
            detail_parts.append(f"restart exit {result.returncode}")
        if result.stderr.strip():
            detail_parts.append(result.stderr.strip())
        if detail_parts:
            detail = "; ".join(detail_parts)
    raise BluetoothRecoveryRequiredError(
        error=error,
        recovery_attempted=attempted,
        recovery_detail=detail,
    )
