"""Host-level gateway alerts for Bluetooth and mDNS health."""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CommandRunner = Callable[[list[str], float], subprocess.CompletedProcess[str] | None]
_AVAHI_HOSTNAME_PATTERN = re.compile(r"Host name is ([A-Za-z0-9._-]+\.local)")
_DEFAULT_BLUETOOTH_SYSFS_ROOT = Path("/sys/class/bluetooth")
_DEFAULT_RFKILL_ROOT = Path("/sys/class/rfkill")


@dataclass(frozen=True)
class GatewayAlert:
    code: str
    severity: str
    runbook: str
    context: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "runbook": self.runbook,
            "context": dict(self.context),
        }


def _run_command(
    command: list[str],
    timeout_seconds: float = 5.0,
) -> subprocess.CompletedProcess[str] | None:
    if not command or shutil.which(command[0]) is None:
        return None
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _systemctl_state(unit: str, *, run_command: CommandRunner) -> str | None:
    result = run_command(["systemctl", "is-active", unit], 5.0)
    if result is None:
        return None
    state = result.stdout.strip()
    return state or None


def _bluetooth_controllers(sysfs_root: Path) -> list[str]:
    if not sysfs_root.exists():
        return []
    return [
        entry.name
        for entry in sorted(sysfs_root.iterdir())
        if entry.is_dir() and entry.name.startswith("hci")
    ]


