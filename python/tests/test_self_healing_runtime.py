from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
from dataclasses import replace
from email import message_from_string
from functools import partial
from pathlib import Path

import pytest
from bm_gateway import notifications, self_healing
from bm_gateway import self_healing_runtime as runtime
from bm_gateway.config import AppConfig, NotificationsConfig, load_config
from bm_gateway.localization import translation_for
from bm_gateway.self_healing import (
    SelfHealingEvent,
    USBOTGHealth,
    WiFiWatchdogStateError,
    new_self_healing_state,
    persist_wifi_watchdog_state,
    wifi_watchdog_state_path,
)


def _config() -> AppConfig:
    config = load_config(Path("python/config/config.toml.example"))
    return replace(
        config,
        self_healing=replace(
            config.self_healing,
            usb_otg_watchdog_enabled=True,
            usb_otg_reboot_enabled=True,
            usb_otg_reboot_attempts=2,
        ),
        notifications=replace(
            config.notifications, enabled=True, recipient="user@example.com", locale="en"
        ),
    )


def _seed(state_dir: Path) -> Path:
    path = self_healing.usb_otg_watchdog_state_path(state_dir)
    state = new_self_healing_state()
    state.usb_otg_rebind_attempted = True
    state.usb_otg_reboot_attempts_used = 2
    self_healing.persist_usb_otg_watchdog_state(path, state)
    return path


def _evaluate(monkeypatch: pytest.MonkeyPatch, *, healthy: bool = False) -> None:
    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            usb_otg_health_checker=lambda *_: USBOTGHealth(
                healthy, "original-reason", "controller", "configured" if healthy else "powered"
            ),
            usb_otg_rebind_action=lambda *_: True,
            usb_otg_boot_id_reader=lambda: "boot-one",
            connectivity_checker=lambda *_: False,
        ),
    )


def _delivery(monkeypatch: pytest.MonkeyPatch, path: Path) -> list[str]:
    delivered: list[str] = []

    def sendmail(payload: str) -> subprocess.CompletedProcess[str]:
        assert json.loads(path.read_text())["escalation_notification_pending"] is False
        body = message_from_string(payload).get_payload(decode=True)
        assert isinstance(body, bytes)
        delivered.append(body.decode())
        return subprocess.CompletedProcess(["sendmail"], 0, "", "")

    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        partial(notifications.deliver_notification_outbox, runner=sendmail),
    )
    return delivered


def _wifi_config() -> AppConfig:
    config = load_config(Path("python/config/config.toml.example"))
    return replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_watchdog_enabled=True,
            wifi_interface="wlan0",
        ),
        notifications=replace(
            config.notifications, enabled=True, recipient="user@example.com", locale="en"
        ),
    )


def _legacy_wifi_state(
    tmp_path: Path, *, phase: str = "pending", identity: str | None = None
) -> Path:
    path = wifi_watchdog_state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "recovery_pending": True,
        "outage_seconds": 600,
        "wifi_interface": "wlan0",
        "recovery_started_at": 1000.0,
        "recovery_phase": phase,
    }
    if identity is not None:
        payload["recovery_handoff_id"] = identity
    path.write_text(json.dumps(payload))
    return path


def _wifi_mail_delivery(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    delivered: list[str] = []

    def sendmail(payload: str) -> subprocess.CompletedProcess[str]:
        body = message_from_string(payload).get_payload(decode=True)
        assert isinstance(body, bytes)
        delivered.append(body.decode())
        return subprocess.CompletedProcess(["sendmail"], 0, "", "")

    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        partial(notifications.deliver_notification_outbox, runner=sendmail),
    )
    return delivered


@pytest.mark.parametrize("identity", [None, "", "existing-incident"])
@pytest.mark.parametrize(
    "scenario", ["reconnect_failed", "reconnect_success", "reboot", "authorized", "healthy"]
)
def test_legacy_wifi_identity_is_durable_before_actions_and_alerts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, identity: str | None, scenario: str
) -> None:
    config = _wifi_config()
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_reconnect_enabled=scenario.startswith("reconnect"),
            wifi_reconnect_after_minutes=1,
            wifi_reboot_enabled=scenario in {"reboot", "authorized"},
            wifi_reboot_after_minutes=2,
        ),
    )
    path = _legacy_wifi_state(
        tmp_path,
        phase="reboot_authorized" if scenario == "authorized" else "pending",
        identity=identity,
    )
    observed: list[str] = []

    def assert_identity() -> None:
        payload = json.loads(path.read_text())
        assert payload["recovery_handoff_id"]
        assert payload["recovery_started_at"] == 1000.0
        observed.append(payload["recovery_handoff_id"])

    probes = 0

    def probe(*_args: object) -> bool:
        nonlocal probes
        assert_identity()
        probes += 1
        return scenario == "healthy" or (scenario == "reconnect_success" and probes > 1)

    def reconnect(_interface: str) -> bool:
        assert_identity()
        return scenario == "reconnect_success"

    def queue(
        *, path: Path, config: NotificationsConfig, action: str, detail: str, idempotency_key: str
    ) -> bool:
        assert_identity()
        return notifications.queue_notification_event_once(
            path=path, config=config, action=action, detail=detail, idempotency_key=idempotency_key
        )

    monkeypatch.setattr(runtime, "queue_notification_event_once", queue)
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-one")
    monkeypatch.setattr(runtime, "default_schedule_reboot", assert_identity)
    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            now_monotonic=1000.0,
            now_wall_time=2000.0,
            connectivity_checker=probe,
            reconnect_action=reconnect,
        ),
    )
    delivered = _wifi_mail_delivery(monkeypatch)
    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )
    assert delivered
    assert not any(event.action == "wifi_watchdog_state_unavailable" for event in events)
    assert len(set(observed)) == 1
    if identity:
        assert observed[0] == identity


@pytest.mark.parametrize("action", ["wifi_reconnect_attempted", "wifi_reboot_requested"])
def test_delivered_wifi_alert_does_not_replay_after_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str
) -> None:
    config = _wifi_config()
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_reboot_enabled=action == "wifi_reboot_requested",
            wifi_reconnect_enabled=action == "wifi_reconnect_attempted",
            wifi_reconnect_after_minutes=1,
        ),
    )
    _legacy_wifi_state(
        tmp_path, phase="reboot_authorized" if action == "wifi_reboot_requested" else "pending"
    )
    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            now_monotonic=1000.0,
            now_wall_time=2000.0,
            connectivity_checker=lambda *_: False,
            reconnect_action=lambda _: False,
        ),
    )
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-one")
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: None)
    delivered = _wifi_mail_delivery(monkeypatch)
    for _ in range(3):
        runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert len(delivered) == 1
    assert (
        notifications.load_notification_outbox(notifications.notification_outbox_path(tmp_path))
        == []
    )


