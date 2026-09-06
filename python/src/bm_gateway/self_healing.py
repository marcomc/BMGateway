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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .config import AppConfig

ConnectivityChecker = Callable[[str, str], bool]
ReconnectAction = Callable[[str], bool]
RebootAction = Callable[[], None]
USBOTGHealthChecker = Callable[[str, str], "USBOTGHealth"]
USBOTGRebindAction = Callable[[str, str], bool]
USBOTGStateCheckpoint = Callable[[], None]
_USB_OTG_HELPER_PATH = "/usr/local/bin/bm-gateway-usb-otg-frame-test"
_USB_OTG_CONFIGFS_ROOT = Path("/sys/kernel/config")
_USB_OTG_UDC_ROOT = Path("/sys/class/udc")


class USBOTGWatchdogStateError(RuntimeError):
    """The USB OTG watchdog recovery state cannot be safely used."""


@dataclass
class SelfHealingState:
    started_monotonic: float
    wifi_outage_started_monotonic: float | None = None
    wifi_reconnect_attempted: bool = False
    wifi_reboot_requested: bool = False
    periodic_reboot_requested: bool = False
    usb_otg_rebind_attempted: bool = False
    usb_otg_reboot_attempts_used: int = 0
    usb_otg_escalated: bool = False
    usb_otg_escalation_notification_pending: bool = False
    usb_otg_escalation_id: str = ""
    usb_otg_escalation_reason: str = ""
    usb_otg_escalation_reboot_attempts: int = 0


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
) -> list[SelfHealingEvent]:
    now = time.monotonic() if now_monotonic is None else now_monotonic
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
    else:
        if connectivity_checker(healing.connectivity_check_host, healing.wifi_interface):
            if state.wifi_outage_started_monotonic is not None:
                events.append(
                    SelfHealingEvent(
                        action="wifi_connectivity_restored",
                        status="completed",
                        details={
                            "connectivity_check_host": healing.connectivity_check_host,
                            "outage_seconds": int(now - state.wifi_outage_started_monotonic),
                        },
                    )
                )
            state.wifi_outage_started_monotonic = None
            state.wifi_reconnect_attempted = False
            state.wifi_reboot_requested = False
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
                outage_seconds = now - state.wifi_outage_started_monotonic
                if (
                    healing.wifi_reconnect_enabled
                    and not state.wifi_reconnect_attempted
                    and outage_seconds >= healing.wifi_reconnect_after_minutes * 60
                ):
                    state.wifi_reconnect_attempted = True
                    reconnected = reconnect_action(healing.wifi_interface)
                    events.append(
                        SelfHealingEvent(
                            action="wifi_reconnect_attempted",
                            status="completed" if reconnected else "failed",
                            details={
                                "wifi_interface": healing.wifi_interface,
                                "outage_seconds": int(outage_seconds),
                            },
                        )
                    )

                if (
                    healing.wifi_reboot_enabled
                    and not state.wifi_reboot_requested
                    and outage_seconds >= healing.wifi_reboot_after_minutes * 60
                ):
                    state.wifi_reboot_requested = True
                    reboot_action()
                    events.append(
                        SelfHealingEvent(
                            action="wifi_reboot_requested",
                            status="completed",
                            details={
                                "wifi_interface": healing.wifi_interface,
                                "connectivity_check_host": healing.connectivity_check_host,
                                "outage_seconds": int(outage_seconds),
                            },
                        )
                    )

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
