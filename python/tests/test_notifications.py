from __future__ import annotations

import fcntl
import json
import os
import socket
import stat
import subprocess
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import Parser
from functools import partial
from pathlib import Path

import pytest
from bm_gateway import notifications, self_healing, self_healing_runtime
from bm_gateway.config import NotificationsConfig, load_config
from bm_gateway.localization import supported_locale_codes, translation_for
from bm_gateway.notifications import (
    NotificationEvent,
    NotificationOutboxError,
    deliver_notification_outbox,
    load_notification_outbox,
    notification_outbox_path,
    persist_notification_outbox,
    queue_notification_event,
    queue_notification_event_once,
    send_test_notification,
)


def _success(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["sendmail"], 0, "", "")


def _failure(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["sendmail"], 75, "", "temporary failure")


def test_queue_notification_event_prunes_by_retention_and_limit(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, offline_retention_days=1, offline_max_events=2)
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)

    queue_notification_event(
        path=path,
        config=config,
        action="old",
        detail="expired",
        now=now - timedelta(days=2),
        retention_now=now,
    )
    queue_notification_event(
        path=path,
        config=config,
        action="one",
        detail="first",
        now=now,
        retention_now=now,
    )
    queue_notification_event(
        path=path,
        config=config,
        action="two",
        detail="second",
        now=now + timedelta(minutes=1),
        retention_now=now,
    )
    queue_notification_event(
        path=path,
        config=config,
        action="three",
        detail="third",
        now=now + timedelta(minutes=2),
        retention_now=now,
    )

    assert [event.action for event in load_notification_outbox(path)] == ["two", "three"]


@pytest.mark.parametrize("queue_once", [False, True])
@pytest.mark.parametrize(
    "offline_max_events,expected",
    [(1, ["newest"]), (2, ["middle", "newest"])],
)
def test_queue_apis_sort_mixed_events_and_cap_by_newest_timestamp(
    tmp_path: Path,
    queue_once: bool,
    offline_max_events: int,
    expected: list[str],
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True,
        offline_retention_days=30,
        offline_max_events=offline_max_events,
    )
    retention_now = datetime.now(timezone.utc)
    enqueue = queue_notification_event_once if queue_once else queue_notification_event
    for action, occurred_at in (
        ("newest", retention_now - timedelta(days=1)),
        ("oldest", retention_now - timedelta(days=3)),
        ("middle", retention_now - timedelta(days=2)),
    ):
        enqueue(
            path=path,
            config=config,
            action=action,
            detail=action,
            idempotency_key=action,
            now=occurred_at,
            retention_now=retention_now,
        )

    assert [event.action for event in load_notification_outbox(path)] == expected