@pytest.mark.parametrize("after_replace", [False, True])
@pytest.mark.parametrize("checkpoint", ["identity", "receipt"])
def test_wifi_identity_and_receipt_checkpoint_failures_retry_durably(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, after_replace: bool, checkpoint: str
) -> None:
    config = _wifi_config()
    path = _legacy_wifi_state(tmp_path)
    real_persist = self_healing._persist_watchdog_json
    failed = False

    def persist(
        target: Path,
        payload: dict[str, object],
        error_type: type[self_healing.USBOTGWatchdogStateError] | type[WiFiWatchdogStateError],
        error_message: str,
    ) -> None:
        nonlocal failed
        match = (
            bool(payload.get("reconnect_notified_outcomes"))
            if checkpoint == "receipt"
            else bool(payload.get("recovery_handoff_id"))
        )
        if target == path and match and not failed:
            failed = True
            if after_replace:
                real_fsync = os.fsync
                sync_calls = 0

                def fail_parent_sync(fd: int) -> None:
                    nonlocal sync_calls
                    sync_calls += 1
                    if sync_calls == 2:
                        raise OSError("injected directory fsync failure after replace")
                    real_fsync(fd)

                with monkeypatch.context() as injection:
                    injection.setattr(os, "fsync", fail_parent_sync)
                    real_persist(target, payload, error_type, error_message)
            raise WiFiWatchdogStateError("injected checkpoint failure")
        real_persist(target, payload, error_type, error_message)

    event = SelfHealingEvent(action="wifi_reconnect_attempted", status="failed", details={})
    monkeypatch.setattr(self_healing, "_persist_watchdog_json", persist)
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    delivered = _wifi_mail_delivery(monkeypatch)
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert failed
    assert delivered == []
    real_confirm = self_healing.confirm_wifi_watchdog_state_durable

    def fail_barrier(_path: Path) -> None:
        raise WiFiWatchdogStateError("injected durability barrier failure")

    monkeypatch.setattr(runtime, "confirm_wifi_watchdog_state_durable", fail_barrier)
    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )
    assert any(event.action == "wifi_watchdog_state_unavailable" for event in events)
    assert delivered == []
    monkeypatch.setattr(runtime, "confirm_wifi_watchdog_state_durable", real_confirm)
    for _ in range(2):
        runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert len(delivered) == 1


def test_wifi_receipts_preserve_new_outcomes_boots_and_incidents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    config = replace(config, self_healing=replace(config.self_healing, wifi_reboot_enabled=True))
    path = _legacy_wifi_state(tmp_path)
    current_event = SelfHealingEvent(action="wifi_reconnect_attempted", status="failed", details={})
    boot = "boot-one"
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [current_event])
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: boot)
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: None)
    delivered = _wifi_mail_delivery(monkeypatch)

    def cycle() -> None:
        runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    cycle()
    current_event = replace(current_event, status="completed")
    cycle()
    assert len(delivered) == 2
    current_event = SelfHealingEvent(action="wifi_reboot_requested", status="completed", details={})
    cycle()
    boot = "boot-two"
    cycle()
    assert len(delivered) == 4
    current_event = SelfHealingEvent(
        action="wifi_connectivity_restored", status="completed", details={}
    )
    cycle()
    assert len(delivered) == 5
    payload = json.loads(path.read_text())
    assert payload["recovery_pending"] is False
    assert payload["reconnect_notified_outcomes"] == []
    _legacy_wifi_state(tmp_path)
    current_event = SelfHealingEvent(action="wifi_reconnect_attempted", status="failed", details={})
    cycle()
    assert len(delivered) == 6


def test_runtime_queues_wifi_recovery_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    event = SelfHealingEvent(
        action="wifi_reconnect_attempted",
        status="completed",
        details={"wifi_interface": "wlan0", "outage_seconds": 300},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert events == [event]
    queued = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert [(item.action, item.detail) for item in queued] == [
        ("wifi_reconnect_attempted", "Wi-Fi reconnect succeeded after 300 seconds on wlan0.")
    ]


def test_non_reboot_wifi_restoration_retries_after_queue_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    restored = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={"outage_seconds": 60},
    )
    calls = 0

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        nonlocal calls
        calls += 1
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.wifi_outage_started_monotonic = 10.0
        state.wifi_recovery_pending = False
        return [restored]

    def queue_once(**_kwargs: object) -> bool:
        if calls == 1:
            raise notifications.NotificationOutboxError("injected queue failure")
        return True

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(runtime, "queue_notification_event_once", queue_once)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    state = new_self_healing_state()

    first = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert first == [restored]
    assert state.wifi_outage_started_monotonic == 10.0

    second = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert second == [restored]
    assert calls == 2


def test_same_cycle_reconnect_restoration_is_queued_before_peer_reboot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    periodic = SelfHealingEvent(action="periodic_reboot_requested", status="completed", details={})
    reconnect = SelfHealingEvent(
        action="wifi_reconnect_attempted",
        status="completed",
        details={"wifi_interface": "wlan0", "outage_seconds": 60},
    )
    restored = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={"outage_seconds": 60},
    )
    order: list[str] = []

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.wifi_recovery_pending = True
        state.wifi_recovery_handoff_id = "handoff-peer"
        state.wifi_recovery_phase = "reconnect_pending"
        state.wifi_recovery_outage_seconds = 60
        state.wifi_recovery_interface = "wlan0"
        return [periodic, reconnect, restored]

    def queue_once(**kwargs: object) -> bool:
        order.append(str(kwargs["action"]))
        return True

    def deliver(**_kwargs: object) -> tuple[bool, str]:
        order.append("deliver")
        return False, "No pending notifications"

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(runtime, "queue_notification_event_once", queue_once)
    monkeypatch.setattr(runtime, "deliver_notification_outbox", deliver)
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: order.append("schedule"))

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert events == [periodic, reconnect, restored]
    assert order == [
        "wifi_reconnect_attempted",
        "wifi_connectivity_restored",
        "deliver",
        "schedule",
    ]


def test_runtime_schedules_wifi_reboot_after_queueing_notification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    event = SelfHealingEvent(
        action="wifi_reboot_requested",
        status="completed",
        details={"wifi_interface": "wlan0", "outage_seconds": 900},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    scheduled: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: scheduled.append(True))

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert events == [event]
    assert scheduled == [True]
    queued = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert queued[0].action == "wifi_reboot_requested"


