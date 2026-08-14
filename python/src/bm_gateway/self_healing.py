"""Runtime self-healing policies for appliance recovery."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator

from .config import AppConfig

ConnectivityChecker = Callable[[str, str], bool]
ReconnectAction = Callable[[str], bool]
USBOTGHealthChecker = Callable[[str, str], "USBOTGHealth"]
USBOTGRebindAction = Callable[[str, str], bool]
USBOTGStateCheckpoint = Callable[[], None]
_USB_OTG_HELPER_PATH = "/usr/local/bin/bm-gateway-usb-otg-frame-test"
_USB_OTG_CONFIGFS_ROOT = Path("/sys/kernel/config")
_USB_OTG_UDC_ROOT = Path("/sys/class/udc")


class USBOTGWatchdogStateError(RuntimeError):
    """The USB OTG watchdog recovery state cannot be safely used."""


class WiFiWatchdogStateError(RuntimeError):
    """The Wi-Fi watchdog recovery state cannot be safely used."""


@dataclass
class SelfHealingState:
    started_monotonic: float
    wifi_outage_started_monotonic: float | None = None
    wifi_reconnect_attempted: bool = False
    wifi_reboot_requested: bool = False
    wifi_recovery_pending: bool = False
    wifi_recovery_outage_seconds: int = 0
    wifi_recovery_interface: str = ""
    wifi_recovery_started_at: float = 0.0
    wifi_recovery_handoff_id: str = ""
    wifi_recovery_phase: str = ""
    periodic_reboot_requested: bool = False
    usb_otg_rebind_attempted: bool = False
    usb_otg_reboot_attempts_used: int = 0
    usb_otg_escalated: bool = False


@dataclass(frozen=True)
class USBOTGHealth:
    healthy: bool
    reason: str
    udc_name: str | None
    udc_state: str | None


@dataclass(frozen=True)
class SelfHealingEvent:
    action: str
    status: str
    details: dict[str, object]


def new_self_healing_state(now_monotonic: float | None = None) -> SelfHealingState:
    return SelfHealingState(
        started_monotonic=time.monotonic() if now_monotonic is None else now_monotonic
    )


def usb_otg_watchdog_state_path(state_dir: Path) -> Path:
    return state_dir / "runtime" / "usb_otg_watchdog_state.json"


def wifi_watchdog_state_path(state_dir: Path) -> Path:
    return state_dir / "runtime" / "wifi_watchdog_state.json"


@contextmanager
def locked_wifi_recovery_state(path: Path) -> Iterator[SelfHealingState]:
    """Yield the current durable recovery state while holding its exclusive lock."""
    lock_handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current = new_self_healing_state()
        load_wifi_watchdog_state(path, current)
        yield current
    except OSError as error:
        raise WiFiWatchdogStateError("Cannot lock Wi-Fi watchdog state") from error
    finally:
        if lock_handle is not None:
            lock_handle.close()


def _persist_watchdog_json(
    path: Path,
    payload: dict[str, object],
    error_type: type[USBOTGWatchdogStateError] | type[WiFiWatchdogStateError],
    error_message: str,
) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(json.dumps(payload, sort_keys=True) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise error_type(error_message) from error


def load_wifi_watchdog_state(path: Path, state: SelfHealingState) -> None:
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except OSError as error:
        raise WiFiWatchdogStateError("Cannot read Wi-Fi watchdog state") from error
    try:
        raw = json.loads(payload)
        recovery_pending = raw["recovery_pending"]
        outage_seconds = raw["outage_seconds"]
        wifi_interface = raw["wifi_interface"]
        recovery_started_at = raw.get("recovery_started_at", 0.0)
        recovery_handoff_id = raw.get("recovery_handoff_id", "")
        recovery_phase = raw.get("recovery_phase", "")
        if recovery_pending and not recovery_phase:
            recovery_phase = "pending"
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise WiFiWatchdogStateError("Wi-Fi watchdog state is invalid") from error
    if (
        not isinstance(recovery_pending, bool)
        or not isinstance(outage_seconds, int)
        or outage_seconds < 0
        or not isinstance(wifi_interface, str)
        or isinstance(recovery_started_at, bool)
        or not isinstance(recovery_started_at, (int, float))
        or recovery_started_at < 0
        or not isinstance(recovery_handoff_id, str)
        or recovery_phase not in {"", "pending", "reboot_authorized"}
    ):
        raise WiFiWatchdogStateError("Wi-Fi watchdog state has invalid values")
    state.wifi_recovery_pending = recovery_pending
    state.wifi_recovery_outage_seconds = outage_seconds
    state.wifi_recovery_interface = wifi_interface
    state.wifi_recovery_started_at = float(recovery_started_at)
    state.wifi_recovery_handoff_id = recovery_handoff_id
    state.wifi_recovery_phase = recovery_phase


def persist_wifi_watchdog_state(
    path: Path,
    state: SelfHealingState,
    *,
    preserve_pending: bool = True,
) -> None:
    lock_handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        payload: dict[str, object] = {
            "recovery_pending": state.wifi_recovery_pending,
            "outage_seconds": state.wifi_recovery_outage_seconds,
            "wifi_interface": state.wifi_recovery_interface,
            "recovery_started_at": state.wifi_recovery_started_at,
            "recovery_handoff_id": state.wifi_recovery_handoff_id,
            "recovery_phase": state.wifi_recovery_phase,
        }
        if preserve_pending:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                current = None
            if isinstance(current, dict) and current.get("recovery_pending") is True:
                payload = current
        _persist_watchdog_json(
            path,
            payload,
            WiFiWatchdogStateError,
            "Cannot persist Wi-Fi watchdog state",
        )
    except OSError as error:
        raise WiFiWatchdogStateError("Cannot lock Wi-Fi watchdog state") from error
    finally:
        if lock_handle is not None:
            lock_handle.close()


def clear_wifi_recovery_handoff(path: Path, state: SelfHealingState) -> bool:
    """Clear a persisted recovery handoff under its state lock when present."""
    lock_handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current = new_self_healing_state()
        load_wifi_watchdog_state(path, current)
        if not current.wifi_recovery_pending or current.wifi_recovery_phase == "reboot_authorized":
            return False
        _persist_watchdog_json(
            path,
            {
                "recovery_pending": False,
                "outage_seconds": 0,
                "wifi_interface": "",
                "recovery_started_at": 0.0,
                "recovery_handoff_id": "",
                "recovery_phase": "",
            },
            WiFiWatchdogStateError,
            "Cannot persist Wi-Fi watchdog state",
        )
    except OSError as error:
        raise WiFiWatchdogStateError("Cannot lock Wi-Fi watchdog state") from error
    finally:
        if lock_handle is not None:
            lock_handle.close()
    state.wifi_recovery_pending = False
    state.wifi_recovery_outage_seconds = 0
    state.wifi_recovery_interface = ""
    state.wifi_recovery_started_at = 0.0
    state.wifi_recovery_handoff_id = ""
    state.wifi_recovery_phase = ""
    return True


def consume_wifi_recovery_notification(
    path: Path,
    state: SelfHealingState,
    enqueue: Callable[[SelfHealingState], None],
) -> bool:
    """Queue and acknowledge one persisted recovery handoff under its state lock."""
    lock_handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current = new_self_healing_state()
        load_wifi_watchdog_state(path, current)
        if not current.wifi_recovery_pending:
            state.wifi_recovery_pending = False
            state.wifi_recovery_outage_seconds = 0
            state.wifi_recovery_interface = ""
            state.wifi_recovery_started_at = 0.0
            state.wifi_recovery_handoff_id = ""
            state.wifi_recovery_phase = ""
            return False
        if not current.wifi_recovery_handoff_id:
            current.wifi_recovery_handoff_id = uuid.uuid4().hex
            _persist_watchdog_json(
                path,
                {
                    "recovery_pending": True,
                    "outage_seconds": current.wifi_recovery_outage_seconds,
                    "wifi_interface": current.wifi_recovery_interface,
                    "recovery_started_at": current.wifi_recovery_started_at,
                    "recovery_handoff_id": current.wifi_recovery_handoff_id,
                    "recovery_phase": current.wifi_recovery_phase,
                },
                WiFiWatchdogStateError,
                "Cannot persist Wi-Fi watchdog state",
            )
        enqueue(current)
        acknowledged = replace(
            current,
            wifi_recovery_pending=False,
            wifi_recovery_outage_seconds=0,
            wifi_recovery_interface="",
            wifi_recovery_started_at=0.0,
            wifi_recovery_handoff_id="",
            wifi_recovery_phase="",
        )
        _persist_watchdog_json(
            path,
            {
                "recovery_pending": False,
                "outage_seconds": 0,
                "wifi_interface": "",
                "recovery_started_at": 0.0,
                "recovery_handoff_id": "",
                "recovery_phase": "",
            },
            WiFiWatchdogStateError,
            "Cannot persist Wi-Fi watchdog state",
        )
    except OSError as error:
        raise WiFiWatchdogStateError("Cannot lock Wi-Fi watchdog state") from error
    finally:
        if lock_handle is not None:
            lock_handle.close()
    state.wifi_recovery_pending = acknowledged.wifi_recovery_pending
    state.wifi_recovery_outage_seconds = acknowledged.wifi_recovery_outage_seconds
    state.wifi_recovery_interface = acknowledged.wifi_recovery_interface
    state.wifi_recovery_started_at = acknowledged.wifi_recovery_started_at
    state.wifi_recovery_handoff_id = acknowledged.wifi_recovery_handoff_id
    state.wifi_recovery_phase = acknowledged.wifi_recovery_phase
    return True


def load_usb_otg_watchdog_state(path: Path, state: SelfHealingState) -> None:
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except OSError as error:
        raise USBOTGWatchdogStateError("Cannot read USB OTG watchdog state") from error
    try:
        raw = json.loads(payload)
        rebind_attempted = raw["rebind_attempted"]
        reboot_attempts_used = raw["reboot_attempts_used"]
        escalated = raw["escalated"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise USBOTGWatchdogStateError("USB OTG watchdog state is invalid") from error
    if (
        not isinstance(rebind_attempted, bool)
        or not isinstance(reboot_attempts_used, int)
        or reboot_attempts_used < 0
        or not isinstance(escalated, bool)
    ):
        raise USBOTGWatchdogStateError("USB OTG watchdog state has invalid values")
    state.usb_otg_rebind_attempted = rebind_attempted
    state.usb_otg_reboot_attempts_used = reboot_attempts_used
    state.usb_otg_escalated = escalated


def persist_usb_otg_watchdog_state(path: Path, state: SelfHealingState) -> None:
    _persist_watchdog_json(
        path,
        {
            "rebind_attempted": state.usb_otg_rebind_attempted,
            "reboot_attempts_used": state.usb_otg_reboot_attempts_used,
            "escalated": state.usb_otg_escalated,
        },
        USBOTGWatchdogStateError,
        "Cannot persist USB OTG watchdog state",
    )


def default_connectivity_checker(host: str, interface: str) -> bool:
    if shutil.which("ping") is None:
        return True
    command = ["ping", "-c", "1", "-W", "3"]
    if interface.strip():
        command.extend(["-I", interface])
    command.append(host)
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def default_wifi_reconnect(interface: str) -> bool:
    if shutil.which("nmcli") is not None:
        radio = subprocess.run(
            ["sudo", "-n", "nmcli", "radio", "wifi", "on"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        connect = subprocess.run(
            ["sudo", "-n", "nmcli", "device", "connect", interface],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return radio.returncode == 0 and connect.returncode == 0

    for service_name in ("NetworkManager.service", "wpa_supplicant.service"):
        completed = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", service_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return True
    return False


def default_schedule_reboot() -> None:
    subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-lc", "sleep 1 && sudo -n systemctl reboot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def default_usb_otg_health_check(
    image_path: str,
    gadget_name: str,
    *,
    configfs_root: Path = _USB_OTG_CONFIGFS_ROOT,
    udc_root: Path = _USB_OTG_UDC_ROOT,
) -> USBOTGHealth:
    image = Path(image_path)
    if not image.is_file():
        return USBOTGHealth(False, "USB OTG backing image is missing", None, None)

    gadget_path = configfs_root / "usb_gadget" / gadget_name
    udc_path = gadget_path / "UDC"
    if not udc_path.is_file():
        return USBOTGHealth(False, "USB OTG gadget is not configured", None, None)

    try:
        udc_name = udc_path.read_text(encoding="utf-8").strip()
    except OSError:
        return USBOTGHealth(False, "USB OTG gadget status is unreadable", None, None)
    if not udc_name:
        return USBOTGHealth(False, "USB OTG gadget is detached", None, None)

    state_path = udc_root / udc_name / "state"
    try:
        udc_state = state_path.read_text(encoding="utf-8").strip()
    except OSError:
        return USBOTGHealth(False, "USB OTG controller state is unreadable", udc_name, None)
    if udc_state != "configured":
        return USBOTGHealth(False, "UDC state is not configured", udc_name, udc_state)
    return USBOTGHealth(True, "", udc_name, udc_state)


def default_usb_otg_rebind(image_path: str, gadget_name: str) -> bool:
    completed = subprocess.run(
        [
            "sudo",
            "-n",
            _USB_OTG_HELPER_PATH,
            "refresh",
            "--image-path",
            image_path,
            "--gadget-name",
            gadget_name,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def evaluate_self_healing(
    *,
    config: AppConfig,
    state: SelfHealingState,
    now_monotonic: float | None = None,
    connectivity_checker: ConnectivityChecker = default_connectivity_checker,
    reconnect_action: ReconnectAction = default_wifi_reconnect,
    usb_otg_health_checker: USBOTGHealthChecker = default_usb_otg_health_check,
    usb_otg_rebind_action: USBOTGRebindAction = default_usb_otg_rebind,
    usb_otg_state_checkpoint: USBOTGStateCheckpoint | None = None,
    now_wall_time: float | None = None,
) -> list[SelfHealingEvent]:
    now = time.monotonic() if now_monotonic is None else now_monotonic
    wall_time = time.time() if now_wall_time is None else now_wall_time
    events: list[SelfHealingEvent] = []
    healing = config.self_healing

    if healing.periodic_reboot_enabled and not state.periodic_reboot_requested:
        elapsed_seconds = now - state.started_monotonic
        threshold_seconds = healing.periodic_reboot_hours * 3600
        if elapsed_seconds >= threshold_seconds:
            state.periodic_reboot_requested = True
            events.append(
                SelfHealingEvent(
                    action="periodic_reboot_requested",
                    status="completed",
                    details={
                        "periodic_reboot_hours": healing.periodic_reboot_hours,
                        "elapsed_seconds": int(elapsed_seconds),
                    },
                )
            )

    if not healing.wifi_watchdog_enabled:
        state.wifi_outage_started_monotonic = None
        state.wifi_reconnect_attempted = False
        state.wifi_reboot_requested = False
        state.wifi_recovery_pending = False
        state.wifi_recovery_outage_seconds = 0
        state.wifi_recovery_interface = ""
        state.wifi_recovery_started_at = 0.0
        state.wifi_recovery_handoff_id = ""
        state.wifi_recovery_phase = ""
    else:
        if connectivity_checker(healing.connectivity_check_host, healing.wifi_interface):
            if state.wifi_outage_started_monotonic is not None or state.wifi_recovery_pending:
                outage_seconds = state.wifi_recovery_outage_seconds
                if not state.wifi_recovery_pending:
                    assert state.wifi_outage_started_monotonic is not None
                    outage_seconds = int(now - state.wifi_outage_started_monotonic)
                elif state.wifi_recovery_started_at > 0:
                    outage_seconds = max(
                        outage_seconds,
                        int(wall_time - state.wifi_recovery_started_at),
                    )
                events.append(
                    SelfHealingEvent(
                        action="wifi_connectivity_restored",
                        status="completed",
                        details={
                            "connectivity_check_host": healing.connectivity_check_host,
                            "outage_seconds": outage_seconds,
                        },
                    )
                )
            state.wifi_outage_started_monotonic = None
            state.wifi_reconnect_attempted = False
            state.wifi_reboot_requested = False
            if not state.wifi_recovery_pending:
                state.wifi_recovery_outage_seconds = 0
                state.wifi_recovery_interface = ""
                state.wifi_recovery_started_at = 0.0
                state.wifi_recovery_handoff_id = ""
                state.wifi_recovery_phase = ""
        else:
            if state.wifi_outage_started_monotonic is None:
                state.wifi_outage_started_monotonic = now
                events.append(
                    SelfHealingEvent(
                        action="wifi_connectivity_lost",
                        status="failed",
                        details={
                            "connectivity_check_host": healing.connectivity_check_host,
                            "wifi_interface": healing.wifi_interface,
                        },
                    )
                )
            else:
                outage_duration = now - state.wifi_outage_started_monotonic
                reconnected = False
                if (
                    healing.wifi_reconnect_enabled
                    and not state.wifi_reconnect_attempted
                    and outage_duration >= healing.wifi_reconnect_after_minutes * 60
                ):
                    state.wifi_reconnect_attempted = True
                    reconnected = reconnect_action(healing.wifi_interface)
                    if reconnected:
                        reconnected = connectivity_checker(
                            healing.connectivity_check_host,
                            healing.wifi_interface,
                        )
                    events.append(
                        SelfHealingEvent(
                            action="wifi_reconnect_attempted",
                            status="completed" if reconnected else "failed",
                            details={
                                "wifi_interface": healing.wifi_interface,
                                "outage_seconds": int(outage_duration),
                            },
                        )
                    )

                if (
                    healing.wifi_reboot_enabled
                    and not state.wifi_reboot_requested
                    and not reconnected
                    and outage_duration >= healing.wifi_reboot_after_minutes * 60
                ):
                    was_recovery_pending = state.wifi_recovery_pending
                    state.wifi_reboot_requested = True
                    state.wifi_recovery_pending = True
                    state.wifi_recovery_outage_seconds = int(outage_duration)
                    state.wifi_recovery_interface = healing.wifi_interface
                    if not was_recovery_pending:
                        state.wifi_recovery_started_at = wall_time - outage_duration
                        state.wifi_recovery_handoff_id = uuid.uuid4().hex
                    state.wifi_recovery_phase = "reboot_authorized"
                    events.append(
                        SelfHealingEvent(
                            action="wifi_reboot_requested",
                            status="completed",
                            details={
                                "wifi_interface": healing.wifi_interface,
                                "connectivity_check_host": healing.connectivity_check_host,
                                "outage_seconds": int(outage_duration),
                            },
                        )
                    )

    if not healing.usb_otg_watchdog_enabled:
        state.usb_otg_rebind_attempted = False
        state.usb_otg_reboot_attempts_used = 0
        state.usb_otg_escalated = False
        return events

    health = usb_otg_health_checker(config.usb_otg.image_path, config.usb_otg.gadget_name)
    if health.healthy:
        if state.usb_otg_rebind_attempted or state.usb_otg_reboot_attempts_used:
            events.append(
                SelfHealingEvent(
                    action="usb_otg_enumeration_restored",
                    status="completed",
                    details={"udc_name": health.udc_name, "udc_state": health.udc_state},
                )
            )
        state.usb_otg_rebind_attempted = False
        state.usb_otg_reboot_attempts_used = 0
        state.usb_otg_escalated = False
        return events

    details: dict[str, object] = {
        "reason": health.reason,
        "udc_name": health.udc_name,
        "udc_state": health.udc_state,
    }
    if not state.usb_otg_rebind_attempted:
        state.usb_otg_rebind_attempted = True
        if usb_otg_state_checkpoint is not None:
            try:
                usb_otg_state_checkpoint()
            except USBOTGWatchdogStateError as error:
                state.usb_otg_rebind_attempted = False
                events.append(
                    SelfHealingEvent(
                        action="usb_otg_watchdog_state_persist_failed",
                        status="failed",
                        details={"reason": str(error)},
                    )
                )
                return events
        rebound = usb_otg_rebind_action(config.usb_otg.image_path, config.usb_otg.gadget_name)
        events.extend(
            [
                SelfHealingEvent(action="usb_otg_not_enumerated", status="failed", details=details),
                SelfHealingEvent(
                    action="usb_otg_rebind_attempted",
                    status="completed" if rebound else "failed",
                    details=details,
                ),
            ]
        )
        return events

    if (
        healing.usb_otg_reboot_enabled
        and state.usb_otg_reboot_attempts_used < healing.usb_otg_reboot_attempts
    ):
        state.usb_otg_reboot_attempts_used += 1
        if usb_otg_state_checkpoint is not None:
            try:
                usb_otg_state_checkpoint()
            except USBOTGWatchdogStateError as error:
                state.usb_otg_reboot_attempts_used -= 1
                events.append(
                    SelfHealingEvent(
                        action="usb_otg_watchdog_state_persist_failed",
                        status="failed",
                        details={"reason": str(error)},
                    )
                )
                return events
        events.append(
            SelfHealingEvent(
                action="usb_otg_reboot_requested",
                status="completed",
                details={**details, "attempt": state.usb_otg_reboot_attempts_used},
            )
        )
        return events

    if not state.usb_otg_escalated:
        state.usb_otg_escalated = True
        events.append(
            SelfHealingEvent(
                action="usb_otg_recovery_exhausted",
                status="failed",
                details={**details, "reboot_attempts": state.usb_otg_reboot_attempts_used},
            )
        )

    return events
