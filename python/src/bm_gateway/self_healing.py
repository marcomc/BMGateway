"""Runtime self-healing policies for appliance recovery."""

from __future__ import annotations

import fcntl
import json
import math
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
from .localization import translation_for

ConnectivityChecker = Callable[[str, str], bool]
ReconnectAction = Callable[[str], bool]
RebootAction = Callable[[], None]
USBOTGHealthChecker = Callable[[str, str], "USBOTGHealth"]
USBOTGRebindAction = Callable[[str, str], bool]
USBOTGStateCheckpoint = Callable[[], None]
USBOTGBootIDReader = Callable[[], str]
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
    usb_otg_escalation_notification_pending: bool = False
    usb_otg_escalation_id: str = ""
    usb_otg_escalation_reason: str = ""
    usb_otg_escalation_reboot_attempts: int = 0
    usb_otg_pending_action: str = ""
    usb_otg_pending_reboot_boot_id: str = ""


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
    try:
        recovery_started_at_float = float(recovery_started_at)
    except (OverflowError, TypeError, ValueError):
        raise WiFiWatchdogStateError("Wi-Fi watchdog state has invalid values") from None
    if (
        not isinstance(recovery_pending, bool)
        or not isinstance(outage_seconds, int)
        or outage_seconds < 0
        or not isinstance(wifi_interface, str)
        or isinstance(recovery_started_at, bool)
        or not isinstance(recovery_started_at, (int, float))
        or not math.isfinite(recovery_started_at_float)
        or recovery_started_at_float < 0
        or not isinstance(recovery_handoff_id, str)
        or recovery_phase not in {"", "pending", "reconnect_pending", "reboot_authorized"}
    ):
        raise WiFiWatchdogStateError("Wi-Fi watchdog state has invalid values")
    state.wifi_recovery_pending = recovery_pending
    state.wifi_recovery_outage_seconds = outage_seconds
    state.wifi_recovery_interface = wifi_interface
    state.wifi_recovery_started_at = recovery_started_at_float
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
            except json.JSONDecodeError as error:
                raise WiFiWatchdogStateError("Wi-Fi watchdog state is invalid") from error
            if (
                isinstance(current, dict)
                and current.get("recovery_pending") is True
                and state.wifi_recovery_phase != "reboot_authorized"
            ):
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


def clear_wifi_recovery_handoff(
    path: Path, state: SelfHealingState, *, force: bool = False
) -> bool:
    """Clear a persisted Wi-Fi recovery handoff while holding its lock."""
    lock_handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current = new_self_healing_state()
        load_wifi_watchdog_state(path, current)
        if not current.wifi_recovery_pending or (
            current.wifi_recovery_phase == "reboot_authorized" and not force
        ):
            if current.wifi_recovery_pending:
                _copy_wifi_recovery_state(current, state)
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
    _clear_wifi_recovery_state(state)
    return True


def consume_wifi_recovery_notification(
    path: Path,
    state: SelfHealingState,
    enqueue: Callable[[SelfHealingState], None],
) -> bool:
    """Queue and acknowledge one persisted Wi-Fi recovery handoff atomically."""
    lock_handle = None
    acknowledged: SelfHealingState | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current = new_self_healing_state()
        load_wifi_watchdog_state(path, current)
        if not current.wifi_recovery_pending:
            _clear_wifi_recovery_state(state)
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
    if acknowledged is not None:
        _copy_wifi_recovery_state(acknowledged, state)
    return acknowledged is not None


def _copy_wifi_recovery_state(source: SelfHealingState, target: SelfHealingState) -> None:
    for name in (
        "wifi_recovery_pending",
        "wifi_recovery_outage_seconds",
        "wifi_recovery_interface",
        "wifi_recovery_started_at",
        "wifi_recovery_handoff_id",
        "wifi_recovery_phase",
    ):
        setattr(target, name, getattr(source, name))