def test_runtime_resumes_persisted_periodic_reboot_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(config.notifications, enabled=False),
        self_healing=replace(config.self_healing, periodic_reboot_enabled=True),
    )
    persisted = new_self_healing_state()
    persisted.periodic_reboot_requested = True
    persisted.periodic_reboot_scheduled_boot_id = "boot-one"
    persist_usb_path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    self_healing.persist_usb_otg_watchdog_state(persist_usb_path, persisted)
    scheduled: list[bool] = []
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [])
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-one")
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: scheduled.append(True))

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert [event.action for event in events] == ["periodic_reboot_requested"]
    assert scheduled == [True]


def test_periodic_authorization_is_consumed_after_a_new_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = replace(
        _config(),
        notifications=replace(_config().notifications, enabled=False),
        self_healing=replace(_config().self_healing, periodic_reboot_enabled=True),
    )
    persisted = new_self_healing_state()
    persisted.periodic_reboot_requested = True
    persisted.periodic_reboot_scheduled_boot_id = "boot-before"
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    self_healing.persist_usb_otg_watchdog_state(path, persisted)
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-after")
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [])
    scheduled: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: scheduled.append(True))

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    restored = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(path, restored)
    assert scheduled == []
    assert restored.periodic_reboot_requested is False
    assert restored.periodic_reboot_scheduled_boot_id == ""


def test_disabling_periodic_reboot_clears_its_scheduled_boot_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = _config()
    config = replace(
        base,
        notifications=replace(base.notifications, enabled=False),
        self_healing=replace(base.self_healing, periodic_reboot_enabled=False),
    )
    persisted = new_self_healing_state()
    persisted.periodic_reboot_requested = True
    persisted.periodic_reboot_scheduled_boot_id = "boot-one"
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    self_healing.persist_usb_otg_watchdog_state(path, persisted)
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-one")
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [])

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    restored = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(path, restored)
    assert restored.periodic_reboot_requested is False
    assert restored.periodic_reboot_scheduled_boot_id == ""


@pytest.mark.parametrize("policy", ["periodic", "wifi"])
def test_reboot_schedule_failure_retries_in_the_same_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, policy: str
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(config.notifications, enabled=False),
        self_healing=replace(
            config.self_healing,
            periodic_reboot_enabled=policy == "periodic",
            wifi_watchdog_enabled=policy == "wifi",
            wifi_reboot_enabled=policy == "wifi",
        ),
    )
    state = new_self_healing_state()
    if policy == "periodic":
        state.periodic_reboot_requested = True
    else:
        state.wifi_recovery_pending = True
        state.wifi_recovery_handoff_id = "handoff-retry"
        state.wifi_recovery_phase = "reboot_authorized"
    if policy == "periodic":
        self_healing.persist_usb_otg_watchdog_state(
            self_healing.usb_otg_watchdog_state_path(tmp_path), state
        )
    else:
        persist_wifi_watchdog_state(
            wifi_watchdog_state_path(tmp_path), state, preserve_pending=False
        )
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-one")
    event = SelfHealingEvent(
        action=("periodic_reboot_requested" if policy == "periodic" else "wifi_reboot_requested"),
        status="completed",
        details={},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    attempts = 0

    def schedule() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("scheduler unavailable")

    monkeypatch.setattr(runtime, "default_schedule_reboot", schedule)

    first = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )
    second = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert first[-1].action == "reboot_schedule_failed"
    assert second == [event]
    assert attempts == 2


def test_runtime_persists_new_periodic_reboot_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(config.notifications, enabled=False),
        self_healing=replace(config.self_healing, periodic_reboot_enabled=True),
    )
    event = SelfHealingEvent(action="periodic_reboot_requested", status="completed", details={})

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.periodic_reboot_requested = True
        return [event]

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: None)

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    restored = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(
        self_healing.usb_otg_watchdog_state_path(tmp_path), restored
    )
    assert restored.periodic_reboot_requested is True


def test_periodic_authorization_persists_when_usb_checkpoint_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(config.notifications, enabled=False),
        self_healing=replace(config.self_healing, periodic_reboot_enabled=True),
    )
    periodic = SelfHealingEvent(action="periodic_reboot_requested", status="completed", details={})
    usb_failure = SelfHealingEvent(
        action="usb_otg_watchdog_state_persist_failed", status="failed", details={}
    )

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.periodic_reboot_requested = True
        return [periodic, usb_failure]

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: None)

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert events == [usb_failure]
    restored = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(
        self_healing.usb_otg_watchdog_state_path(tmp_path), restored
    )
    assert restored.periodic_reboot_requested is True


def test_runtime_consumes_persisted_wifi_restoration_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_outage_seconds = 3600
    persisted.wifi_recovery_started_at = 1000.0
    persisted.wifi_recovery_handoff_id = "handoff-a"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), persisted, preserve_pending=False
    )
    event = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={"outage_seconds": 3600},
    )

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.wifi_recovery_outage_seconds = 3600
        return [event]

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )

    state = new_self_healing_state()
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)

    queued = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert [item.idempotency_key for item in queued] == ["wifi-recovery:handoff-a"]
    assert queued[0].detail == "Wi-Fi connectivity restored after 3600 seconds."
    assert state.wifi_recovery_pending is False


def test_runtime_clears_stale_transient_wifi_state_after_peer_consumes_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    state = new_self_healing_state()
    state.wifi_outage_started_monotonic = 10.0
    state.wifi_reconnect_attempted = True
    state.wifi_reboot_requested = True
    state.wifi_recovery_pending = True
    state.wifi_recovery_handoff_id = "consumed-by-peer"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), new_self_healing_state(), preserve_pending=False
    )

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        current = kwargs["state"]
        assert isinstance(current, self_healing.SelfHealingState)
        assert current.wifi_outage_started_monotonic is None
        assert current.wifi_reconnect_attempted is False
        assert current.wifi_reboot_requested is False
        return []

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )

    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)


def test_initial_wifi_restoration_checkpoint_failure_is_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    baseline = new_self_healing_state()
    persist_wifi_watchdog_state(wifi_watchdog_state_path(tmp_path), baseline)
    restored = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={"outage_seconds": 60},
    )
    evaluations = 0

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        nonlocal evaluations
        evaluations += 1
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.wifi_recovery_pending = True
        state.wifi_recovery_outage_seconds = 60
        state.wifi_recovery_interface = "wlan0"
        state.wifi_recovery_started_at = 1000.0
        state.wifi_recovery_handoff_id = "handoff-initial-checkpoint"
        state.wifi_recovery_phase = "pending"
        return [restored]

    original_persist = self_healing.persist_wifi_watchdog_state
    persist_calls = 0

    def fail_initial_checkpoint(
        path: Path,
        state: self_healing.SelfHealingState,
        *,
        preserve_pending: bool = True,
    ) -> None:
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            raise WiFiWatchdogStateError("injected initial checkpoint failure")
        original_persist(path, state, preserve_pending=preserve_pending)

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(runtime, "persist_wifi_watchdog_state", fail_initial_checkpoint)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    state = new_self_healing_state()

    first = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert any(event.action == "wifi_watchdog_state_unavailable" for event in first)
    assert not notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )

    second = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert second == [restored]
    assert evaluations == 2
    queued = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert [item.action for item in queued] == ["wifi_connectivity_restored"]


