"""Runtime self-healing policies for appliance recovery."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .config import AppConfig

ConnectivityChecker = Callable[[str, str], bool]
ReconnectAction = Callable[[str], bool]
RebootAction = Callable[[], None]


@dataclass
class SelfHealingState:
    started_monotonic: float
    wifi_outage_started_monotonic: float | None = None
    wifi_reconnect_attempted: bool = False
    wifi_reboot_requested: bool = False
    periodic_reboot_requested: bool = False


@dataclass(frozen=True)
class SelfHealingEvent:
    action: str
    status: str
    details: dict[str, object]


def new_self_healing_state(now_monotonic: float | None = None) -> SelfHealingState:
    return SelfHealingState(
        started_monotonic=time.monotonic() if now_monotonic is None else now_monotonic
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


def evaluate_self_healing(
    *,
    config: AppConfig,
    state: SelfHealingState,
    now_monotonic: float | None = None,
    connectivity_checker: ConnectivityChecker = default_connectivity_checker,
    reconnect_action: ReconnectAction = default_wifi_reconnect,
    reboot_action: RebootAction = default_schedule_reboot,
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
        return events

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
        return events

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
        return events

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

    return events
