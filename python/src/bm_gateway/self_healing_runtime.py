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
    queue_notification_event,
    queue_notification_event_once,
)
from .self_healing import (
    SelfHealingEvent,
    SelfHealingState,
    USBOTGWatchdogStateError,
    WiFiWatchdogStateError,
    clear_wifi_recovery_handoff,
    consume_wifi_recovery_notification,
    default_schedule_reboot,
    evaluate_self_healing,
    load_wifi_watchdog_state,
    persist_usb_otg_watchdog_state,
    persist_wifi_watchdog_state,
    usb_otg_watchdog_state_path,
    usb_otg_watchdog_transaction,
    wifi_watchdog_state_path,
)

_REBOOT_ACTIONS = {
    "periodic_reboot_requested",
    "wifi_reboot_requested",
    "usb_otg_reboot_requested",
}


def _queue_wifi_watchdog_notification(
    *, path: Path, config: AppConfig, event: SelfHealingEvent, idempotency_key: str = ""
) -> None:
    details = event.details
    outage_value = details.get("outage_seconds", 0)
    outage_seconds = outage_value if isinstance(outage_value, int) else 0
    interface = str(details.get("wifi_interface", ""))
    translate = translation_for(config.notifications.locale).gettext
    if event.action == "wifi_reconnect_attempted":
        template = (
            "Wi-Fi reconnect succeeded after {outage_seconds} seconds on {wifi_interface}."
            if event.status == "completed"
            else "Wi-Fi reconnect failed after {outage_seconds} seconds on {wifi_interface}."
        )
        detail = translate(template).format(outage_seconds=outage_seconds, wifi_interface=interface)
    elif event.action == "wifi_reboot_requested":
        detail = translate(
            "Wi-Fi reboot requested after {outage_seconds} seconds on {wifi_interface}."
        ).format(outage_seconds=outage_seconds, wifi_interface=interface)
    elif event.action == "wifi_connectivity_restored":
        detail = translate("Wi-Fi connectivity restored after {outage_seconds} seconds.").format(
            outage_seconds=outage_seconds
        )
    else:
        return
    if idempotency_key:
        queue_notification_event_once(
            path=path,
            config=config.notifications,
            action=event.action,
            detail=detail,
            idempotency_key=idempotency_key,
        )
    else:
        queue_notification_event(
            path=path,
            config=config.notifications,
            action=event.action,
            detail=detail,
        )


