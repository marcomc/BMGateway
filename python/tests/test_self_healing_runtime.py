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