def test_invalid_wifi_state_preservation_returns_unavailable_event(
    tmp_path: Path,
) -> None:
    config = _wifi_config()
    config = replace(
        config,
        self_healing=replace(config.self_healing, wifi_watchdog_enabled=False),
    )
    path = wifi_watchdog_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{invalid\n", encoding="utf-8")

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert any(event.action == "wifi_watchdog_state_unavailable" for event in events)


def test_disabling_wifi_reboot_clears_persisted_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    config = replace(
        config,
        self_healing=replace(config.self_healing, wifi_reboot_enabled=False),
    )
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_handoff_id = "stale-authorized"
    persisted.wifi_recovery_phase = "reboot_authorized"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), persisted, preserve_pending=False
    )

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        assert state.wifi_recovery_pending is False
        return []

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    restored = new_self_healing_state()
    self_healing.load_wifi_watchdog_state(wifi_watchdog_state_path(tmp_path), restored)
    assert restored.wifi_recovery_pending is False
    assert restored.wifi_reboot_scheduled_boot_id == ""


def test_disabling_wifi_watchdog_clears_persisted_recovery_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    config = replace(config, self_healing=replace(config.self_healing, wifi_watchdog_enabled=False))
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_handoff_id = "stale-handoff"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), persisted, preserve_pending=False
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [])
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    reloaded = new_self_healing_state()
    self_healing.load_wifi_watchdog_state(wifi_watchdog_state_path(tmp_path), reloaded)
    assert reloaded.wifi_recovery_pending is False


def test_wifi_notification_queue_failure_is_reported_without_reboot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    event = SelfHealingEvent(
        action="wifi_reconnect_attempted",
        status="completed",
        details={"wifi_interface": "wlan0", "outage_seconds": 900},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    monkeypatch.setattr(
        runtime,
        "queue_notification_event",
        lambda **_kwargs: (_ for _ in ()).throw(
            notifications.NotificationOutboxError("injected queue failure")
        ),
    )
    scheduled: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: scheduled.append(True))

    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )

    assert scheduled == []
    assert events == [event]


def test_repeated_wifi_reboot_events_use_one_idempotent_notification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    config = replace(
        config,
        self_healing=replace(config.self_healing, wifi_reboot_enabled=True),
    )
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_handoff_id = "handoff-reboot"
    persisted.wifi_recovery_phase = "reboot_authorized"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), persisted, preserve_pending=False
    )
    event = SelfHealingEvent(
        action="wifi_reboot_requested",
        status="completed",
        details={"wifi_interface": "wlan0", "outage_seconds": 900},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: None)

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    queued = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert [item.idempotency_key for item in queued] == [
        f"wifi-reboot:handoff-reboot:{self_healing.default_reboot_boot_id()}"
    ]


def test_wifi_reboot_authorization_is_consumed_after_a_new_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_outage_seconds = 900
    persisted.wifi_recovery_started_at = 1000.0
    persisted.wifi_recovery_interface = "wlan0"
    persisted.wifi_recovery_handoff_id = "handoff-reboot"
    persisted.wifi_recovery_phase = "reboot_authorized"
    persisted.wifi_reboot_scheduled_boot_id = "boot-before"
    path = wifi_watchdog_state_path(tmp_path)
    persist_wifi_watchdog_state(path, persisted, preserve_pending=False)
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-after")
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [])
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    scheduled: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: scheduled.append(True))

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    restored = new_self_healing_state()
    self_healing.load_wifi_watchdog_state(path, restored)
    assert scheduled == []
    assert restored.wifi_recovery_pending is True
    assert restored.wifi_recovery_phase == "pending"
    assert restored.wifi_reboot_scheduled_boot_id == ""
    assert restored.wifi_recovery_handoff_id == "handoff-reboot"


def test_coalesced_periodic_and_wifi_reboots_share_one_scheduled_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = _config()
    config = replace(
        base,
        notifications=replace(base.notifications, enabled=False),
        self_healing=replace(
            base.self_healing,
            periodic_reboot_enabled=True,
            wifi_watchdog_enabled=True,
            wifi_reboot_enabled=True,
        ),
    )
    periodic_state = new_self_healing_state()
    periodic_state.periodic_reboot_requested = True
    self_healing.persist_usb_otg_watchdog_state(
        self_healing.usb_otg_watchdog_state_path(tmp_path), periodic_state
    )
    wifi_state = new_self_healing_state()
    wifi_state.wifi_recovery_pending = True
    wifi_state.wifi_recovery_handoff_id = "handoff-coalesced"
    wifi_state.wifi_recovery_phase = "reboot_authorized"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), wifi_state, preserve_pending=False
    )
    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-before")
    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        lambda **_kwargs: [
            SelfHealingEvent(action="wifi_reboot_requested", status="completed", details={})
        ],
    )
    scheduled: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: scheduled.append(True))

    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    restored_periodic = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(
        self_healing.usb_otg_watchdog_state_path(tmp_path), restored_periodic
    )
    restored_wifi = new_self_healing_state()
    self_healing.load_wifi_watchdog_state(wifi_watchdog_state_path(tmp_path), restored_wifi)
    assert scheduled == [True]
    assert restored_periodic.periodic_reboot_scheduled_boot_id == "boot-before"
    assert restored_wifi.wifi_reboot_scheduled_boot_id == "boot-before"

    monkeypatch.setattr(runtime, "default_reboot_boot_id", lambda: "boot-after")
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [])
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert scheduled == [True]


def test_restoration_queue_failure_keeps_handoff_for_a_later_cycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_handoff_id = "handoff-retry"
    persisted.wifi_recovery_phase = "pending"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), persisted, preserve_pending=False
    )
    event = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={"outage_seconds": 3600},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [event])
    attempts = 0

    def fail_once(**_kwargs: object) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise notifications.NotificationOutboxError("injected queue failure")
        return True

    monkeypatch.setattr(runtime, "queue_notification_event_once", fail_once)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    state = new_self_healing_state()
    first = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert first == [event]
    assert state.wifi_recovery_pending is True

    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert state.wifi_recovery_pending is False


