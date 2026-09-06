"""Coordinate watchdog checkpoints, notification handoff and reboot scheduling."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import AppConfig
from .localization import translation_for
from .notifications import (
    NotificationOutboxError,
    deliver_notification_outbox,
    notification_outbox_path,
    queue_notification_event_once,
)
from .self_healing import (
    SelfHealingEvent,
    SelfHealingState,
    USBOTGWatchdogStateError,
    default_schedule_reboot,
    evaluate_self_healing,
    persist_usb_otg_watchdog_state,
    usb_otg_watchdog_state_path,
    usb_otg_watchdog_transaction,
)

_REBOOT_ACTIONS = {
    "periodic_reboot_requested",
    "wifi_reboot_requested",
    "usb_otg_reboot_requested",
}


def run_self_healing(
    *, config: AppConfig, state: SelfHealingState, state_dir: Path
) -> list[SelfHealingEvent]:
    """Run one serialized watchdog transaction for daemon and one-shot callers."""
    events: list[SelfHealingEvent] = []
    path = usb_otg_watchdog_state_path(state_dir)
    before = replace(state)
    loaded = False
    try:
        with usb_otg_watchdog_transaction(path, state):
            loaded = True
            before = replace(state)
            persisted = replace(state)

            def checkpoint() -> None:
                nonlocal persisted
                if any(
                    value != getattr(persisted, name)
                    for name, value in vars(state).items()
                    if name.startswith("usb_otg_")
                ):
                    persist_usb_otg_watchdog_state(path, state)
                    persisted = replace(state)

            events = evaluate_self_healing(
                config=config,
                state=state,
                # Existing periodic/Wi-Fi policies still select their requests;
                # the coordinator schedules one reboot after durable handoff.
                reboot_action=lambda: None,
                usb_otg_state_checkpoint=checkpoint,
            )
            if any(
                event.action
                in {"usb_otg_watchdog_state_persist_failed", "usb_otg_watchdog_state_unavailable"}
                for event in events
            ):
                return _defer_reboots(events, state, before)
            checkpoint()
            for event in events:
                if event.action != "usb_otg_recovery_exhausted":
                    continue
                text = translation_for(config.notifications.locale).gettext
                queue_notification_event_once(
                    path=notification_outbox_path(state_dir),
                    config=config.notifications,
                    action=event.action,
                    detail=text(
                        "USB OTG frame enumeration remained unavailable after "
                        "{attempts} reboot attempt(s): {reason}"
                    ).format(
                        attempts=state.usb_otg_escalation_reboot_attempts,
                        reason=text(state.usb_otg_escalation_reason),
                    ),
                    idempotency_key=f"usb-otg-escalation:{state.usb_otg_escalation_id}",
                )
                state.usb_otg_escalation_notification_pending = False
                checkpoint()

            # Every production outbox consumer holds the USB transaction lock.
            # A failed queue/ACK exits before delivery; a fresh caller reloads
            # the durable pending identity and retries the handoff first.
            if config.notifications.enabled:
                delivered, detail = deliver_notification_outbox(
                    path=notification_outbox_path(state_dir), config=config.notifications
                )
                if detail != "No pending notifications":
                    events.append(
                        SelfHealingEvent(
                            action="notification_outbox_delivery",
                            status="completed" if delivered else "failed",
                            details={"detail": detail},
                        )
                    )
            requested_actions = [
                event.action for event in events if event.action in _REBOOT_ACTIONS
            ]
            if requested_actions:
                try:
                    default_schedule_reboot()
                except OSError:
                    events = _defer_reboots(events, state, before)
                    events.append(
                        SelfHealingEvent(
                            action="reboot_schedule_failed",
                            status="failed",
                            details={
                                "reason": translation_for(config.notifications.locale).gettext(
                                    "Reboot scheduling failed"
                                ),
                                "requested_actions": requested_actions,
                            },
                        )
                    )
    except (USBOTGWatchdogStateError, NotificationOutboxError) as error:
        if not loaded:
            state.usb_otg_escalation_notification_pending = False
            events = evaluate_self_healing(
                config=replace(
                    config,
                    self_healing=replace(config.self_healing, usb_otg_watchdog_enabled=False),
                ),
                state=state,
                reboot_action=lambda: None,
            )
        events = _defer_reboots(events, state, before)
        events.append(
            SelfHealingEvent(
                action=(
                    "usb_otg_recovery_notification_queue"
                    if isinstance(error, NotificationOutboxError)
                    else "usb_otg_watchdog_state_unavailable"
                ),
                status="failed",
                details={
                    "reason": translation_for(config.notifications.locale).gettext(str(error))
                },
            )
        )
    return events


def _defer_reboots(
    events: list[SelfHealingEvent], state: SelfHealingState, before: SelfHealingState
) -> list[SelfHealingEvent]:
    # USB state is always reloaded from disk on the next transaction. Do not
    # overwrite a checkpoint that may already have reached disk before fsync
    # reported an error. Only process-local peer request flags are restored.
    state.periodic_reboot_requested = before.periodic_reboot_requested
    state.wifi_reboot_requested = before.wifi_reboot_requested
    return [event for event in events if event.action not in _REBOOT_ACTIONS]