def run_self_healing(
    *, config: AppConfig, state: SelfHealingState, state_dir: Path
) -> list[SelfHealingEvent]:
    """Run one serialized watchdog transaction for daemon and one-shot callers."""
    events: list[SelfHealingEvent] = []
    path = usb_otg_watchdog_state_path(state_dir)
    wifi_path = wifi_watchdog_state_path(state_dir)
    before = replace(state)
    loaded = False
    try:
        with usb_otg_watchdog_transaction(path, state):
            loaded = True
            before = replace(state)
            wifi_state_error: WiFiWatchdogStateError | None = None
            try:
                load_wifi_watchdog_state(wifi_path, state)
            except WiFiWatchdogStateError as error:
                wifi_state_error = error
            persisted_usb = replace(state)
            persisted_wifi = replace(state)

            def usb_checkpoint() -> None:
                nonlocal persisted_usb
                if any(
                    value != getattr(persisted_usb, name)
                    for name, value in vars(state).items()
                    if name.startswith("usb_otg_")
                ):
                    persist_usb_otg_watchdog_state(path, state)
                    persisted_usb = replace(state)

            def wifi_checkpoint() -> None:
                nonlocal persisted_wifi
                if any(
                    getattr(state, name) != getattr(persisted_wifi, name)
                    for name in vars(state)
                    if name.startswith("wifi_")
                ):
                    persist_wifi_watchdog_state(wifi_path, state)
                    persisted_wifi = replace(state)

            healing_config = config
            if wifi_state_error is not None:
                healing_config = replace(
                    config,
                    self_healing=replace(config.self_healing, wifi_watchdog_enabled=False),
                )

            events = evaluate_self_healing(
                config=healing_config,
                state=state,
                # Existing periodic/Wi-Fi policies still select their requests;
                # the coordinator schedules one reboot after durable handoff.
                reboot_action=lambda: None,
                usb_otg_state_checkpoint=usb_checkpoint,
                wifi_state_checkpoint=wifi_checkpoint,
            )
            usb_checkpoint_failed = any(
                event.action
                in {"usb_otg_watchdog_state_persist_failed", "usb_otg_watchdog_state_unavailable"}
                for event in events
            )

            if not config.self_healing.wifi_watchdog_enabled:
                clear_wifi_recovery_handoff(wifi_path, state, force=True)
            if not usb_checkpoint_failed:
                usb_checkpoint()
            wifi_checkpoint()

            if wifi_state_error is not None:
                events.append(
                    SelfHealingEvent(
                        action="wifi_watchdog_state_unavailable",
                        status="failed",
                        details={
                            "reason": translation_for(config.notifications.locale).gettext(
                                str(wifi_state_error)
                            )
                        },
                    )
                )

            if (
                state.wifi_recovery_pending
                and state.wifi_recovery_phase == "reconnect_pending"
                and any(event.action == "wifi_connectivity_restored" for event in events)
                and not any(event.action == "wifi_reconnect_attempted" for event in events)
            ):
                events.insert(
                    0,
                    SelfHealingEvent(
                        action="wifi_reconnect_attempted",
                        status="completed",
                        details={
                            "wifi_interface": state.wifi_recovery_interface,
                            "outage_seconds": state.wifi_recovery_outage_seconds,
                        },
                    ),
                )

            def enqueue_wifi_recovery(recovery_state: SelfHealingState) -> None:
                translate = translation_for(config.notifications.locale).gettext
                detail = translate(
                    "Wi-Fi connectivity restored after {outage_seconds} seconds."
                ).format(outage_seconds=recovery_state.wifi_recovery_outage_seconds)
                queue_notification_event_once(
                    path=notification_outbox_path(state_dir),
                    config=config.notifications,
                    action="wifi_connectivity_restored",
                    detail=detail,
                    idempotency_key=(f"wifi-recovery:{recovery_state.wifi_recovery_handoff_id}"),
                )

            defer_notification_delivery = False
            for event in events:
                if event.action == "wifi_connectivity_restored":
                    if defer_notification_delivery:
                        continue
                    try:
                        if state.wifi_recovery_pending:
                            consume_wifi_recovery_notification(
                                wifi_path, state, enqueue_wifi_recovery
                            )
                        else:
                            _queue_wifi_watchdog_notification(
                                path=notification_outbox_path(state_dir),
                                config=config,
                                event=event,
                            )
                    except (NotificationOutboxError, WiFiWatchdogStateError):
                        defer_notification_delivery = True
                elif event.action in {
                    "wifi_reconnect_attempted",
                    "wifi_reboot_requested",
                }:
                    try:
                        idempotency_key = ""
                        if event.action in {
                            "wifi_reconnect_attempted",
                            "wifi_reboot_requested",
                        }:
                            notification_kind = (
                                "reconnect"
                                if event.action == "wifi_reconnect_attempted"
                                else "reboot"
                            )
                            idempotency_key = (
                                f"wifi-{notification_kind}:{state.wifi_recovery_handoff_id}"
                                if state.wifi_recovery_handoff_id
                                else ""
                            )
                        _queue_wifi_watchdog_notification(
                            path=notification_outbox_path(state_dir),
                            config=config,
                            event=event,
                            idempotency_key=idempotency_key,
                        )
                        if (
                            event.action == "wifi_reconnect_attempted"
                            and event.status == "completed"
                        ):
                            state.wifi_recovery_phase = "pending"
                            persist_wifi_watchdog_state(wifi_path, state, preserve_pending=False)
                    except NotificationOutboxError:
                        defer_notification_delivery = True
                    except WiFiWatchdogStateError:
                        defer_notification_delivery = True

            if defer_notification_delivery:
                return _defer_reboots(events, state, before)

            if usb_checkpoint_failed:
                # Wi-Fi notifications are independent of a failed USB
                # checkpoint, but no reboot may be scheduled in this cycle.
                return _defer_reboots(events, state, before)

            for event in events:
                if event.action != "usb_otg_recovery_exhausted":
                    continue
                queue_notification_event_once(
                    path=notification_outbox_path(state_dir),
                    config=config.notifications,
                    action=event.action,
                    detail="",
                    idempotency_key=f"usb-otg-escalation:{state.usb_otg_escalation_id}",
                    usb_otg_reason=state.usb_otg_escalation_reason,
                    usb_otg_reboot_attempts=state.usb_otg_escalation_reboot_attempts,
                )
                state.usb_otg_escalation_notification_pending = False
                usb_checkpoint()

            wifi_checkpoint()

            # Every production outbox consumer holds the USB transaction lock.
            # A failed queue/ACK exits before delivery; a fresh caller reloads
            # the durable pending identity and retries the handoff first.
            if config.notifications.enabled and not defer_notification_delivery:
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
    except (USBOTGWatchdogStateError, NotificationOutboxError, WiFiWatchdogStateError) as error:
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
                    else "wifi_watchdog_state_unavailable"
                    if isinstance(error, WiFiWatchdogStateError)
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
    state.wifi_reconnect_attempted = before.wifi_reconnect_attempted
    state.wifi_reboot_requested = before.wifi_reboot_requested
    return [event for event in events if event.action not in _REBOOT_ACTIONS]