def test_successful_reconnect_retries_before_restoration_ack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    reconnect = SelfHealingEvent(
        action="wifi_reconnect_attempted",
        status="completed",
        details={"wifi_interface": "wlan0", "outage_seconds": 60},
    )
    restored = SelfHealingEvent(
        action="wifi_connectivity_restored",
        status="completed",
        details={"outage_seconds": 60},
    )

    def evaluate(**kwargs: object) -> list[SelfHealingEvent]:
        state = kwargs["state"]
        assert isinstance(state, self_healing.SelfHealingState)
        state.wifi_recovery_pending = True
        state.wifi_recovery_handoff_id = "handoff-reconnect"
        state.wifi_recovery_phase = "reconnect_pending"
        state.wifi_recovery_outage_seconds = 60
        state.wifi_recovery_interface = "wlan0"
        return [reconnect, restored]

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    calls = 0

    def queue_once(**kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise notifications.NotificationOutboxError("injected queue failure")
        return True

    monkeypatch.setattr(runtime, "queue_notification_event_once", queue_once)
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    first = new_self_healing_state()
    first_events = runtime.run_self_healing(config=config, state=first, state_dir=tmp_path)
    assert first_events == [reconnect, restored]
    assert first.wifi_recovery_phase == "reconnect_pending"

    runtime.run_self_healing(config=config, state=first, state_dir=tmp_path)
    assert calls == 3
    assert first.wifi_recovery_pending is False


def test_reconnect_retry_is_not_claimed_while_wifi_remains_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _wifi_config()
    persisted = new_self_healing_state()
    persisted.wifi_recovery_pending = True
    persisted.wifi_recovery_handoff_id = "handoff-offline"
    persisted.wifi_recovery_phase = "reconnect_pending"
    persisted.wifi_recovery_outage_seconds = 60
    persisted.wifi_recovery_interface = "wlan0"
    persist_wifi_watchdog_state(
        wifi_watchdog_state_path(tmp_path), persisted, preserve_pending=False
    )
    offline = SelfHealingEvent(
        action="wifi_connectivity_lost",
        status="failed",
        details={"wifi_interface": "wlan0"},
    )
    monkeypatch.setattr(runtime, "evaluate_self_healing", lambda **_kwargs: [offline])
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        lambda **_kwargs: (False, "No pending notifications"),
    )
    state = new_self_healing_state()
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)

    assert not notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert state.wifi_recovery_phase == "reconnect_pending"


@pytest.mark.parametrize("failure", ["queue", "checkpoint", "ack", "ack_after_replace"])
@pytest.mark.parametrize("next_state", ["unhealthy", "healthy", "disabled"])
def test_pending_handoff_survives_failure_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, next_state: str
) -> None:
    config = _config()
    path = _seed(tmp_path)
    _evaluate(monkeypatch)
    delivered = _delivery(monkeypatch, path)
    persist = self_healing.persist_usb_otg_watchdog_state
    calls = 0

    def checkpoint(target: Path, state: self_healing.SelfHealingState) -> None:
        nonlocal calls
        calls += 1
        fail = (failure == "checkpoint" and calls == 1) or (
            failure in {"ack", "ack_after_replace"} and calls == 2
        )
        if not fail or failure == "ack_after_replace":
            persist(target, state)
        if fail:
            raise self_healing.USBOTGWatchdogStateError("injected checkpoint failure")

    queue = notifications.queue_notification_event_once

    def fail_queue(**kwargs: object) -> bool:
        raise notifications.NotificationOutboxError("injected queue failure")

    monkeypatch.setattr(runtime, "persist_usb_otg_watchdog_state", checkpoint)
    if failure == "queue":
        monkeypatch.setattr(runtime, "queue_notification_event_once", fail_queue)
    first = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )
    assert any("injected" in str(event.details) for event in first)
    assert delivered == []
    first_id = json.loads(path.read_text()).get("escalation_id")
    monkeypatch.setattr(runtime, "persist_usb_otg_watchdog_state", persist)
    monkeypatch.setattr(runtime, "queue_notification_event_once", queue)
    # Failure before the initial durable identity has no pending work yet.
    if failure != "checkpoint":
        _evaluate(monkeypatch, healthy=next_state == "healthy")
        if next_state == "disabled":
            config = replace(
                config, self_healing=replace(config.self_healing, usb_otg_watchdog_enabled=False)
            )
    fresh = new_self_healing_state()
    runtime.run_self_healing(config=config, state=fresh, state_dir=tmp_path)
    runtime.run_self_healing(config=config, state=fresh, state_dir=tmp_path)
    assert len(delivered) == 1
    assert "2 reboot attempt(s): original-reason" in delivered[0]
    assert not notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    if first_id and next_state == "unhealthy":
        assert json.loads(path.read_text())["escalation_id"] == first_id


@pytest.mark.parametrize("mode", ["summary", "individual"])
@pytest.mark.parametrize("fail_ack", [False, True])
def test_competing_processes_serialize_identity_ack_and_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, fail_ack: bool
) -> None:
    config = _config()
    config = replace(config, notifications=replace(config.notifications, offline_delivery=mode))
    path = _seed(tmp_path)
    _evaluate(monkeypatch)
    ctx = multiprocessing.get_context("fork")
    queued = ctx.Event()
    release = ctx.Event()
    competing = ctx.Event()
    delivery_log = tmp_path / "delivered.txt"
    persist = self_healing.persist_usb_otg_watchdog_state
    queue = notifications.queue_notification_event_once

    def sendmail(payload: str) -> subprocess.CompletedProcess[str]:
        assert not json.loads(path.read_text())["escalation_notification_pending"]
        with delivery_log.open("a") as handle:
            handle.write("delivered\n")
        return subprocess.CompletedProcess(["sendmail"], 0, "", "")

    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        partial(notifications.deliver_notification_outbox, runner=sendmail),
    )

    def first() -> None:
        def pause_queue(**kwargs: object) -> bool:
            # Test wrapper uses the production queue signature via captured arguments.
            result = queue(
                path=notifications.notification_outbox_path(tmp_path),
                config=config.notifications,
                action=str(kwargs["action"]),
                detail=str(kwargs["detail"]),
                idempotency_key=str(kwargs["idempotency_key"]),
            )
            queued.set()
            assert release.wait(10)
            return result

        def ack(target: Path, state: self_healing.SelfHealingState) -> None:
            if fail_ack and not state.usb_otg_escalation_notification_pending:
                raise self_healing.USBOTGWatchdogStateError("ack failure")
            persist(target, state)

        monkeypatch.setattr(runtime, "queue_notification_event_once", pause_queue)
        monkeypatch.setattr(runtime, "persist_usb_otg_watchdog_state", ack)
        runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)

    def second() -> None:
        stale = new_self_healing_state()
        competing.set()
        runtime.run_self_healing(config=config, state=stale, state_dir=tmp_path)

    workers = [ctx.Process(target=first), ctx.Process(target=second)]
    try:
        workers[0].start()
        assert queued.wait(10)
        identity = json.loads(path.read_text())["escalation_id"]
        workers[1].start()
        assert competing.wait(10)
        assert not delivery_log.exists()
        release.set()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert delivery_log.read_text().splitlines() == ["delivered"]
        assert json.loads(path.read_text())["escalation_id"] == identity
    finally:
        release.set()
        for worker in workers:
            if worker.pid is not None and worker.is_alive():
                worker.terminate()
                worker.join(5)


