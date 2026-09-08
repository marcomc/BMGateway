"""Record durable notifications for bootstrap-driven BMGateway updates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .notifications import (
    deliver_notification_outbox,
    notification_outbox_path,
    queue_notification_event_once,
)
from .self_healing import (
    WiFiWatchdogStateError,
    confirm_wifi_watchdog_state_durable,
    load_wifi_watchdog_state,
    new_self_healing_state,
    usb_otg_watchdog_state_path,
    usb_otg_watchdog_transaction,
    wifi_watchdog_state_path,
)
from .system_lifecycle import lifecycle_wall_clock_is_synchronized

_REVISION_PATTERN = re.compile(r"[0-9a-f]{7,64}")
_FAILURE_STAGES = frozenset({"fetch", "install", "services"})
_WATCHDOG_HANDOFF_WAIT_DETAIL = "Notification delivery is waiting for watchdog handoff"


@dataclass(frozen=True)
class UpdateNotificationResult:
    """Outcome of recording an update without changing the update result itself."""

    queued: bool
    delivered: bool
    detail: str


def _revision(value: str, *, name: str) -> str:
    normalized = value.strip().lower()
    if _REVISION_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{name} must be a Git revision of 7 to 64 hexadecimal characters")
    return normalized


def record_update_notification(
    *,
    config: AppConfig,
    state_dir: Path,
    previous_revision: str,
    current_revision: str | None = None,
    reboot_required: bool | None = None,
    failure_stage: str | None = None,
) -> UpdateNotificationResult:
    """Queue an update result and attempt delivery without masking the update outcome."""
    previous = _revision(previous_revision, name="previous revision")
    time_trusted = lifecycle_wall_clock_is_synchronized()
    state = new_self_healing_state()
    with usb_otg_watchdog_transaction(
        usb_otg_watchdog_state_path(state_dir), state, allow_unavailable=True
    ) as usb_error:
        path = notification_outbox_path(state_dir)
        if failure_stage is None:
            if current_revision is None or reboot_required is None:
                raise ValueError("Successful updates require current revision and reboot status")
            current = _revision(current_revision, name="current revision")
            if current == previous:
                raise ValueError("Successful updates must change the Git revision")
            queued = queue_notification_event_once(
                path=path,
                config=config.notifications,
                action="software_update_completed",
                detail="",
                idempotency_key=f"software-update:completed:{previous}:{current}",
                update_outcome="completed",
                update_from_revision=previous,
                update_to_revision=current,
                update_reboot_required=reboot_required,
                time_trusted=time_trusted,
            )
        else:
            if failure_stage not in _FAILURE_STAGES:
                raise ValueError(
                    "failure stage must be one of: " + ", ".join(sorted(_FAILURE_STAGES))
                )
            if current_revision is not None or reboot_required is not None:
                raise ValueError(
                    "Failed updates must not claim a current revision or reboot status"
                )
            queued = queue_notification_event_once(
                path=path,
                config=config.notifications,
                action="software_update_failed",
                detail="",
                idempotency_key=f"software-update:failed:{previous}:{failure_stage}",
                update_outcome="failed",
                update_from_revision=previous,
                update_stage=failure_stage,
                time_trusted=time_trusted,
            )
        if not time_trusted:
            delivered, detail = False, "Notification delivery is waiting for clock synchronization"
        elif usb_error is not None or state.usb_otg_escalation_notification_pending:
            delivered, detail = False, _WATCHDOG_HANDOFF_WAIT_DETAIL
        else:
            wifi_path = wifi_watchdog_state_path(state_dir)
            try:
                load_wifi_watchdog_state(wifi_path, state)
                if wifi_path.exists():
                    confirm_wifi_watchdog_state_durable(wifi_path)
            except WiFiWatchdogStateError:
                delivered, detail = False, _WATCHDOG_HANDOFF_WAIT_DETAIL
            else:
                if state.wifi_recovery_pending:
                    delivered, detail = False, _WATCHDOG_HANDOFF_WAIT_DETAIL
                else:
                    delivered, detail = deliver_notification_outbox(
                        path=path,
                        config=config.notifications,
                        time_trusted=True,
                    )
    return UpdateNotificationResult(queued=queued, delivered=delivered, detail=detail)
