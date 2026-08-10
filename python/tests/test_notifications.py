from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bm_gateway.notifications as notifications_module
import pytest
from bm_gateway.config import NotificationsConfig
from bm_gateway.notifications import (
    NotificationOutboxError,
    deliver_notification_outbox,
    load_notification_outbox,
    persist_notification_outbox,
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
        path=path, config=config, action="wifi", detail="offline", now=queued_at
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
        )


def test_temporary_cleanup_failure_does_not_mask_persistence_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notification_outbox.json"

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("replace failed")

    def fail_unlink(target: Path, *, missing_ok: bool = False) -> None:
        raise OSError("cleanup failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(NotificationOutboxError, match="replace failed"):
        persist_notification_outbox(
            path,
            [
                notifications_module.NotificationEvent(
                    action="usb",
                    detail="offline",
                    occurred_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                )
            ],
        )


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
        path=path, config=config, action="wifi", detail="offline", now=queued_at
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
