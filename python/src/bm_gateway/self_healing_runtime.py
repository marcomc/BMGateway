"""Coordinate watchdog checkpoints, notification handoff and reboot scheduling."""

from __future__ import annotations

import time
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
    clear_wifi_recovery_transient_state,
    confirm_wifi_watchdog_state_durable,
    consume_wifi_recovery_notification,
    default_reboot_boot_id,
    default_schedule_reboot,
    ensure_wifi_recovery_identity,
    evaluate_self_healing,
    load_wifi_watchdog_state,
    persist_usb_otg_watchdog_state,
    persist_wifi_watchdog_state,
    rollback_initial_wifi_checkpoint,
    usb_otg_watchdog_state_path,
    usb_otg_watchdog_transaction,
    wifi_watchdog_state_path,
)
from .system_lifecycle import transfer_lifecycle_notifications

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
    if event.action not in {
        "wifi_reconnect_attempted",
        "wifi_reboot_requested",
        "wifi_connectivity_restored",
    }:
        return
    if idempotency_key:
        queue_notification_event_once(
            path=path,
            config=config.notifications,
            action=event.action,
            detail="",
            wifi_outcome=event.status,
            wifi_interface=interface,
            wifi_outage_seconds=outage_seconds,
            idempotency_key=idempotency_key,
        )
    else:
        queue_notification_event(
            path=path,
            config=config.notifications,
            action=event.action,
            detail="",
            wifi_outcome=event.status,
            wifi_interface=interface,
            wifi_outage_seconds=outage_seconds,
        )


def _queue_wifi_recovery_action(
    *,
    config: AppConfig,
    state: SelfHealingState,
    wifi_path: Path,
    outbox_path: Path,
    event: SelfHealingEvent,
    boot_id: str = "",
) -> None:
    reconnect = event.action == "wifi_reconnect_attempted"
    notification_kind = "reconnect" if reconnect else "reboot"
    notification_instance = event.status if reconnect else boot_id
    acknowledged = (
        notification_instance in state.wifi_reconnect_notified_outcomes
        if reconnect
        else notification_instance == state.wifi_reboot_notified_boot_id
    )
    if not acknowledged:
        key = (
            f"wifi-{notification_kind}:{state.wifi_recovery_handoff_id}:{notification_instance}"
            if state.wifi_recovery_handoff_id
            else ""
        )
        _queue_wifi_watchdog_notification(
            path=outbox_path, config=config, event=event, idempotency_key=key
        )
        if (
            state.wifi_recovery_pending
            and config.notifications.enabled
            and config.notifications.offline_delivery != "drop"
        ):
            if reconnect:
                state.wifi_reconnect_notified_outcomes += (event.status,)
            else:
                state.wifi_reboot_notified_boot_id = notification_instance
            persist_wifi_watchdog_state(wifi_path, state, preserve_pending=False)
    if reconnect and event.status == "completed":
        state.wifi_recovery_phase = "pending"
        persist_wifi_watchdog_state(wifi_path, state, preserve_pending=False)


def _transfer_wifi_restoration(
    *, config: AppConfig, state: SelfHealingState, wifi_path: Path, outbox_path: Path
) -> list[SelfHealingEvent]:
    """Transfer one ended incident before a later outage can replace its state."""
    transferred: list[SelfHealingEvent] = []
    if state.wifi_recovery_phase == "reconnect_pending":
        reconnect = SelfHealingEvent(
            action="wifi_reconnect_attempted",
            status="completed",
            details={
                "wifi_interface": state.wifi_recovery_interface,
                "outage_seconds": state.wifi_recovery_outage_seconds,
            },
        )
        _queue_wifi_recovery_action(
            config=config,
            state=state,
            wifi_path=wifi_path,
            outbox_path=outbox_path,
            event=reconnect,
        )
        transferred.append(reconnect)
    restored = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={
            "wifi_interface": state.wifi_recovery_interface,
            "outage_seconds": state.wifi_recovery_outage_seconds,
        },
    )

    def enqueue(current: SelfHealingState) -> None:
        _queue_wifi_watchdog_notification(
            path=outbox_path,
            config=config,
            event=restored,
            idempotency_key=f"wifi-recovery:{current.wifi_recovery_handoff_id}",
        )

    if consume_wifi_recovery_notification(wifi_path, state, enqueue):
        transferred.append(restored)
    return transferred