@pytest.mark.parametrize("used_rebind", [False, True])
def test_checkpoint_failure_defers_peer_reboots_without_consuming_usb_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, used_rebind: bool
) -> None:
    config = _config()
    config = replace(
        config,
        self_healing=replace(
            config.self_healing, periodic_reboot_enabled=True, periodic_reboot_hours=1
        ),
    )
    state = new_self_healing_state(now_monotonic=0)
    state.usb_otg_rebind_attempted = used_rebind
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    self_healing.persist_usb_otg_watchdog_state(path, state)
    _evaluate(monkeypatch)
    reboots: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: reboots.append(True))

    def fail_checkpoint(*args: object) -> None:
        raise self_healing.USBOTGWatchdogStateError("checkpoint failure")

    monkeypatch.setattr(runtime, "persist_usb_otg_watchdog_state", fail_checkpoint)
    events = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert reboots == []
    assert not state.periodic_reboot_requested
    assert not any(event.action.endswith("reboot_requested") for event in events)
    assert json.loads(path.read_text())["reboot_attempts_used"] == 0


@pytest.mark.parametrize("policy", ["disabled", "drop"])
def test_explicit_notification_policy_acknowledges_without_queuing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: str
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(
            config.notifications, enabled=policy != "disabled", offline_delivery="drop"
        ),
    )
    path = _seed(tmp_path)
    _evaluate(monkeypatch)
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert not json.loads(path.read_text())["escalation_notification_pending"]
    assert not notifications.notification_outbox_path(tmp_path).exists()


def test_corrupt_state_blocks_delivery_and_reports_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _seed(tmp_path)
    path.write_text("invalid")
    events = runtime.run_self_healing(
        config=_config(), state=new_self_healing_state(), state_dir=tmp_path
    )
    assert [event.action for event in events] == ["usb_otg_watchdog_state_unavailable"]
    assert path.read_text() == "invalid"


def test_pending_healthy_reset_allows_a_new_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    path = _seed(tmp_path)
    state = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(path, state)
    state.usb_otg_escalated = True
    state.usb_otg_escalation_notification_pending = True
    state.usb_otg_escalation_id = "old-episode"
    state.usb_otg_escalation_reason = "original-reason"
    state.usb_otg_escalation_reboot_attempts = 2
    self_healing.persist_usb_otg_watchdog_state(path, state)
    _evaluate(monkeypatch, healthy=True)
    delivered = _delivery(monkeypatch, path)
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert not json.loads(path.read_text())["escalated"]
    _evaluate(monkeypatch)
    events = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert "usb_otg_rebind_attempted" in [event.action for event in events]
    assert len(delivered) == 1


def test_pr14_pending_outbox_identity_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    path = _seed(tmp_path)
    state = new_self_healing_state()
    self_healing.load_usb_otg_watchdog_state(path, state)
    state.usb_otg_escalated = True
    state.usb_otg_escalation_notification_pending = True
    state.usb_otg_escalation_id = "old-episode"
    state.usb_otg_escalation_reason = "original-reason"
    state.usb_otg_escalation_reboot_attempts = 2
    self_healing.persist_usb_otg_watchdog_state(path, state)
    notifications.queue_notification_event_once(
        path=notifications.notification_outbox_path(tmp_path),
        config=config.notifications,
        action="usb_otg_recovery_exhausted",
        detail="existing payload",
        idempotency_key="usb-otg-escalation:old-episode",
    )
    _evaluate(monkeypatch)
    delivered = _delivery(monkeypatch, path)
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert len(delivered) == 1
    assert "Events retained: 1" in delivered[0]
    assert "existing payload" in delivered[0]


def test_fresh_runtime_reestablishes_durability_before_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    path = _seed(tmp_path)
    _evaluate(monkeypatch)
    delivered = _delivery(monkeypatch, path)
    fsync = os.fsync
    failed = False
    barriers = 0

    def fail_ack_sync(descriptor: int) -> None:
        nonlocal failed, barriers
        data = json.loads(path.read_text())
        if data.get("escalation_id") and not data["escalation_notification_pending"]:
            barriers += 1
            if not failed:
                failed = True
                raise OSError("post-replace fsync failure")
        fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_ack_sync)
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert failed and delivered == []
    barriers = 0
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert barriers >= 2
    assert len(delivered) == 1


def test_corrupt_usb_does_not_disable_existing_wifi_reconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            usb_otg_watchdog_enabled=False,
            wifi_watchdog_enabled=True,
            wifi_reconnect_enabled=True,
            wifi_reconnect_after_minutes=1,
        ),
    )
    path = _seed(tmp_path)
    path.write_text("invalid")
    state = new_self_healing_state(now_monotonic=0)
    state.wifi_outage_started_monotonic = 0
    reconnects: list[str] = []

    def reconnect(interface: str) -> bool:
        reconnects.append(interface)
        return True

    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            now_monotonic=120,
            connectivity_checker=lambda *_: False,
            reconnect_action=reconnect,
        ),
    )
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert reconnects == [config.self_healing.wifi_interface]
    assert not state.wifi_reboot_requested


def test_unchanged_usb_state_is_not_rewritten_for_wifi_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_watchdog_enabled=True,
            usb_otg_watchdog_enabled=False,
        ),
    )
    _evaluate(monkeypatch)
    writes: list[object] = []
    monkeypatch.setattr(
        runtime, "persist_usb_otg_watchdog_state", lambda *args: writes.append(args)
    )
    state = new_self_healing_state()
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert writes == []