def test_persistence_normalizes_events_and_rejects_blank_actions(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    occurred_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
    persist_notification_outbox(
        path,
        [NotificationEvent(action=" usb ", detail=" offline ", occurred_at=occurred_at)],
    )

    assert load_notification_outbox(path) == [
        NotificationEvent(action="usb", detail="offline", occurred_at=occurred_at)
    ]
    with pytest.raises(NotificationOutboxError, match="without an action"):
        persist_notification_outbox(
            path,
            [NotificationEvent(action="  ", detail="offline", occurred_at=occurred_at)],
        )
    with pytest.raises(NotificationOutboxError, match="without an action"):
        queue_notification_event(
            path=path,
            config=NotificationsConfig(enabled=True),
            action="  ",
            detail="offline",
            now=occurred_at,
        )


@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_concurrent_enqueue_survives_delivery_transaction(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        offline_delivery=mode,
    )
    queue_notification_event(path=path, config=config, action="old", detail="included")
    producer_started = threading.Event()
    producer: threading.Thread | None = None

    def enqueue() -> None:
        producer_started.set()
        queue_notification_event(path=path, config=config, action="new", detail="pending")

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        nonlocal producer
        producer = threading.Thread(target=enqueue)
        producer.start()
        assert producer_started.wait(timeout=1)
        time.sleep(0.05)
        assert producer.is_alive()
        return _success(payload)

    assert deliver_notification_outbox(path=path, config=config, runner=send)[0] is True
    assert producer is not None
    producer.join(timeout=2)
    assert not producer.is_alive()
    assert [event.action for event in load_notification_outbox(path)] == ["new"]


def test_summary_delivery_sends_one_message_and_clears_outbox(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    queue_notification_event(path=path, config=config, action="wifi", detail="offline")
    queue_notification_event(path=path, config=config, action="usb", detail="unavailable")
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    delivered, detail = deliver_notification_outbox(
        path=path,
        config=config,
        runner=send,
    )

    assert delivered is True
    assert detail == "Pending notifications delivered"
    assert len(payloads) == 1
    assert "Events retained: 2" in payloads[0]
    assert not path.exists()


@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_delivery_canonicalizes_unsorted_persisted_events_chronologically(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / "notification_outbox.json"
    now = datetime.now(timezone.utc)
    persist_notification_outbox(
        path,
        [
            NotificationEvent("newest", "third", now - timedelta(hours=1)),
            NotificationEvent("oldest", "first", now - timedelta(hours=3)),
            NotificationEvent("middle", "second", now - timedelta(hours=2)),
        ],
    )
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    config = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        offline_delivery=mode,
    )
    assert deliver_notification_outbox(path=path, config=config, runner=send, now=now)[0]
    bodies = [Parser(policy=policy.default).parsestr(payload).get_content() for payload in payloads]
    if mode == "summary":
        assert len(bodies) == 1
        assert bodies[0].index("oldest") < bodies[0].index("middle") < bodies[0].index("newest")
    else:
        assert len(bodies) == 3
        assert [
            next(action for action in ("oldest", "middle", "newest") if action in body)
            for body in bodies
        ] == [
            "oldest",
            "middle",
            "newest",
        ]


def test_failed_delivery_keeps_outbox(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    queue_notification_event(path=path, config=config, action="wifi", detail="offline")

    delivered, detail = deliver_notification_outbox(path=path, config=config, runner=_failure)

    assert delivered is False
    assert detail == "temporary failure"
    assert [event.action for event in load_notification_outbox(path)] == ["wifi"]


@pytest.mark.parametrize("fail_first", [False, True])
def test_summary_preserves_every_retained_failure_beyond_twenty_events(
    tmp_path: Path, fail_first: bool
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", offline_max_events=25
    )
    queue_notification_event(
        path=path,
        config=config,
        action="usb_otg_recovery_exhausted",
        detail="",
        usb_otg_reason="USB OTG gadget is not configured",
        usb_otg_reboot_attempts=1,
    )
    for index in range(24):
        queue_notification_event(
            path=path,
            config=config,
            action="failure",
            detail=f"distinct failure [{index}]",
        )
    retained = load_notification_outbox(path)
    assert len(retained) == config.offline_max_events
    if fail_first:
        delivered, _ = deliver_notification_outbox(path=path, config=config, runner=_failure)
        assert delivered is False
        assert load_notification_outbox(path) == retained

    bodies: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        bodies.append(Parser(policy=policy.default).parsestr(payload).get_content())
        return _success(payload)

    delivered, _ = deliver_notification_outbox(path=path, config=config, runner=send)

    assert delivered is True
    assert len(bodies) == 1
    assert "Events retained: 25" in bodies[0]
    assert "USB OTG recovery exhausted" in bodies[0]
    assert "USB OTG gadget is not configured" in bodies[0]
    for index in range(24):
        assert f"distinct failure [{index}]" in bodies[0]
    assert not path.exists()


@pytest.mark.parametrize("locale", supported_locale_codes())
def test_summary_header_is_neutral_in_delivery_locale(tmp_path: Path, locale: str) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    queue_notification_event(path=path, config=config, action="failure", detail="unavailable")
    bodies: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        bodies.append(Parser(policy=policy.default).parsestr(payload).get_content())
        return _success(payload)

    delivered, _ = deliver_notification_outbox(
        path=path, config=replace(config, locale=locale), runner=send
    )

    assert delivered is True
    expected = translation_for(locale).gettext("BMGateway notification summary on {hostname}.")
    assert bodies[0].splitlines()[0] == expected.format(hostname=socket.gethostname())


@pytest.mark.parametrize("locale", supported_locale_codes())
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_wifi_action_labels_use_delivery_locale_in_decoded_mail(
    tmp_path: Path, locale: str, mode: str
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", offline_delivery=mode
    )
    labels = {
        "wifi_reconnect_attempted": "Wi-Fi reconnect attempted",
        "wifi_reboot_requested": "Wi-Fi reboot requested",
        "wifi_connectivity_restored": "Wi-Fi connectivity restored",
    }
    for action in labels:
        queue_notification_event(path=path, config=config, action=action, detail="watchdog event")
    assert deliver_notification_outbox(path=path, config=config, runner=_failure)[0] is False
    assert [event.action for event in load_notification_outbox(path)] == list(labels)
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    assert deliver_notification_outbox(
        path=path, config=replace(config, locale=locale), runner=send
    )[0]
    messages = [Parser(policy=policy.default).parsestr(payload) for payload in payloads]
    assert len(messages) == (1 if mode == "summary" else len(labels))
    translation = translation_for(locale)
    for index, (action, label) in enumerate(labels.items()):
        translated = translation.gettext(label)
        if locale != "en":
            assert translated != label
        message = messages[0 if mode == "summary" else index]
        body = message.get_content()
        assert translated in body
        assert action not in body
        assert action not in str(message["Subject"])
        if mode == "individual":
            assert translated in str(message["Subject"])
            assert translation.gettext("Event: {action}").format(action=translated) in body
    assert not path.exists()


def test_summary_delivery_reports_outbox_deletion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    queue_notification_event(path=path, config=config, action="wifi", detail="offline")
    original_unlink = Path.unlink

    def fail_outbox_unlink(target: Path, *, missing_ok: bool = False) -> None:
        if target == path:
            raise OSError("read-only outbox")
        original_unlink(target, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_outbox_unlink)

    delivered, detail = deliver_notification_outbox(path=path, config=config, runner=_success)

    assert delivered is False
    assert detail == "Cannot remove notification outbox: read-only outbox"
    assert path.exists()


@pytest.mark.parametrize("mode", ["drop", "individual"])
def test_delivery_modes_report_final_outbox_deletion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        offline_delivery=mode,
    )
    queue_notification_event(
        path=path,
        config=replace(config, offline_delivery="summary"),
        action="wifi",
        detail="offline",
    )

    def fail_unlink(target: Path, *, missing_ok: bool = False) -> None:
        raise OSError("read-only outbox")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    delivered, detail = deliver_notification_outbox(path=path, config=config, runner=_success)

    assert delivered is False
    assert detail == "Cannot remove notification outbox: read-only outbox"


def test_retention_prune_reports_outbox_deletion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        offline_retention_days=1,
    )
    queued_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    queue_notification_event(
        path=path,
        config=config,
        action="wifi",
        detail="offline",
        now=queued_at,
        retention_now=queued_at,
    )

    def fail_unlink(target: Path, *, missing_ok: bool = False) -> None:
        raise OSError("read-only outbox")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    delivered, detail = deliver_notification_outbox(
        path=path,
        config=config,
        runner=_success,
        now=queued_at + timedelta(days=2),
    )

    assert delivered is False
    assert detail == "Cannot remove notification outbox: read-only outbox"
    with pytest.raises(NotificationOutboxError, match="Cannot remove notification outbox"):
        queue_notification_event(
            path=path,
            config=config,
            action="usb",
            detail="offline",
            now=queued_at + timedelta(days=2),
            retention_now=queued_at + timedelta(days=2),
        )


def test_temporary_cleanup_failure_does_not_mask_persistence_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notification_outbox.json"

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("replace failed")

    def fail_unlink(target: Path, *, missing_ok: bool = False) -> None:
        raise OSError("cleanup failed")

    event = NotificationEvent(
        action="usb",
        detail="offline",
        occurred_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_replace)
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(NotificationOutboxError, match="replace failed"):
            persist_notification_outbox(path, [event])

    persist_notification_outbox(path, [event])
    assert load_notification_outbox(path) == [event]


def test_directory_and_lock_setup_failures_use_outbox_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runtime" / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")

    def fail_mkdir(*args: object, **kwargs: object) -> None:
        raise OSError("mkdir")

    def fail_flock(*args: object, **kwargs: object) -> None:
        raise OSError("flock")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "mkdir", fail_mkdir)
        with pytest.raises(NotificationOutboxError, match="Cannot lock notification outbox"):
            queue_notification_event(path=path, config=config, action="usb", detail="offline")
        assert deliver_notification_outbox(path=path, config=config)[0] is False

    with monkeypatch.context() as patch:
        patch.setattr(
            fcntl,
            "flock",
            fail_flock,
        )
        with pytest.raises(NotificationOutboxError, match="Cannot lock notification outbox"):
            persist_notification_outbox(
                path,
                [
                    NotificationEvent(
                        action="usb",
                        detail="offline",
                        occurred_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                    )
                ],
            )

    queue_notification_event(path=path, config=config, action="usb", detail="offline")
    assert [event.action for event in load_notification_outbox(path)] == ["usb"]


