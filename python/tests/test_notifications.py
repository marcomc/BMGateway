from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bm_gateway.config import NotificationsConfig
from bm_gateway.notifications import (
    deliver_notification_outbox,
    load_notification_outbox,
    queue_notification_event,
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
    )
    queue_notification_event(path=path, config=config, action="one", detail="first", now=now)
    queue_notification_event(
        path=path,
        config=config,
        action="two",
        detail="second",
        now=now + timedelta(minutes=1),
    )
    queue_notification_event(
        path=path,
        config=config,
        action="three",
        detail="third",
        now=now + timedelta(minutes=2),
    )

    assert [event.action for event in load_notification_outbox(path)] == ["two", "three"]


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


def test_failed_delivery_keeps_outbox(tmp_path: Path) -> None:
    path = tmp_path / "notification_outbox.json"
    config = NotificationsConfig(enabled=True, recipient="operator@example.test")
    queue_notification_event(path=path, config=config, action="wifi", detail="offline")

    delivered, detail = deliver_notification_outbox(path=path, config=config, runner=_failure)

    assert delivered is False
    assert detail == "temporary failure"
    assert [event.action for event in load_notification_outbox(path)] == ["wifi"]


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
    assert "[BMGateway] usb" in retry_payloads[0]

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