def _bluetooth_rfkill_state(rfkill_root: Path) -> dict[str, dict[str, str]]:
    states: dict[str, dict[str, str]] = {}
    if not rfkill_root.exists():
        return states
    for entry in sorted(rfkill_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            adapter_type = (entry / "type").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if adapter_type != "bluetooth":
            continue
        try:
            controller = (entry / "name").read_text(encoding="utf-8").strip()
        except OSError:
            controller = ""
        if not controller:
            continue
        state = {
            "soft": "0",
            "hard": "0",
            "state": "1",
        }
        for key in ("soft", "hard", "state"):
            try:
                state[key] = (entry / key).read_text(encoding="utf-8").strip()
            except OSError:
                continue
        states[controller] = state
    return states


def _bluetoothctl_controller_state(*, run_command: CommandRunner) -> dict[str, str]:
    result = run_command(["bluetoothctl", "show"], 5.0)
    if result is None:
        return {}
    output = result.stdout
    state: dict[str, str] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Controller "):
            controller_summary = stripped.removeprefix("Controller ").strip()
            if controller_summary:
                state["controller"] = controller_summary.split()[0]
        elif stripped.startswith("Powered: "):
            state["powered"] = stripped.removeprefix("Powered: ").strip().lower()
        elif stripped.startswith("PowerState: "):
            state["power_state"] = stripped.removeprefix("PowerState: ").strip().lower()
    if result.returncode != 0 and not state:
        state["command_failed"] = "true"
    return state


def _collect_bluetooth_alerts(
    *,
    configured_adapter: str | None,
    bluetooth_sysfs_root: Path,
    rfkill_root: Path,
    run_command: CommandRunner,
) -> list[GatewayAlert]:
    controllers = _bluetooth_controllers(bluetooth_sysfs_root)
    if not controllers:
        return [
            GatewayAlert(
                code="bluetooth_controller_missing",
                severity="error",
                runbook="troubleshooting-bluetooth.md",
            )
        ]

    selected_controllers = controllers
    if configured_adapter and configured_adapter != "auto":
        if configured_adapter not in controllers:
            return [
                GatewayAlert(
                    code="bluetooth_controller_missing",
                    severity="error",
                    runbook="troubleshooting-bluetooth.md",
                    context={"controller": configured_adapter},
                )
            ]
        selected_controllers = [configured_adapter]
    controller_label = ",".join(selected_controllers or controllers)
    rfkill_states = _bluetooth_rfkill_state(rfkill_root)
    for controller in selected_controllers:
        state = rfkill_states.get(controller)
        if state is None:
            continue
        if state.get("hard") == "1":
            return [
                GatewayAlert(
                    code="bluetooth_hard_blocked",
                    severity="error",
                    runbook="troubleshooting-bluetooth.md",
                    context={"controller": controller},
                )
            ]
        if state.get("soft") == "1":
            return [
                GatewayAlert(
                    code="bluetooth_soft_blocked",
                    severity="error",
                    runbook="troubleshooting-bluetooth.md",
                    context={"controller": controller},
                )
            ]

    service_state = _systemctl_state("bluetooth.service", run_command=run_command)
    if service_state is not None and service_state != "active":
        return [
            GatewayAlert(
                code="bluetooth_service_inactive",
                severity="error",
                runbook="troubleshooting-bluetooth.md",
            )
        ]

    controller_state = _bluetoothctl_controller_state(run_command=run_command)
    powered = controller_state.get("powered")
    power_state = controller_state.get("power_state", "")
    if powered == "no" or power_state == "off-blocked":
        return [
            GatewayAlert(
                code="bluetooth_powered_off",
                severity="error",
                runbook="troubleshooting-bluetooth.md",
                context={
                    "controller": controller_state.get("controller", controller_label),
                    "power_state": power_state,
                },
            )
        ]
    return []


def _latest_advertised_mdns_name(*, run_command: CommandRunner) -> str | None:
    result = run_command(
        ["journalctl", "-u", "avahi-daemon", "-n", "80", "--no-pager", "-o", "cat"],
        5.0,
    )
    if result is None:
        return None
    latest: str | None = None
    for line in result.stdout.splitlines():
        match = _AVAHI_HOSTNAME_PATTERN.search(line)
        if match is not None:
            latest = match.group(1)
    return latest


def _collect_mdns_alerts(
    *,
    expected_hostname: str,
    run_command: CommandRunner,
) -> list[GatewayAlert]:
    service_state = _systemctl_state("avahi-daemon.service", run_command=run_command)
    if service_state is not None and service_state != "active":
        return [
            GatewayAlert(
                code="mdns_service_inactive",
                severity="error",
                runbook="troubleshooting-mdns-hostname.md",
            )
        ]

    advertised_hostname = _latest_advertised_mdns_name(run_command=run_command)
    if advertised_hostname and advertised_hostname != expected_hostname:
        return [
            GatewayAlert(
                code="mdns_hostname_mismatch",
                severity="error",
                runbook="troubleshooting-mdns-hostname.md",
                context={
                    "expected_hostname": expected_hostname,
                    "advertised_hostname": advertised_hostname,
                },
            )
        ]
    return []


def collect_gateway_alerts(
    *,
    expected_hostname: str | None = None,
    configured_adapter: str | None = None,
    bluetooth_sysfs_root: Path = _DEFAULT_BLUETOOTH_SYSFS_ROOT,
    rfkill_root: Path = _DEFAULT_RFKILL_ROOT,
    run_command: CommandRunner = _run_command,
) -> list[GatewayAlert]:
    if (
        not sys.platform.startswith("linux")
        and bluetooth_sysfs_root == _DEFAULT_BLUETOOTH_SYSFS_ROOT
        and rfkill_root == _DEFAULT_RFKILL_ROOT
    ):
        return []
    hostname = (expected_hostname or socket.gethostname()).strip()
    expected_mdns_name = f"{hostname}.local" if hostname else ""
    alerts = _collect_bluetooth_alerts(
        configured_adapter=configured_adapter,
        bluetooth_sysfs_root=bluetooth_sysfs_root,
        rfkill_root=rfkill_root,
        run_command=run_command,
    )
    if expected_mdns_name:
        alerts.extend(
            _collect_mdns_alerts(
                expected_hostname=expected_mdns_name,
                run_command=run_command,
            )
        )
    return alerts


def describe_gateway_alert(alert: GatewayAlert) -> str:
    if alert.code == "bluetooth_controller_missing":
        return (
            "Bluetooth interface is unavailable because no controller is detected. "
            "See the Raspberry Pi hardware audit or Bluetooth recovery runbook."
        )
    if alert.code == "bluetooth_hard_blocked":
        controller = alert.context.get("controller", "hci0")
        return (
            f"Bluetooth interface is hard-blocked on {controller}. "
            "See the Raspberry Pi Bluetooth recovery runbook."
        )
    if alert.code == "bluetooth_soft_blocked":
        controller = alert.context.get("controller", "hci0")
        return (
            f"Bluetooth interface is soft-blocked on {controller}. "
            "See the Raspberry Pi Bluetooth recovery runbook."
        )
    if alert.code == "bluetooth_service_inactive":
        return "Bluetooth service is inactive. See the Raspberry Pi Bluetooth recovery runbook."
    if alert.code == "bluetooth_powered_off":
        controller = alert.context.get("controller", "hci0")
        return (
            f"Bluetooth interface is powered off on {controller}. "
            "See the Raspberry Pi Bluetooth recovery runbook."
        )
    if alert.code == "mdns_service_inactive":
        return (
            "Bonjour/mDNS advertising is inactive. "
            "See the Raspberry Pi mDNS hostname recovery runbook."
        )
    if alert.code == "mdns_hostname_mismatch":
        expected_hostname = alert.context.get("expected_hostname", "bmgateway.local")
        advertised_hostname = alert.context.get("advertised_hostname", expected_hostname)
        return (
            f"Bonjour/mDNS is advertising {advertised_hostname} instead of {expected_hostname}. "
            "This usually means another device is already using the expected name. "
            "See the Raspberry Pi mDNS hostname recovery runbook."
        )
    return "Gateway attention needed. See the Raspberry Pi troubleshooting runbooks."