def test_parent_directory_is_synced_after_replace_and_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    original_fsync = os.fsync
    synced_types: list[str] = []

    def record_fsync(descriptor: int) -> None:
        synced_types.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", record_fsync)

    queue_notification_event(path=path, config=config, action="usb", detail="offline")
    assert synced_types[-1] == "directory"
    synced_types.clear()

    assert deliver_notification_outbox(path=path, config=config, runner=_success)[0] is True
    assert synced_types == ["directory"]


def test_directory_sync_failure_uses_controlled_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    original_fsync = os.fsync

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("directory fsync failed")
        original_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_directory_fsync)
        with pytest.raises(NotificationOutboxError, match="Cannot sync notification outbox"):
            queue_notification_event(path=path, config=config, action="usb", detail="offline")

    assert [event.action for event in load_notification_outbox(path)] == ["usb"]
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_directory_fsync)
        delivered, detail = deliver_notification_outbox(path=path, config=config, runner=_success)
    assert delivered is False
    assert "Cannot sync notification outbox directory" in detail


def test_corrupt_outbox_is_not_silently_discarded(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    path.write_text("{not valid JSON", encoding="utf-8")

    delivered, detail = deliver_notification_outbox(
        path=path,
        config=NotificationsConfig(enabled=True, recipient="operator@example.test"),
    )

    assert delivered is False
    assert detail == "Notification outbox contains invalid JSON"
    assert path.read_text(encoding="utf-8") == "{not valid JSON"


def test_offset_naive_timestamps_are_rejected_as_controlled_outbox_errors(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    path.write_text(
        '[{"action":"usb","detail":"offline","occurred_at":"2026-08-10T06:00:00"}]\n',
        encoding="utf-8",
    )
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")

    delivered, detail = deliver_notification_outbox(path=path, config=config)

    assert delivered is False
    assert detail == "Notification timestamps must include a UTC offset"
    with pytest.raises(NotificationOutboxError, match="must include a UTC offset"):
        queue_notification_event(
            path=tmp_path / "other.json",
            config=config,
            action="usb",
            detail="offline",
            now=datetime(2026, 8, 10, 6),
        )


def test_delivery_prunes_events_that_expire_after_queueing(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", offline_retention_days=1
    )
    queued_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    queue_notification_event(
        path=path,
        config=config,
        action="wifi",
        detail="offline",
        now=queued_at,
        retention_now=queued_at,
    )

    delivered, detail = deliver_notification_outbox(
        path=path,
        config=config,
        now=queued_at + timedelta(days=2),
    )

    assert delivered is True
    assert detail == "No pending notifications"
    assert not path.exists()


def test_individual_and_drop_delivery_modes(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        offline_delivery="individual",
    )
    queue_notification_event(path=path, config=config, action="wifi", detail="offline")
    queue_notification_event(path=path, config=config, action="usb", detail="unavailable")
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    delivered, _ = deliver_notification_outbox(
        path=path,
        config=config,
        runner=send,
    )

    assert delivered is True
    assert len(payloads) == 2

    queue_notification_event(path=path, config=config, action="wifi", detail="offline")
    queue_notification_event(path=path, config=config, action="usb", detail="unavailable")
    attempts: list[str] = []

    def fail_second(payload: str) -> subprocess.CompletedProcess[str]:
        attempts.append(payload)
        return _success(payload) if len(attempts) == 1 else _failure(payload)

    delivered, detail = deliver_notification_outbox(path=path, config=config, runner=fail_second)

    assert delivered is False
    assert detail == "temporary failure"
    assert [event.action for event in load_notification_outbox(path)] == ["usb"]

    retry_payloads: list[str] = []

    def retry(payload: str) -> subprocess.CompletedProcess[str]:
        retry_payloads.append(payload)
        return _success(payload)

    delivered, _ = deliver_notification_outbox(path=path, config=config, runner=retry)

    assert delivered is True
    assert len(retry_payloads) == 1
    assert "[BMGateway] notification: usb" in retry_payloads[0]

    queue_notification_event(
        path=path,
        config=NotificationsConfig(
            enabled=True,
            recipient="operator@example.test",
            offline_delivery="summary",
        ),
        action="wifi",
        detail="offline",
    )
    delivered, detail = deliver_notification_outbox(
        path=path,
        config=NotificationsConfig(
            enabled=True,
            recipient="operator@example.test",
            offline_delivery="drop",
        ),
    )

    assert delivered is True
    assert detail == "Pending notifications dropped"
    assert not path.exists()


def test_test_notification_requires_enabled_recipient_and_uses_sendmail() -> None:
    assert send_test_notification(config=NotificationsConfig())[0] is False
    assert send_test_notification(config=NotificationsConfig(enabled=True))[0] is False
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    sent, detail = send_test_notification(
        config=NotificationsConfig(enabled=True, recipient="operator@example.test"),
        runner=send,
    )

    assert sent is True
    assert detail == "Test email sent"
    assert "To: operator@example.test" in payloads[0]
    for recipient in (
        "one@example.test, two@example.test",
        ".operator@example.test",
        "operator..name@example.test",
        "operator.@example.test",
        "Operator <operator@example.test>",
        " operator@example.test",
    ):
        assert send_test_notification(
            config=NotificationsConfig(enabled=True, recipient=recipient)
        ) == (False, "Notification recipient is invalid")


def test_notification_payloads_use_configured_locale(tmp_path: Path) -> None:
    config = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        locale="it",
    )
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    assert send_test_notification(config=config, runner=send)[0] is True
    assert "test notifica" in payloads.pop()

    path = tmp_path / "notification_outbox.json"
    queue_notification_event(path=path, config=config, action="usb", detail="offline")
    assert deliver_notification_outbox(path=path, config=config, runner=send)[0] is True
    assert "riepilogo notifiche" in payloads.pop()

    individual = NotificationsConfig(
        enabled=True,
        recipient="operator@example.test",
        locale="it",
        offline_delivery="individual",
    )
    queue_notification_event(path=path, config=individual, action="usb", detail="offline")
    assert deliver_notification_outbox(path=path, config=individual, runner=send)[0] is True
    payload = payloads.pop()
    assert "notifica: usb" in payload
    assert "Evento: usb" in payload
    assert "Dettaglio: offline" in payload


def test_sendmail_timeout_is_a_controlled_failure_and_retains_outbox(tmp_path: Path) -> None:
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")

    def timeout(payload: str) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["sendmail"], 30)

    assert send_test_notification(config=config, runner=timeout)[0] is False

    path = tmp_path / "notification_outbox.json"
    queue_notification_event(path=path, config=config, action="usb", detail="offline")
    delivered, _ = deliver_notification_outbox(path=path, config=config, runner=timeout)
    assert delivered is False
    assert [event.action for event in load_notification_outbox(path)] == ["usb"]