def _clear_wifi_recovery_state(state: SelfHealingState) -> None:
    state.wifi_recovery_pending = False
    state.wifi_recovery_outage_seconds = 0
    state.wifi_recovery_interface = ""
    state.wifi_recovery_started_at = 0.0
    state.wifi_recovery_handoff_id = ""
    state.wifi_recovery_phase = ""


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
        pending_action = raw.get("pending_action", "")
        pending_boot_id = raw.get("pending_reboot_boot_id", "")
        escalation_notification_pending = raw.get("escalation_notification_pending", False)
        escalation_id = raw.get("escalation_id", "")
        escalation_reason = raw.get("escalation_reason", "")
        escalation_reboot_attempts = raw.get("escalation_reboot_attempts", reboot_attempts_used)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise USBOTGWatchdogStateError("USB OTG watchdog state is invalid") from error
    if (
        not isinstance(rebind_attempted, bool)
        or not isinstance(reboot_attempts_used, int)
        or reboot_attempts_used < 0
        or not isinstance(escalated, bool)
        or pending_action not in ("", "rebind", "reboot")
        or not isinstance(pending_boot_id, str)
        or (pending_action == "reboot" and not pending_boot_id.strip())
        or (pending_action != "reboot" and bool(pending_boot_id))
        or (bool(pending_action) and not rebind_attempted)
        or (pending_action == "reboot" and reboot_attempts_used == 0)
        or (bool(pending_action) and escalation_notification_pending)
        or not isinstance(escalation_notification_pending, bool)
        or not isinstance(escalation_id, str)
        or not isinstance(escalation_reason, str)
        or not isinstance(escalation_reboot_attempts, int)
        or escalation_reboot_attempts < 0
    ):
        raise USBOTGWatchdogStateError("USB OTG watchdog state has invalid values")
    state.usb_otg_rebind_attempted = rebind_attempted
    state.usb_otg_reboot_attempts_used = reboot_attempts_used
    state.usb_otg_escalated = escalated
    state.usb_otg_pending_action = pending_action
    state.usb_otg_pending_reboot_boot_id = pending_boot_id
    state.usb_otg_escalation_notification_pending = escalation_notification_pending
    state.usb_otg_escalation_id = escalation_id
    state.usb_otg_escalation_reason = escalation_reason
    state.usb_otg_escalation_reboot_attempts = escalation_reboot_attempts