@pytest.mark.parametrize("action", ["rebind", "reboot"])
@pytest.mark.parametrize("fault", ["before_replace", "after_replace", "interrupted_after_replace"])
def test_failed_action_checkpoint_resumes_without_another_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str, fault: str
) -> None:
    config = _config()
    state = new_self_healing_state()
    state.usb_otg_rebind_attempted = action == "reboot"
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    self_healing.persist_usb_otg_watchdog_state(path, state)
    actions: list[str] = []

    def rebind(*args: object) -> bool:
        actions.append("rebind")
        return True

    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            usb_otg_health_checker=lambda *_: USBOTGHealth(False, "offline", None, None),
            usb_otg_rebind_action=rebind,
            usb_otg_boot_id_reader=lambda: "boot-one",
        ),
    )
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: actions.append("reboot"))
    persist = self_healing.persist_usb_otg_watchdog_state
    failed = False

    def checkpoint(target: Path, current: self_healing.SelfHealingState) -> None:
        nonlocal failed
        if not failed:
            failed = True
            if fault != "before_replace":
                persist(target, current)
            if fault == "interrupted_after_replace":
                raise SystemExit("interrupted before action")
            raise self_healing.USBOTGWatchdogStateError("injected action checkpoint")
        persist(target, current)

    monkeypatch.setattr(runtime, "persist_usb_otg_watchdog_state", checkpoint)
    if fault == "interrupted_after_replace":
        with pytest.raises(SystemExit, match="interrupted"):
            runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    else:
        first = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
        assert any(event.action == "usb_otg_watchdog_state_persist_failed" for event in first)
    assert actions == []
    if fault != "before_replace":
        assert json.loads(path.read_text())["pending_action"] == action
    fresh = new_self_healing_state()
    runtime.run_self_healing(config=config, state=fresh, state_dir=tmp_path)
    assert actions == [action]
    assert fresh.usb_otg_reboot_attempts_used == (1 if action == "reboot" else 0)


@pytest.mark.parametrize("fault_after_replace", [False, True])
def test_rebind_ack_failure_is_repeatable_without_skipping_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault_after_replace: bool
) -> None:
    config = _config()
    config = replace(
        config, self_healing=replace(config.self_healing, usb_otg_reboot_enabled=False)
    )
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    calls: list[str] = []

    def rebind(*args: object) -> bool:
        calls.append("rebind")
        return True

    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            usb_otg_health_checker=lambda *_: USBOTGHealth(False, "offline", None, None),
            usb_otg_rebind_action=rebind,
        ),
    )
    persist = self_healing.persist_usb_otg_watchdog_state
    failed = False

    def checkpoint(target: Path, state: self_healing.SelfHealingState) -> None:
        nonlocal failed
        if not failed and calls:
            failed = True
            if fault_after_replace:
                persist(target, state)
            raise self_healing.USBOTGWatchdogStateError("intent clear failure")
        persist(target, state)

    monkeypatch.setattr(runtime, "persist_usb_otg_watchdog_state", checkpoint)
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert calls == ["rebind"]
    # Keep mail isolated; following escalation is intentionally dropped.
    config = replace(config, notifications=replace(config.notifications, enabled=False))
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert len(calls) == (1 if fault_after_replace else 2)
    assert json.loads(path.read_text())["rebind_attempted"]


@pytest.mark.parametrize(
    "cancel", ["healthy", "watchdog_disabled", "reboot_disabled", "lower_limit"]
)
def test_pending_reboot_resumes_once_per_reservation_and_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: str
) -> None:
    config = _config()
    config = replace(config, notifications=replace(config.notifications, enabled=False))
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    state = new_self_healing_state()
    state.usb_otg_rebind_attempted = True
    self_healing.persist_usb_otg_watchdog_state(path, state)
    reboots: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: reboots.append(True))
    _evaluate(monkeypatch)
    for _ in range(2):
        runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert len(reboots) == 2
    assert json.loads(path.read_text())["reboot_attempts_used"] == 1
    if cancel == "healthy":
        _evaluate(monkeypatch, healthy=True)
    elif cancel == "watchdog_disabled":
        config = replace(
            config, self_healing=replace(config.self_healing, usb_otg_watchdog_enabled=False)
        )
    elif cancel == "reboot_disabled":
        config = replace(
            config, self_healing=replace(config.self_healing, usb_otg_reboot_enabled=False)
        )
    else:
        # Reserve the second attempt on a fresh boot, then lower its limit.
        monkeypatch.setattr(
            runtime,
            "evaluate_self_healing",
            partial(
                self_healing.evaluate_self_healing,
                usb_otg_health_checker=lambda *_: USBOTGHealth(False, "offline", None, None),
                usb_otg_boot_id_reader=lambda: "boot-two",
            ),
        )
        runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
        assert json.loads(path.read_text())["reboot_attempts_used"] == 2
        config = replace(
            config, self_healing=replace(config.self_healing, usb_otg_reboot_attempts=1)
        )
    before = len(reboots)
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert len(reboots) == before
    assert json.loads(path.read_text())["pending_action"] == ""


def test_reboot_budget_counts_new_boots_and_scheduler_failure_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(config.notifications, enabled=False),
        self_healing=replace(config.self_healing, usb_otg_reboot_attempts=1),
    )
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    state = new_self_healing_state()
    state.usb_otg_rebind_attempted = True
    self_healing.persist_usb_otg_watchdog_state(path, state)
    _evaluate(monkeypatch)

    def failed_schedule() -> None:
        raise OSError("scheduler unavailable")

    monkeypatch.setattr(runtime, "default_schedule_reboot", failed_schedule)
    events = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert events[-1].action == "reboot_schedule_failed"
    assert not any(event.action == "usb_otg_reboot_requested" for event in events)
    reboots: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: reboots.append(True))
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert reboots == [True]
    assert json.loads(path.read_text())["reboot_attempts_used"] == 1
    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            usb_otg_health_checker=lambda *_: USBOTGHealth(False, "offline", None, None),
            usb_otg_boot_id_reader=lambda: "boot-two",
        ),
    )
    events = runtime.run_self_healing(
        config=config, state=new_self_healing_state(), state_dir=tmp_path
    )
    assert any(event.action == "usb_otg_recovery_exhausted" for event in events)
    assert reboots == [True]


def test_missing_boot_identity_does_not_block_rebind_but_defers_reboot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    calls: list[bool] = []

    def rebind(*args: object) -> bool:
        calls.append(True)
        return True

    def unavailable() -> str:
        raise self_healing.USBOTGWatchdogStateError("USB OTG reboot boot identity is unavailable")

    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            usb_otg_health_checker=lambda *_: USBOTGHealth(False, "offline", None, None),
            usb_otg_rebind_action=rebind,
            usb_otg_boot_id_reader=unavailable,
        ),
    )
    state = new_self_healing_state()
    runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert calls == [True]
    events = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert any(event.action == "usb_otg_watchdog_state_unavailable" for event in events)
    assert state.usb_otg_reboot_attempts_used == 0