_USB_HEALTH_REASONS = (
    "USB OTG backing image is missing",
    "USB OTG gadget is not configured",
    "USB OTG gadget status is unreadable",
    "USB OTG gadget is detached",
    "USB OTG controller state is unreadable",
    "UDC state is not configured",
)
_USB_DETAIL_TEMPLATE = (
    "USB OTG frame enumeration remained unavailable after {attempts} reboot attempt(s): {reason}"
)


@pytest.mark.parametrize("reason", _USB_HEALTH_REASONS)
@pytest.mark.parametrize("locale", supported_locale_codes())
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_replayed_usb_escalation_localizes_production_reason_in_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, locale: str, mode: str
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        notifications=replace(
            config.notifications,
            enabled=True,
            recipient="operator@example.test",
            locale=locale,
            offline_delivery=mode,
        ),
    )
    state = self_healing.new_self_healing_state()
    state.usb_otg_escalated = True
    state.usb_otg_escalation_notification_pending = True
    state.usb_otg_escalation_id = "pending-episode"
    state.usb_otg_escalation_reason = reason
    state.usb_otg_escalation_reboot_attempts = 2
    state_path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    self_healing.persist_usb_otg_watchdog_state(state_path, state)
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    monkeypatch.setattr(
        self_healing_runtime,
        "deliver_notification_outbox",
        partial(deliver_notification_outbox, runner=send),
    )
    # A fresh caller replays durable pending work even with the watchdog disabled.
    self_healing_runtime.run_self_healing(
        config=config, state=self_healing.new_self_healing_state(), state_dir=tmp_path
    )
    assert len(payloads) == 1
    message = Parser(policy=policy.default).parsestr(payloads[0])
    body = message.get_content()
    translated = translation_for(locale).gettext(reason)
    assert translated in body
    assert message["To"] == "operator@example.test"
    if locale != "en":
        assert translated != reason
        assert reason not in body
    assert json.loads(state_path.read_text())["escalation_reason"] == reason
    assert not load_notification_outbox(notification_outbox_path(tmp_path))


