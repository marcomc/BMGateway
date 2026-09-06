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
from bm_gateway.config import AppConfig, load_config
from bm_gateway.self_healing import USBOTGHealth, new_self_healing_state


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