@pytest.mark.parametrize(
    "action,boot_id,attempted,count",
    [
        ("invalid", "", True, 1),
        ("reboot", "", True, 1),
        ("rebind", "boot-one", True, 0),
        ("reboot", "boot-one", False, 1),
        ("reboot", "boot-one", True, 0),
    ],
)
def test_invalid_pending_action_state_is_rejected(
    tmp_path: Path, action: str, boot_id: str, attempted: bool, count: int
) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "rebind_attempted": attempted,
                "reboot_attempts_used": count,
                "escalated": False,
                "pending_action": action,
                "pending_reboot_boot_id": boot_id,
            }
        )
    )
    with pytest.raises(self_healing.USBOTGWatchdogStateError, match="invalid values"):
        self_healing.load_usb_otg_watchdog_state(path, new_self_healing_state())


def test_competing_same_boot_reboots_reuse_one_reserved_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    state = new_self_healing_state()
    state.usb_otg_rebind_attempted = True
    self_healing.persist_usb_otg_watchdog_state(path, state)
    _evaluate(monkeypatch)
    requests = tmp_path / "requests.txt"

    def reboot() -> None:
        with requests.open("a") as handle:
            handle.write("requested\n")

    monkeypatch.setattr(runtime, "default_schedule_reboot", reboot)
    ctx = multiprocessing.get_context("fork")

    def run() -> None:
        runtime.run_self_healing(
            config=_config(), state=new_self_healing_state(), state_dir=tmp_path
        )

    workers = [ctx.Process(target=run), ctx.Process(target=run)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert len(requests.read_text().splitlines()) == 2
        assert json.loads(path.read_text())["reboot_attempts_used"] == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


@pytest.mark.parametrize(
    "requests",
    [
        ["usb_otg_reboot_requested"],
        ["periodic_reboot_requested"],
        ["wifi_reboot_requested"],
        ["usb_otg_reboot_requested", "periodic_reboot_requested", "wifi_reboot_requested"],
    ],
)
def test_shared_scheduler_failure_identifies_requested_policies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requests: list[str]
) -> None:
    config = _config()
    config = replace(config, notifications=replace(config.notifications, enabled=False))
    state = new_self_healing_state()

    def evaluate(**kwargs: object) -> list[self_healing.SelfHealingEvent]:
        state.periodic_reboot_requested = True
        state.wifi_reboot_requested = True
        return [
            self_healing.SelfHealingEvent(action=action, status="requested", details={})
            for action in requests
        ]

    def schedule() -> None:
        raise OSError("scheduler unavailable")

    monkeypatch.setattr(runtime, "evaluate_self_healing", evaluate)
    monkeypatch.setattr(runtime, "default_schedule_reboot", schedule)
    events = runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert len(events) == 1
    assert events[0].action == "reboot_schedule_failed"
    assert events[0].details == {
        "reason": "Reboot scheduling failed",
        "requested_actions": requests,
    }
    assert not state.periodic_reboot_requested
    assert not state.wifi_reboot_requested


@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_duplicate_queue_failure_defers_ack_delivery_and_peer_reboot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    config = _config()
    config = replace(
        config,
        notifications=replace(config.notifications, offline_delivery=mode),
        self_healing=replace(config.self_healing, periodic_reboot_enabled=True),
    )
    path = _seed(tmp_path)
    outbox_path = notifications.notification_outbox_path(tmp_path)
    assert path.parent == outbox_path.parent
    _evaluate(monkeypatch)
    delivered = _delivery(monkeypatch, path)
    reboots: list[bool] = []
    monkeypatch.setattr(runtime, "default_schedule_reboot", lambda: reboots.append(True))
    sync_directory = notifications._fsync_directory
    calls = 0

    def fail_queue_sync(directory: Path) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise notifications.NotificationOutboxError("injected queue durability failure")
        sync_directory(directory)

    def run_fresh() -> list[self_healing.SelfHealingEvent]:
        state = new_self_healing_state()
        state.started_monotonic -= config.self_healing.periodic_reboot_hours * 3600 + 1
        return runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)

    monkeypatch.setattr(notifications, "_fsync_directory", fail_queue_sync)
    for _ in range(2):
        events = run_fresh()
        assert any(event.action == "usb_otg_recovery_notification_queue" for event in events)
        assert json.loads(path.read_text())["escalation_notification_pending"]
        assert len(notifications.load_notification_outbox(outbox_path)) == 1
        assert delivered == []
        assert reboots == []

    def interrupt_before_delivery(**kwargs: object) -> tuple[bool, str]:
        assert calls == 3
        assert not json.loads(path.read_text())["escalation_notification_pending"]
        raise SystemExit("stop before delivery")

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "deliver_notification_outbox", interrupt_before_delivery)
        with pytest.raises(SystemExit, match="stop before delivery"):
            run_fresh()
    assert len(notifications.load_notification_outbox(outbox_path)) == 1
    assert reboots == []
    run_fresh()
    assert len(delivered) == 1
    assert reboots == [True]
    assert notifications.load_notification_outbox(outbox_path) == []


@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_pending_mail_uses_delivery_locale_after_watchdog_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    config = _config()
    config = replace(
        config, notifications=replace(config.notifications, locale="it", offline_delivery=mode)
    )
    path = _seed(tmp_path)
    reason = "USB OTG backing image is missing"
    monkeypatch.setattr(
        runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            usb_otg_health_checker=lambda *_: USBOTGHealth(False, reason, None, None),
        ),
    )
    monkeypatch.setattr(
        runtime,
        "deliver_notification_outbox",
        partial(
            notifications.deliver_notification_outbox,
            runner=lambda payload: subprocess.CompletedProcess(["sendmail"], 75, "", "offline"),
        ),
    )
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert not json.loads(path.read_text())["escalation_notification_pending"]
    queued = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert len(queued) == 1
    assert queued[0].usb_otg_reason == reason
    assert queued[0].usb_otg_reboot_attempts == 2
    assert queued[0].idempotency_key.startswith("usb-otg-escalation:")
    _evaluate(monkeypatch, healthy=True)
    delivered = _delivery(monkeypatch, path)
    config = replace(config, notifications=replace(config.notifications, locale="de"))
    runtime.run_self_healing(config=config, state=new_self_healing_state(), state_dir=tmp_path)
    assert len(delivered) == 1
    assert translation_for("de").gettext(reason) in delivered[0]
    assert translation_for("it").gettext(reason) not in delivered[0]
    assert json.loads(path.read_text())["reboot_attempts_used"] == 0
    assert (
        notifications.load_notification_outbox(notifications.notification_outbox_path(tmp_path))
        == []
    )