def persist_usb_otg_watchdog_state(path: Path, state: SelfHealingState) -> None:
    payload = (
        json.dumps(
            {
                "rebind_attempted": state.usb_otg_rebind_attempted,
                "reboot_attempts_used": state.usb_otg_reboot_attempts_used,
                "escalated": state.usb_otg_escalated,
                "pending_action": state.usb_otg_pending_action,
                "pending_reboot_boot_id": state.usb_otg_pending_reboot_boot_id,
                "escalation_notification_pending": state.usb_otg_escalation_notification_pending,
                "escalation_id": state.usb_otg_escalation_id,
                "escalation_reason": state.usb_otg_escalation_reason,
                "escalation_reboot_attempts": state.usb_otg_escalation_reboot_attempts,
            },
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(payload)
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
        raise USBOTGWatchdogStateError("Cannot persist USB OTG watchdog state") from error


@contextmanager
def usb_otg_watchdog_transaction(path: Path, state: SelfHealingState) -> Iterator[None]:
    """Serialize reload, evaluation, outbox acknowledgement and delivery.

    Always acquire this lock before the notification outbox lock. The runtime
    owns the entire transaction, including all state checkpoints and delivery.
    """
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = (path.parent / f".{path.name}.lock").open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError as error:
        if handle is not None:
            handle.close()
        raise USBOTGWatchdogStateError("Cannot lock USB OTG watchdog state") from error
    try:
        # Missing state also replaces a stale process-local cache.
        current = new_self_healing_state()
        load_usb_otg_watchdog_state(path, current)
        # A predecessor may have replaced JSON then failed directory fsync.
        # Establish durability before trusting an ACK observed from that file.
        try:
            with path.open("rb") as state_file:
                os.fsync(state_file.fileno())
        except FileNotFoundError:
            pass
        except OSError as error:
            raise USBOTGWatchdogStateError("Cannot persist USB OTG watchdog state") from error
        try:
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise USBOTGWatchdogStateError("Cannot persist USB OTG watchdog state") from error
        for name in vars(current):
            if name.startswith("usb_otg_"):
                setattr(state, name, getattr(current, name))
        yield
    finally:
        handle.close()


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


def default_usb_otg_boot_id() -> str:
    """Identify a Linux boot before reserving or resuming a USB reboot."""
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError as error:
        raise USBOTGWatchdogStateError("USB OTG reboot boot identity is unavailable") from error
    if not boot_id:
        raise USBOTGWatchdogStateError("USB OTG reboot boot identity is unavailable")
    return boot_id


def evaluate_self_healing(
    *,
    config: AppConfig,
    state: SelfHealingState,
    now_monotonic: float | None = None,
    connectivity_checker: ConnectivityChecker = default_connectivity_checker,
    reconnect_action: ReconnectAction = default_wifi_reconnect,
    reboot_action: RebootAction = default_schedule_reboot,
    usb_otg_health_checker: USBOTGHealthChecker = default_usb_otg_health_check,
    usb_otg_rebind_action: USBOTGRebindAction = default_usb_otg_rebind,
    usb_otg_state_checkpoint: USBOTGStateCheckpoint | None = None,
    usb_otg_boot_id_reader: USBOTGBootIDReader = default_usb_otg_boot_id,
    wifi_state_checkpoint: Callable[[], None] | None = None,
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
            reboot_action()
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
        _clear_wifi_recovery_state(state)
    else:
        if connectivity_checker(healing.connectivity_check_host, healing.wifi_interface):
            if state.wifi_outage_started_monotonic is not None or state.wifi_recovery_pending:
                outage_seconds = state.wifi_recovery_outage_seconds
                if not state.wifi_recovery_pending:
                    assert state.wifi_outage_started_monotonic is not None
                    outage_seconds = int(now - state.wifi_outage_started_monotonic)
                    state.wifi_recovery_pending = True
                    state.wifi_recovery_outage_seconds = outage_seconds
                    state.wifi_recovery_interface = healing.wifi_interface
                    state.wifi_recovery_started_at = wall_time - outage_seconds
                    state.wifi_recovery_handoff_id = uuid.uuid4().hex
                    state.wifi_recovery_phase = "pending"
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
                _clear_wifi_recovery_state(state)
        else:
            reboot_authorized = (
                state.wifi_recovery_pending and state.wifi_recovery_phase == "reboot_authorized"
            )
            if state.wifi_outage_started_monotonic is None:
                state.wifi_outage_started_monotonic = now
                if not state.wifi_recovery_pending:
                    state.wifi_recovery_pending = True
                    state.wifi_recovery_outage_seconds = 0
                    state.wifi_recovery_interface = healing.wifi_interface
                    state.wifi_recovery_started_at = wall_time
                    state.wifi_recovery_handoff_id = uuid.uuid4().hex
                    state.wifi_recovery_phase = "pending"
                elif reboot_authorized:
                    state.wifi_reboot_requested = True
                    events.append(
                        SelfHealingEvent(
                            action="wifi_reboot_requested",
                            status="completed",
                            details={
                                "wifi_interface": healing.wifi_interface,
                                "connectivity_check_host": healing.connectivity_check_host,
                                "outage_seconds": state.wifi_recovery_outage_seconds,
                            },
                        )
                    )
                if not reboot_authorized:
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
                reconnect_succeeded = False
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
                    reconnect_succeeded = reconnected
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
                    if reconnected:
                        state.wifi_recovery_pending = True
                        state.wifi_recovery_outage_seconds = int(outage_duration)
                        state.wifi_recovery_interface = healing.wifi_interface
                        if not state.wifi_recovery_handoff_id:
                            state.wifi_recovery_started_at = wall_time - outage_duration
                            state.wifi_recovery_handoff_id = uuid.uuid4().hex
                        state.wifi_recovery_phase = "reconnect_pending"
                        events.append(
                            SelfHealingEvent(
                                action="wifi_connectivity_restored",
                                status="completed",
                                details={
                                    "connectivity_check_host": healing.connectivity_check_host,
                                    "outage_seconds": int(outage_duration),
                                },
                            )
                        )
                        state.wifi_outage_started_monotonic = None
                        state.wifi_reconnect_attempted = False
                        state.wifi_reboot_requested = False

                if (
                    healing.wifi_reboot_enabled
                    and not state.wifi_reboot_requested
                    and not reconnect_succeeded
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

    def checkpoint_usb() -> bool:
        try:
            if usb_otg_state_checkpoint is not None:
                usb_otg_state_checkpoint()
        except USBOTGWatchdogStateError as error:
            events.append(
                SelfHealingEvent(
                    action="usb_otg_watchdog_state_persist_failed",
                    status="failed",
                    details={
                        "reason": translation_for(config.notifications.locale).gettext(str(error))
                    },
                )
            )
            return False
        return True

    if state.usb_otg_escalation_notification_pending:
        events.append(
            SelfHealingEvent(
                action="usb_otg_recovery_exhausted",
                status="failed",
                details={
                    "reason": state.usb_otg_escalation_reason,
                    "reboot_attempts": state.usb_otg_escalation_reboot_attempts,
                },
            )
        )

    if not healing.usb_otg_watchdog_enabled:
        state.usb_otg_rebind_attempted = False
        state.usb_otg_reboot_attempts_used = 0
        state.usb_otg_escalated = False
        state.usb_otg_pending_action = ""
        state.usb_otg_pending_reboot_boot_id = ""
        if not state.usb_otg_escalation_notification_pending:
            state.usb_otg_escalation_id = ""
            state.usb_otg_escalation_reason = ""
            state.usb_otg_escalation_reboot_attempts = 0
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
        state.usb_otg_pending_action = ""
        state.usb_otg_pending_reboot_boot_id = ""
        if not state.usb_otg_escalation_notification_pending:
            state.usb_otg_escalation_id = ""
            state.usb_otg_escalation_reason = ""
        return events

    details: dict[str, object] = {
        "reason": health.reason,
        "udc_name": health.udc_name,
        "udc_state": health.udc_state,
    }
    if state.usb_otg_escalation_notification_pending:
        return events
    if state.usb_otg_pending_action == "reboot" and (
        not healing.usb_otg_reboot_enabled
        or state.usb_otg_reboot_attempts_used > healing.usb_otg_reboot_attempts
    ):
        state.usb_otg_pending_action = ""
        state.usb_otg_pending_reboot_boot_id = ""

    if not state.usb_otg_rebind_attempted or state.usb_otg_pending_action == "rebind":
        state.usb_otg_rebind_attempted = True
        state.usb_otg_pending_action = "rebind"
        if not checkpoint_usb():
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
        state.usb_otg_pending_action = ""
        checkpoint_usb()
        return events

    if healing.usb_otg_reboot_enabled and (
        state.usb_otg_pending_action == "reboot"
        or state.usb_otg_reboot_attempts_used < healing.usb_otg_reboot_attempts
    ):
        try:
            boot_id = usb_otg_boot_id_reader()
            if not boot_id.strip():
                raise USBOTGWatchdogStateError("USB OTG reboot boot identity is unavailable")
        except USBOTGWatchdogStateError as error:
            events.append(
                SelfHealingEvent(
                    action="usb_otg_watchdog_state_unavailable",
                    status="failed",
                    details={
                        "reason": translation_for(config.notifications.locale).gettext(str(error))
                    },
                )
            )
            return events
        if (
            state.usb_otg_pending_action == "reboot"
            and state.usb_otg_pending_reboot_boot_id != boot_id
        ):
            state.usb_otg_pending_action = ""
            state.usb_otg_pending_reboot_boot_id = ""
        if (
            state.usb_otg_pending_action == "reboot"
            or state.usb_otg_reboot_attempts_used < healing.usb_otg_reboot_attempts
        ):
            if state.usb_otg_pending_action != "reboot":
                state.usb_otg_reboot_attempts_used += 1
                state.usb_otg_pending_action = "reboot"
                state.usb_otg_pending_reboot_boot_id = boot_id
            if not checkpoint_usb():
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
        state.usb_otg_escalation_notification_pending = True
        state.usb_otg_escalation_id = uuid.uuid4().hex
        state.usb_otg_escalation_reason = health.reason
        state.usb_otg_escalation_reboot_attempts = state.usb_otg_reboot_attempts_used
        events.append(
            SelfHealingEvent(
                action="usb_otg_recovery_exhausted",
                status="failed",
                details={**details, "reboot_attempts": state.usb_otg_reboot_attempts_used},
            )
        )

    return events
