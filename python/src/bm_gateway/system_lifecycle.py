"""Boot and shutdown intents sharing the watchdog transaction and mail outbox.

The systemd shutdown guard is adapted from PiServ. Transport and durable delivery
remain owned by BMGateway, rather than copying PiServ's direct-send helper.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from .config import AppConfig
from .notifications import (
    NotificationOutboxError,
    deliver_notification_outbox,
    notification_outbox_path,
    queue_notification_event_once,
)
from .self_healing import (
    confirm_wifi_watchdog_state_durable,
    default_reboot_boot_id,
    load_wifi_watchdog_state,
    new_self_healing_state,
    usb_otg_watchdog_state_path,
    usb_otg_watchdog_transaction,
    wifi_watchdog_state_path,
)


def _path(state_dir: Path) -> Path:
    return state_dir / "runtime" / "system_lifecycle_state.json"


def _save(path: Path, data: dict[str, Any]) -> None:
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise NotificationOutboxError("Cannot persist lifecycle notification state") from error
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError as error:
                logging.warning("%s", error)


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            data = json.load(handle)
            os.fsync(handle.fileno())
        if not isinstance(data, dict) or set(data) != {"boot_id", "recorded", "pending"}:
            raise ValueError("invalid lifecycle state")
        UUID(data["boot_id"])
        if not isinstance(data["recorded"], list) or any(
            event not in {"boot", "shutdown"} for event in data["recorded"]
        ):
            raise ValueError("invalid lifecycle receipts")
        if not isinstance(data["pending"], list):
            raise ValueError("invalid lifecycle intents")
        for event in data["pending"]:
            if event["action"] not in {"boot", "shutdown"}:
                raise ValueError("invalid lifecycle action")
            UUID(event["boot_id"])
            if datetime.fromisoformat(event["occurred_at"]).tzinfo is None:
                raise ValueError("naive lifecycle timestamp")
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return data
    except FileNotFoundError:
        return {"boot_id": "", "recorded": [], "pending": []}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise NotificationOutboxError("Cannot load lifecycle notification state") from error


def _systemd_runtime_present() -> bool:
    return Path("/run/systemd/system").is_dir()


def lifecycle_wall_clock_is_synchronized() -> bool:
    """Fail closed on appliances until systemd confirms NTP synchronization."""
    if not _systemd_runtime_present():
        return True
    try:
        result = subprocess.run(
            ["/usr/bin/timedatectl", "show", "--property=NTPSynchronized", "--value"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "yes"


def transfer_lifecycle_notifications(*, config: AppConfig, state_dir: Path) -> bool:
    """Caller holds the shared watchdog lock through subsequent delivery."""
    if not lifecycle_wall_clock_is_synchronized():
        return False
    path = _path(state_dir)
    data = _load(path)
    if not data["pending"]:
        return True
    transfer_time = datetime.now(timezone.utc)
    cutoff = transfer_time - timedelta(days=config.notifications.offline_retention_days)
    pending = data["pending"][-config.notifications.offline_max_events :]
    for event in pending:
        occurred_at = datetime.fromisoformat(event["occurred_at"])
        if occurred_at < cutoff:
            continue
        queue_notification_event_once(
            path=notification_outbox_path(state_dir),
            config=config.notifications,
            action=f"system_{event['action']}",
            detail="",
            idempotency_key=f"lifecycle:{event['boot_id']}:{event['action']}",
            now=occurred_at,
            retention_now=transfer_time,
        )
    data["pending"] = []
    _save(path, data)
    return True


def shutdown_in_progress() -> bool:
    """A service stop/restart is not evidence of a host shutdown (PiServ guard)."""
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", "is-system-running"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.stdout.strip() == "stopping"


def notify_system_lifecycle(*, config: AppConfig, state_dir: Path, action: str) -> None:
    if action not in {"boot", "shutdown"}:
        raise ValueError("Invalid lifecycle action")
    if not config.notifications.enabled:
        return
    if action == "shutdown" and not shutdown_in_progress():
        return
    boot_id = str(UUID(default_reboot_boot_id()))
    state = new_self_healing_state()
    with usb_otg_watchdog_transaction(
        usb_otg_watchdog_state_path(state_dir), state, allow_unavailable=True
    ) as usb_error:
        data = _load(_path(state_dir))
        if data["boot_id"] != boot_id:
            data["boot_id"] = boot_id
            data["recorded"] = []
        if action not in data["recorded"]:
            data["recorded"].append(action)
            data["pending"].append(
                {
                    "boot_id": boot_id,
                    "action": action,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            data["pending"] = data["pending"][-config.notifications.offline_max_events :]
            _save(_path(state_dir), data)
        if not transfer_lifecycle_notifications(config=config, state_dir=state_dir):
            return
        if usb_error is not None or state.usb_otg_escalation_notification_pending:
            return
        wifi_path = wifi_watchdog_state_path(state_dir)
        load_wifi_watchdog_state(wifi_path, state)
        if wifi_path.exists():
            confirm_wifi_watchdog_state_durable(wifi_path)
        if state.wifi_recovery_pending:
            return
        delivered, detail = deliver_notification_outbox(
            path=notification_outbox_path(state_dir), config=config.notifications
        )
        if not delivered:
            # Durable intent/outbox is retained; keep ExecStop armed while the
            # normal runtime retries delivery when connectivity returns.
            logging.warning("%s", detail)