def test_replayed_usb_escalation_translates_known_queued_legacy_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        notifications=replace(
            config.notifications, enabled=True, recipient="operator@example.test", locale="it"
        ),
    )
    state = self_healing.new_self_healing_state()
    state.usb_otg_escalated = True
    state.usb_otg_escalation_notification_pending = True
    state.usb_otg_escalation_id = "legacy-episode"
    state.usb_otg_escalation_reason = "UDC state is not configured"
    state.usb_otg_escalation_reboot_attempts = 2
    self_healing.persist_usb_otg_watchdog_state(
        self_healing.usb_otg_watchdog_state_path(tmp_path), state
    )
    legacy_detail = (
        "USB OTG frame enumeration remained unavailable after "
        "2 reboot attempt(s): UDC state is not configured"
    )
    queue_notification_event_once(
        path=notification_outbox_path(tmp_path),
        config=config.notifications,
        action="usb_otg_recovery_exhausted",
        detail=legacy_detail,
        idempotency_key="usb-otg-escalation:legacy-episode",
    )
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    monkeypatch.setattr(
        self_healing_runtime,
        "deliver_notification_outbox",
        partial(deliver_notification_outbox, runner=send),
    )
    self_healing_runtime.run_self_healing(
        config=config, state=self_healing.new_self_healing_state(), state_dir=tmp_path
    )
    assert len(payloads) == 1
    message = Parser(policy=policy.default).parsestr(payloads[0])
    text = translation_for("it").gettext
    expected = text(_USB_DETAIL_TEMPLATE).format(
        attempts=2, reason=text("UDC state is not configured")
    )
    assert expected in message.get_content()


@pytest.mark.parametrize("source,target", [("en", "it"), ("it", "en")])
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_queued_usb_detail_uses_delivery_locale(
    tmp_path: Path, source: str, target: str, mode: str
) -> None:
    source_text = translation_for(source).gettext
    target_text = translation_for(target).gettext
    reason = "UDC state is not configured"
    path = tmp_path / "outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", locale=source, offline_delivery=mode
    )
    queue_notification_event(
        path=path,
        config=config,
        action="usb_otg_recovery_exhausted",
        detail=source_text(_USB_DETAIL_TEMPLATE).format(attempts=99, reason="stale detail"),
        usb_otg_reason=reason,
        usb_otg_reboot_attempts=2,
    )
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    assert deliver_notification_outbox(
        path=path, config=replace(config, locale=target), runner=send
    )[0]
    body = Parser(policy=policy.default).parsestr(payloads[0]).get_content()
    assert target_text(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=target_text(reason)) in body


@pytest.mark.parametrize("source", supported_locale_codes())
@pytest.mark.parametrize("reason", _USB_HEALTH_REASONS)
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_legacy_usb_delivery_relocalizes_all_shipped_templates(
    tmp_path: Path, source: str, reason: str, mode: str
) -> None:
    path = tmp_path / "outbox.json"
    text = translation_for(source).gettext
    occurred_at = datetime.now(timezone.utc).isoformat()
    for source_reason in {reason, text(reason)}:
        legacy = {
            "action": "usb_otg_recovery_exhausted",
            "detail": text(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=source_reason),
            "occurred_at": occurred_at,
            "idempotency_key": "original-episode",
        }
        for target in supported_locale_codes():
            path.write_text(json.dumps([legacy]))
            unchanged = path.read_bytes()
            event = load_notification_outbox(path)[0]
            assert path.read_bytes() == unchanged  # Reading compatibility data is not a migration.
            assert event.usb_otg_reason == reason
            assert event.usb_otg_reboot_attempts == 2
            assert event.occurred_at.isoformat() == occurred_at
            assert event.idempotency_key == "original-episode"
            config = NotificationsConfig(
                enabled=True,
                recipient="operator@example.test",
                locale=target,
                offline_delivery=mode,
            )
            payloads: list[str] = []

            def send(
                payload: str, captured: list[str] = payloads
            ) -> subprocess.CompletedProcess[str]:
                captured.append(payload)
                return _success(payload)

            assert deliver_notification_outbox(path=path, config=config, runner=send)[0]
            assert len(payloads) == 1
            message = Parser(policy=policy.default).parsestr(payloads[0])
            target_text = translation_for(target).gettext
            expected = target_text(_USB_DETAIL_TEMPLATE).format(
                attempts=2, reason=target_text(reason)
            )
            assert expected in message.get_content()
            assert target_text("USB OTG recovery exhausted") in message.get_content()