def run_self_healing(
    *, config: AppConfig, state: SelfHealingState, state_dir: Path
) -> list[SelfHealingEvent]:
    """Run one serialized watchdog transaction for daemon and one-shot callers."""
    events: list[SelfHealingEvent] = []
    transferred_events: list[SelfHealingEvent] = []
    wifi_transfer_in_progress = False
    path = usb_otg_watchdog_state_path(state_dir)
    wifi_path = wifi_watchdog_state_path(state_dir)
    before = replace(state)
    try:
        with usb_otg_watchdog_transaction(path, state, allow_unavailable=True) as usb_state_error:
            lifecycle_error: NotificationOutboxError | None = None
            try:
                transfer_lifecycle_notifications(config=config, state_dir=state_dir)
            except NotificationOutboxError as error:
                lifecycle_error = error
            before = replace(state)
            wifi_state_error: WiFiWatchdogStateError | None = None
            had_wifi_recovery_pending = state.wifi_recovery_pending
            previous_retry_origin = state.wifi_retry_started_at
            try:
                load_wifi_watchdog_state(wifi_path, state)
            except WiFiWatchdogStateError as error:
                wifi_state_error = error
            if wifi_state_error is None and previous_retry_origin != state.wifi_retry_started_at:
                clear_wifi_recovery_transient_state(state)
            if wifi_state_error is None:
                if wifi_path.exists():
                    confirm_wifi_watchdog_state_durable(wifi_path)
                identity_changed = ensure_wifi_recovery_identity(state)
                if identity_changed or (state.wifi_recovery_pending and not wifi_path.exists()):
                    persist_wifi_watchdog_state(wifi_path, state, preserve_pending=False)
                if state.wifi_recovery_pending and state.wifi_recovery_observed:
                    wifi_transfer_in_progress = True
                    transferred_events = _transfer_wifi_restoration(
                        config=config,
                        state=state,
                        wifi_path=wifi_path,
                        outbox_path=notification_outbox_path(state_dir),
                    )
                    wifi_transfer_in_progress = False
            if had_wifi_recovery_pending and not state.wifi_recovery_pending:
                clear_wifi_recovery_transient_state(state)
            current_boot_id: str | None = None

            def reboot_boot_id() -> str:
                nonlocal current_boot_id
                if current_boot_id is None:
                    current_boot_id = default_reboot_boot_id()
                return current_boot_id

            periodic_handoff_changed = False
            wifi_handoff_changed = False
            if state.periodic_reboot_requested and usb_state_error is None:
                if not state.periodic_reboot_scheduled_boot_id:
                    state.periodic_reboot_scheduled_boot_id = reboot_boot_id()
                    periodic_handoff_changed = True
                elif state.periodic_reboot_scheduled_boot_id != reboot_boot_id():
                    state.periodic_reboot_requested = False
                    state.periodic_reboot_scheduled_boot_id = ""
                    periodic_handoff_changed = True
            if state.wifi_recovery_pending and state.wifi_recovery_phase == "reboot_authorized":
                if not state.wifi_reboot_scheduled_boot_id:
                    state.wifi_reboot_scheduled_boot_id = reboot_boot_id()
                    wifi_handoff_changed = True
                elif state.wifi_reboot_scheduled_boot_id != reboot_boot_id():
                    state.wifi_retry_started_at = time.time()
                    clear_wifi_recovery_transient_state(state)
                    state.wifi_recovery_phase = "pending"
                    state.wifi_reboot_scheduled_boot_id = ""
                    state.wifi_reboot_requested = False
                    wifi_handoff_changed = True
            if periodic_handoff_changed:
                persist_usb_otg_watchdog_state(path, state)
            if wifi_handoff_changed:
                persist_wifi_watchdog_state(wifi_path, state, preserve_pending=False)
            persisted_periodic_reboot = state.periodic_reboot_requested and usb_state_error is None
            persisted_usb = replace(state)
            persisted_wifi = replace(state)
            persisted_periodic = state.periodic_reboot_requested
            persisted_periodic_boot_id = state.periodic_reboot_scheduled_boot_id
            before = replace(state)

            def usb_checkpoint() -> None:
                nonlocal persisted_periodic, persisted_periodic_boot_id, persisted_usb
                if usb_state_error is not None:
                    return
                if any(
                    value != getattr(persisted_usb, name)
                    for name, value in vars(state).items()
                    if name.startswith("usb_otg_")
                    or name in {"periodic_reboot_requested", "periodic_reboot_scheduled_boot_id"}
                ):
                    persist_usb_otg_watchdog_state(path, state)
                    persisted_usb = replace(state)
                    persisted_periodic = state.periodic_reboot_requested
                    persisted_periodic_boot_id = state.periodic_reboot_scheduled_boot_id

            def wifi_checkpoint(*, preserve_pending: bool = True) -> None:
                nonlocal persisted_wifi
                if any(
                    getattr(state, name) != getattr(persisted_wifi, name)
                    for name in vars(state)
                    if name.startswith("wifi_")
                ):
                    try:
                        persist_wifi_watchdog_state(
                            wifi_path, state, preserve_pending=preserve_pending
                        )
                    except WiFiWatchdogStateError:
                        rollback_initial_wifi_checkpoint(state, persisted_wifi)
                        raise
                    persisted_wifi = replace(state)

            def periodic_checkpoint() -> None:
                nonlocal persisted_periodic, persisted_periodic_boot_id
                if usb_state_error is not None:
                    return
                if (
                    state.periodic_reboot_requested != persisted_periodic
                    or state.periodic_reboot_scheduled_boot_id != persisted_periodic_boot_id
                ):
                    persist_usb_otg_watchdog_state(path, state)
                    persisted_periodic = state.periodic_reboot_requested
                    persisted_periodic_boot_id = state.periodic_reboot_scheduled_boot_id

            healing_config = config
            if usb_state_error is not None:
                healing_config = replace(
                    config,
                    self_healing=replace(
                        config.self_healing,
                        usb_otg_watchdog_enabled=False,
                        periodic_reboot_enabled=False,
                    ),
                )
            if wifi_state_error is not None:
                healing_config = replace(
                    healing_config,
                    self_healing=replace(healing_config.self_healing, wifi_watchdog_enabled=False),
                )

            if (
                config.self_healing.wifi_watchdog_enabled
                and not config.self_healing.wifi_reboot_enabled
                and state.wifi_recovery_pending
                and state.wifi_recovery_phase == "reboot_authorized"
            ):
                clear_wifi_recovery_handoff(wifi_path, state, force=True)

            events = evaluate_self_healing(
                config=healing_config,
                state=state,
                # Existing periodic/Wi-Fi policies still select their requests;
                # the coordinator schedules one reboot after durable handoff.
                reboot_action=lambda: None,
                usb_otg_state_checkpoint=usb_checkpoint,
                wifi_state_checkpoint=wifi_checkpoint,
            )
            if usb_state_error is not None:
                events.append(
                    SelfHealingEvent(
                        action="usb_otg_watchdog_state_unavailable",
                        status="failed",
                        details={
                            "reason": translation_for(config.notifications.locale).gettext(
                                str(usb_state_error)
                            )
                        },
                    )
                )
            if persisted_periodic_reboot:
                if config.self_healing.periodic_reboot_enabled and not any(
                    event.action == "periodic_reboot_requested" for event in events
                ):
                    events.insert(
                        0,
                        SelfHealingEvent(
                            action="periodic_reboot_requested",
                            status="completed",
                            details={
                                "periodic_reboot_hours": config.self_healing.periodic_reboot_hours,
                                "elapsed_seconds": config.self_healing.periodic_reboot_hours * 3600,
                            },
                        ),
                    )
                elif not config.self_healing.periodic_reboot_enabled:
                    state.periodic_reboot_requested = False
                    state.periodic_reboot_scheduled_boot_id = ""
            usb_checkpoint_failed = any(
                event.action
                in {"usb_otg_watchdog_state_persist_failed", "usb_otg_watchdog_state_unavailable"}
                for event in events
            )

            if not config.self_healing.wifi_watchdog_enabled:
                clear_wifi_recovery_handoff(wifi_path, state, force=True)
            if usb_checkpoint_failed:
                # Periodic reboot authorization is independent of the USB
                # checkpoint and must survive a deferred peer recovery.
                periodic_checkpoint()
            else:
                usb_checkpoint()
            wifi_checkpoint(
                preserve_pending=not any(
                    event.action == "wifi_connectivity_restored" for event in events
                )
            )

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

            # Lifecycle receipts gate mail delivery, not independently durable
            # watchdog reboot authorization. Watchdog handoff failures retain
            # their stricter reboot gate below.
            defer_notification_delivery = lifecycle_error is not None
            defer_recovery_reboots = False
            if lifecycle_error is not None:
                events.append(
                    SelfHealingEvent(
                        action="lifecycle_notification_handoff_failed",
                        status="failed",
                        details={
                            "reason": translation_for(config.notifications.locale).gettext(
                                str(lifecycle_error)
                            )
                        },
                    )
                )
            for event in events:
                if event.action == "wifi_connectivity_restored":
                    if defer_notification_delivery:
                        continue
                    try:
                        if state.wifi_recovery_pending:
                            _transfer_wifi_restoration(
                                config=config,
                                state=state,
                                wifi_path=wifi_path,
                                outbox_path=notification_outbox_path(state_dir),
                            )
                        else:
                            _queue_wifi_watchdog_notification(
                                path=notification_outbox_path(state_dir),
                                config=config,
                                event=event,
                            )
                    except (NotificationOutboxError, WiFiWatchdogStateError):
                        if not state.wifi_recovery_pending:
                            state.wifi_outage_started_monotonic = (
                                before.wifi_outage_started_monotonic
                            )
                            state.wifi_reconnect_attempted = before.wifi_reconnect_attempted
                            state.wifi_reboot_requested = before.wifi_reboot_requested
                        defer_notification_delivery = True
                        defer_recovery_reboots = True
                elif event.action in {
                    "wifi_reconnect_attempted",
                    "wifi_reboot_requested",
                }:
                    try:
                        _queue_wifi_recovery_action(
                            config=config,
                            state=state,
                            wifi_path=wifi_path,
                            outbox_path=notification_outbox_path(state_dir),
                            event=event,
                            boot_id=reboot_boot_id()
                            if event.action == "wifi_reboot_requested"
                            else "",
                        )
                    except NotificationOutboxError:
                        defer_notification_delivery = True
                        defer_recovery_reboots = True
                    except WiFiWatchdogStateError:
                        defer_notification_delivery = True
                        defer_recovery_reboots = True

            if defer_recovery_reboots:
                return transferred_events + _defer_reboots(events, state, before)

            if usb_checkpoint_failed:
                # Wi-Fi notifications are independent of a failed USB
                # checkpoint, but no reboot may be scheduled in this cycle.
                return transferred_events + _defer_reboots(events, state, before)

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
                boot_id = (
                    reboot_boot_id()
                    if any(
                        action in {"periodic_reboot_requested", "wifi_reboot_requested"}
                        for action in requested_actions
                    )
                    else ""
                )
                if (
                    "periodic_reboot_requested" in requested_actions
                    and state.periodic_reboot_requested
                ):
                    state.periodic_reboot_scheduled_boot_id = boot_id
                    periodic_checkpoint()
                if (
                    "wifi_reboot_requested" in requested_actions
                    and state.wifi_recovery_pending
                    and state.wifi_recovery_phase == "reboot_authorized"
                ):
                    state.wifi_reboot_scheduled_boot_id = boot_id
                    wifi_checkpoint()
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
        events = _defer_reboots(events, state, before)
        events.append(
            SelfHealingEvent(
                action=(
                    "wifi_recovery_notification_queue"
                    if isinstance(error, NotificationOutboxError) and wifi_transfer_in_progress
                    else "usb_otg_recovery_notification_queue"
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
    return transferred_events + events


def _defer_reboots(
    events: list[SelfHealingEvent], state: SelfHealingState, before: SelfHealingState
) -> list[SelfHealingEvent]:
    # USB state is always reloaded from disk on the next transaction. Do not
    # overwrite a checkpoint that may already have reached disk before fsync
    # reported an error. Only process-local peer request flags are restored.
    state.periodic_reboot_requested = before.periodic_reboot_requested
    state.periodic_reboot_scheduled_boot_id = before.periodic_reboot_scheduled_boot_id
    state.wifi_reconnect_attempted = before.wifi_reconnect_attempted
    state.wifi_reboot_requested = before.wifi_reboot_requested
    state.wifi_reboot_scheduled_boot_id = before.wifi_reboot_scheduled_boot_id
    return [event for event in events if event.action not in _REBOOT_ACTIONS]