@pytest.mark.parametrize(
    "metadata",
    [
        {"usb_otg_reason": "UDC state is not configured"},
        {"usb_otg_reboot_attempts": 2},
        {"usb_otg_reason": None, "usb_otg_reboot_attempts": None},
        {"usb_otg_reason": None, "usb_otg_reboot_attempts": 2},
        {"usb_otg_reason": 1, "usb_otg_reboot_attempts": 2},
        {"usb_otg_reason": "known", "usb_otg_reboot_attempts": None},
        {"usb_otg_reason": "known", "usb_otg_reboot_attempts": True},
        {"usb_otg_reason": "known", "usb_otg_reboot_attempts": -1},
        {"usb_otg_reason": "known", "usb_otg_reboot_attempts": 1.5},
        {"usb_otg_reason": "known", "usb_otg_reboot_attempts": "2"},
        {"action": "other_action", "usb_otg_reason": "known", "usb_otg_reboot_attempts": 2},
    ],
)
def test_outbox_rejects_invalid_usb_metadata_without_writing(
    tmp_path: Path, metadata: dict[str, object]
) -> None:
    path = tmp_path / "outbox.json"
    raw = {
        "action": "usb_otg_recovery_exhausted",
        "detail": "original opaque detail",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    path.write_text(json.dumps([raw]))
    original = path.read_bytes()
    with pytest.raises(NotificationOutboxError, match="contains an invalid event"):
        load_notification_outbox(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("attempts", [0, 2, 2**40])
@pytest.mark.parametrize("reason", ["UDC state is not configured", "unrecognized diagnostic", ""])
def test_structured_usb_serialization_derives_detail_from_original_metadata(
    tmp_path: Path, attempts: int, reason: str
) -> None:
    original = NotificationEvent(
        action="usb_otg_recovery_exhausted",
        detail="conflicting detail must not become a second source of truth",
        occurred_at=datetime.now(timezone.utc),
        idempotency_key="original-episode",
        usb_otg_reason=reason,
        usb_otg_reboot_attempts=attempts,
    )
    expected = _USB_DETAIL_TEMPLATE.format(attempts=attempts, reason=reason)
    serialized = original.to_dict()
    assert serialized["detail"] == expected
    assert serialized["usb_otg_reason"] == reason
    assert serialized["usb_otg_reboot_attempts"] == attempts
    path = tmp_path / "outbox.json"
    persist_notification_outbox(path, [original])
    assert load_notification_outbox(path) == [replace(original, detail=expected)]


@pytest.mark.parametrize("once", [False, True])
def test_both_queue_apis_reject_partial_usb_metadata(tmp_path: Path, once: bool) -> None:
    queue = queue_notification_event_once if once else queue_notification_event
    with pytest.raises(NotificationOutboxError, match="contains an invalid event"):
        queue(
            path=tmp_path / "outbox.json",
            config=NotificationsConfig(enabled=True),
            action="usb_otg_recovery_exhausted",
            detail="opaque",
            idempotency_key="episode",
            usb_otg_reason="UDC state is not configured",
        )
    assert not (tmp_path / "outbox.json").exists()


@pytest.mark.parametrize("reason", ["Reboot scheduling failed", "unknown diagnostic"])
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_structured_usb_reason_uses_catalog_without_legacy_allowlist(
    tmp_path: Path, reason: str, mode: str
) -> None:
    path = tmp_path / "outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", locale="it", offline_delivery=mode
    )
    queue_notification_event(
        path=path,
        config=config,
        action="usb_otg_recovery_exhausted",
        detail="",
        usb_otg_reason=reason,
        usb_otg_reboot_attempts=2,
    )
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    assert deliver_notification_outbox(path=path, config=config, runner=send)[0]
    text = translation_for("it").gettext
    expected = text(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=text(reason))
    assert expected in Parser(policy=policy.default).parsestr(payloads[0]).get_content()


@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_failed_delivery_and_duplicate_preserve_usb_facts_for_new_locale(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / "outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", locale="it", offline_delivery=mode
    )
    reason = "USB OTG gadget is detached"
    occurred_at = datetime.now(timezone.utc)
    assert queue_notification_event_once(
        path=path,
        config=config,
        action="usb_otg_recovery_exhausted",
        detail="",
        idempotency_key="original-episode",
        usb_otg_reason=reason,
        usb_otg_reboot_attempts=2,
        now=occurred_at,
    )
    original = load_notification_outbox(path)
    assert not deliver_notification_outbox(path=path, config=config, runner=_failure)[0]
    assert not queue_notification_event_once(
        path=path,
        config=replace(config, locale="de"),
        action="usb_otg_recovery_exhausted",
        detail="replacement payload",
        idempotency_key="original-episode",
        usb_otg_reason="USB OTG backing image is missing",
        usb_otg_reboot_attempts=4,
        now=occurred_at + timedelta(seconds=1),
    )
    assert load_notification_outbox(path) == original
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    assert deliver_notification_outbox(path=path, config=replace(config, locale="de"), runner=send)[
        0
    ]
    text = translation_for("de").gettext
    body = Parser(policy=policy.default).parsestr(payloads[0]).get_content()
    assert text(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=text(reason)) in body
    assert occurred_at.isoformat() in body


_WIFI_DETAIL_CASES = (
    (
        "wifi_reconnect_attempted",
        "completed",
        "Wi-Fi reconnect succeeded after {outage_seconds} seconds on {wifi_interface}.",
    ),
    (
        "wifi_reconnect_attempted",
        "failed",
        "Wi-Fi reconnect failed after {outage_seconds} seconds on {wifi_interface}.",
    ),
    (
        "wifi_reboot_requested",
        "completed",
        "Wi-Fi reboot requested after {outage_seconds} seconds on {wifi_interface}.",
    ),
    (
        "wifi_connectivity_restored",
        "completed",
        "Wi-Fi connectivity restored after {outage_seconds} seconds.",
    ),
)


@pytest.mark.parametrize("action,outcome,template", _WIFI_DETAIL_CASES)
@pytest.mark.parametrize("locale", supported_locale_codes())
@pytest.mark.parametrize("mode", ["summary", "individual"])
@pytest.mark.parametrize("queue_once", [False, True])
def test_wifi_facts_survive_failed_delivery_and_render_in_new_locale(
    tmp_path: Path,
    action: str,
    outcome: str,
    template: str,
    locale: str,
    mode: str,
    queue_once: bool,
) -> None:
    path = notification_outbox_path(tmp_path)
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", offline_delivery=mode
    )
    queued_at = datetime.now(timezone.utc)
    enqueue = queue_notification_event_once if queue_once else queue_notification_event
    enqueue(
        path=path,
        config=config,
        action=action,
        detail="",
        idempotency_key="stable-incident-event",
        wifi_outcome=outcome,
        wifi_interface="wlan0",
        wifi_outage_seconds=123,
        now=queued_at,
    )
    assert deliver_notification_outbox(path=path, config=config, runner=_failure)[0] is False
    # A newly loaded queue keeps canonical facts and identity, independent of locale.
    pending = load_notification_outbox(path)
    assert len(pending) == 1
    assert pending[0].wifi_outcome == outcome
    assert pending[0].wifi_interface == "wlan0"
    assert pending[0].wifi_outage_seconds == 123
    assert pending[0].idempotency_key == "stable-incident-event"
    assert pending[0].occurred_at == queued_at
    if queue_once:
        assert (
            enqueue(
                path=path,
                config=config,
                action=action,
                detail="duplicate cannot replace original facts",
                idempotency_key="stable-incident-event",
                wifi_outcome=outcome,
                wifi_interface="wlan1",
                wifi_outage_seconds=999,
            )
            is False
        )
        assert load_notification_outbox(path) == pending
    bodies: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        bodies.append(Parser(policy=policy.default).parsestr(payload).get_content())
        return _success(payload)

    assert deliver_notification_outbox(
        path=path, config=replace(config, locale=locale), runner=send
    )[0]
    expected = (
        translation_for(locale).gettext(template).format(wifi_interface="wlan0", outage_seconds=123)
    )
    assert len(bodies) == 1
    assert expected in bodies[0]
    if locale != "en":
        assert template.format(wifi_interface="wlan0", outage_seconds=123) not in bodies[0]
    assert not path.exists()


@pytest.mark.parametrize("action,outcome,template", _WIFI_DETAIL_CASES)
@pytest.mark.parametrize("locale", supported_locale_codes())
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_recognized_legacy_wifi_templates_relocalize_on_retry(
    tmp_path: Path, action: str, outcome: str, template: str, locale: str, mode: str
) -> None:
    path = notification_outbox_path(tmp_path)
    path.parent.mkdir(parents=True)
    occurred_at = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps(
            [
                {
                    "action": action,
                    "detail": translation_for(locale)
                    .gettext(template)
                    .format(wifi_interface="wlan0", outage_seconds=123),
                    "occurred_at": occurred_at,
                    "idempotency_key": "legacy-incident",
                }
            ]
        )
    )
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", locale=locale, offline_delivery=mode
    )
    assert deliver_notification_outbox(path=path, config=config, runner=_failure)[0] is False
    event = load_notification_outbox(path)[0]
    assert event.wifi_outcome == outcome
    assert event.wifi_outage_seconds == 123
    assert event.idempotency_key == "legacy-incident"
    assert event.occurred_at.isoformat() == occurred_at
    bodies: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        bodies.append(Parser(policy=policy.default).parsestr(payload).get_content())
        return _success(payload)

    assert deliver_notification_outbox(
        path=path, config=replace(config, locale="it" if locale == "en" else "en"), runner=send
    )[0]
    expected_locale = "it" if locale == "en" else "en"
    assert (
        translation_for(expected_locale)
        .gettext(template)
        .format(wifi_interface="wlan0", outage_seconds=123)
        in bodies[0]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("wifi_outcome", None),
        ("wifi_outcome", "unknown"),
        ("wifi_outcome", 1),
        ("wifi_interface", None),
        ("wifi_interface", 1),
        ("wifi_outage_seconds", None),
        ("wifi_outage_seconds", -1),
        ("wifi_outage_seconds", True),
        ("wifi_outage_seconds", "3"),
    ],
)
def test_malformed_explicit_wifi_fields_are_not_legacy(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "outbox.json"
    event = NotificationEvent(
        action="wifi_reconnect_attempted",
        detail="",
        occurred_at=datetime.now(timezone.utc),
        wifi_outcome="failed",
        wifi_interface="wlan0",
        wifi_outage_seconds=123,
    ).to_dict()
    malformed: dict[str, object] = dict(event)
    malformed[field] = value
    path.write_text(json.dumps([malformed]))
    with pytest.raises(NotificationOutboxError, match="invalid event"):
        load_notification_outbox(path)
    del malformed[field]
    path.write_text(json.dumps([malformed]))
    with pytest.raises(NotificationOutboxError, match="invalid event"):
        load_notification_outbox(path)


@pytest.mark.parametrize(
    "detail",
    [
        "operator freeform warning",
        "prefix Wi-Fi reconnect failed after 1 seconds on wlan0.",
        "Wi-Fi reconnect failed after 1 seconds on wlan0. Additional failure.",
    ],
)
def test_unknown_legacy_wifi_detail_is_preserved(tmp_path: Path, detail: str) -> None:
    path = tmp_path / "outbox.json"
    event = NotificationEvent(
        action="wifi_reconnect_attempted", detail=detail, occurred_at=datetime.now(timezone.utc)
    )
    persist_notification_outbox(path, [event])
    assert load_notification_outbox(path) == [event]


def test_ambiguous_legacy_wifi_outcome_is_not_inferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = "Reconnect after {outage_seconds} seconds on {wifi_interface}."

    class AmbiguousTranslation:
        def gettext(self, key: str) -> str:
            return template if key.startswith("Wi-Fi reconnect ") else key

    monkeypatch.setattr(notifications, "translation_for", lambda locale: AmbiguousTranslation())
    path = tmp_path / "outbox.json"
    event = NotificationEvent(
        action="wifi_reconnect_attempted",
        detail=template.format(outage_seconds=123, wifi_interface="wlan0"),
        occurred_at=datetime.now(timezone.utc),
    )
    persist_notification_outbox(path, [event])
    assert load_notification_outbox(path) == [event]


@pytest.mark.parametrize("queue_once", [False, True])
@pytest.mark.parametrize(
    "action,outcome",
    [
        ("wifi_connectivity_restored", "failed"),
        ("usb_otg_recovery_exhausted", "completed"),
        ("wifi_reconnect_attempted", None),
    ],
)
def test_both_queue_apis_reject_inconsistent_wifi_facts(
    tmp_path: Path, queue_once: bool, action: str, outcome: str | None
) -> None:
    enqueue = queue_notification_event_once if queue_once else queue_notification_event
    path = tmp_path / "outbox.json"
    with pytest.raises(NotificationOutboxError, match="invalid event"):
        enqueue(
            path=path,
            config=NotificationsConfig(enabled=True),
            action=action,
            detail="",
            idempotency_key="episode",
            wifi_outcome=outcome,
            wifi_interface="wlan0",
            wifi_outage_seconds=123,
        )
    assert not path.exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_partial_individual_delivery_preserves_canonical_usb_metadata(
    tmp_path: Path, legacy: bool
) -> None:
    path = tmp_path / "outbox.json"
    config = NotificationsConfig(
        enabled=True, recipient="operator@example.test", locale="it", offline_delivery="individual"
    )
    queue_notification_event(path=path, config=config, action="first", detail="deliver first")
    reason = "USB OTG gadget is detached"
    queue_notification_event(
        path=path,
        config=config,
        action="usb_otg_recovery_exhausted",
        detail="",
        idempotency_key="second-event",
        usb_otg_reason=reason,
        usb_otg_reboot_attempts=2,
    )
    if legacy:
        rows = json.loads(path.read_text())
        rows[1].pop("usb_otg_reason")
        rows[1].pop("usb_otg_reboot_attempts")
        text = translation_for("it").gettext
        rows[1]["detail"] = text(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=text(reason))
        path.write_text(json.dumps(rows))
    second = load_notification_outbox(path)[1]
    sent: list[str] = []

    def partial_send(payload: str) -> subprocess.CompletedProcess[str]:
        sent.append(payload)
        return _success(payload) if len(sent) == 1 else _failure(payload)

    assert not deliver_notification_outbox(path=path, config=config, runner=partial_send)[0]
    assert load_notification_outbox(path) == [second]
    retained = json.loads(path.read_text())[0]
    assert retained["usb_otg_reason"] == reason
    assert retained["usb_otg_reboot_attempts"] == 2
    sent.clear()

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        sent.append(payload)
        return _success(payload)

    assert deliver_notification_outbox(path=path, config=replace(config, locale="fr"), runner=send)[
        0
    ]
    text = translation_for("fr").gettext
    body = Parser(policy=policy.default).parsestr(sent[0]).get_content()
    assert text(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=text(reason)) in body


@pytest.mark.parametrize(
    "action,detail",
    [
        ("usb_otg_recovery_exhausted", "operator-provided arbitrary detail"),
        (
            "other_action",
            _USB_DETAIL_TEMPLATE.format(attempts=2, reason="UDC state is not configured"),
        ),
        ("usb_otg_recovery_exhausted", _USB_DETAIL_TEMPLATE.format(attempts=2, reason="unknown")),
        (
            "usb_otg_recovery_exhausted",
            "Earlier: "
            + _USB_DETAIL_TEMPLATE.format(attempts=2, reason="UDC state is not configured"),
        ),
        *[
            (
                "usb_otg_recovery_exhausted",
                _USB_DETAIL_TEMPLATE.format(attempts=count, reason="UDC state is not configured"),
            )
            for count in ["-1", "1.5", "02", "9" * 5000]
        ],
    ],
    ids=["freeform", "non-usb", "unknown-reason", "prefix", "negative", "float", "zero", "huge"],
)
@pytest.mark.parametrize("mode", ["summary", "individual"])
def test_unrecognized_legacy_notification_remains_unchanged(
    tmp_path: Path, action: str, detail: str, mode: str
) -> None:
    path = tmp_path / "outbox.json"
    event = NotificationEvent(action=action, detail=detail, occurred_at=datetime.now(timezone.utc))
    persist_notification_outbox(path, [event])
    assert load_notification_outbox(path) == [event]
    assert "usb_otg_reason" not in json.loads(path.read_text())[0]
    payloads: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        payloads.append(payload)
        return _success(payload)

    assert deliver_notification_outbox(
        path=path,
        config=NotificationsConfig(
            enabled=True, recipient="operator@example.test", locale="it", offline_delivery=mode
        ),
        runner=send,
    )[0]
    assert detail in Parser(policy=policy.default).parsestr(payloads[0]).get_content()


def test_ambiguous_legacy_usb_reason_is_not_reinterpreted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    translation = translation_for("it")
    repeated = "diagnostica ambigua"
    for reason in _USB_HEALTH_REASONS[:2]:
        monkeypatch.setitem(translation.catalog, reason, repeated)
    detail = translation.gettext(_USB_DETAIL_TEMPLATE).format(attempts=2, reason=repeated)
    event = NotificationEvent(
        action="usb_otg_recovery_exhausted", detail=detail, occurred_at=datetime.now(timezone.utc)
    )
    path = tmp_path / "outbox.json"
    persist_notification_outbox(path, [event])
    assert load_notification_outbox(path) == [event]


@pytest.mark.parametrize("failure_stage", ["file", "directory"])
def test_duplicate_enqueue_reestablishes_its_own_durability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    path = tmp_path / "outbox.json"
    config = NotificationsConfig(enabled=True)

    def enqueue(detail: str) -> bool:
        return queue_notification_event_once(
            path=path,
            config=config,
            action="usb_otg_recovery_exhausted",
            detail=detail,
            idempotency_key="stable-episode",
        )

    def initial_failure(directory: Path) -> None:
        raise NotificationOutboxError("injected post-replace failure")

    with monkeypatch.context() as patch:
        patch.setattr(notifications, "_fsync_directory", initial_failure)
        with pytest.raises(NotificationOutboxError):
            enqueue("original")
    original = load_notification_outbox(path)
    assert len(original) == 1
    fsync = os.fsync
    synced: list[str] = []

    def fail_sync(fd: int) -> None:
        stage = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        if stage == failure_stage:
            raise OSError("injected duplicate sync failure")
        fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_sync)
        with pytest.raises(NotificationOutboxError, match="injected duplicate sync failure"):
            enqueue("replacement must not overwrite original")

    def record_sync(fd: int) -> None:
        synced.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", record_sync)
        assert enqueue("replacement must not overwrite original") is False
    assert synced == ["file", "directory"]
    assert load_notification_outbox(path) == original
