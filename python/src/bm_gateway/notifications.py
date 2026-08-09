"""Bounded system-mail notifications and offline incident delivery."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from .config import NotificationsConfig

SendmailRunner = Callable[[str], subprocess.CompletedProcess[str]]
SYSTEM_SENDMAIL_PATH = "/usr/sbin/sendmail"
OFFLINE_DELIVERY_MODES = ("summary", "individual", "drop")


class NotificationOutboxError(RuntimeError):
    """The pending-notification state cannot be safely read or written."""


@dataclass(frozen=True)
class NotificationEvent:
    action: str
    detail: str
    occurred_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "detail": self.detail,
            "occurred_at": self.occurred_at.isoformat(),
        }


def notification_outbox_path(state_dir: Path) -> Path:
    return state_dir / "runtime" / "notification_outbox.json"


def load_notification_outbox(path: Path) -> list[NotificationEvent]:
    try:
        raw_payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as error:
        raise NotificationOutboxError(f"Cannot read notification outbox: {error}") from error
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        raise NotificationOutboxError("Notification outbox contains invalid JSON") from error
    if not isinstance(payload, list):
        raise NotificationOutboxError("Notification outbox must contain a list of events")
    events: list[NotificationEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            raise NotificationOutboxError("Notification outbox contains an invalid event")
        try:
            occurred_at = datetime.fromisoformat(str(item["occurred_at"]))
        except (KeyError, TypeError, ValueError):
            raise NotificationOutboxError(
                "Notification outbox contains an invalid timestamp"
            ) from None
        action = str(item.get("action", "")).strip()
        detail = str(item.get("detail", "")).strip()
        if not action:
            raise NotificationOutboxError("Notification outbox contains an event without an action")
        events.append(NotificationEvent(action, detail, occurred_at))
    return events


def persist_notification_outbox(path: Path, events: list[NotificationEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([event.to_dict() for event in events], indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise NotificationOutboxError(f"Cannot persist notification outbox: {error}") from error


def queue_notification_event(
    *,
    path: Path,
    config: NotificationsConfig,
    action: str,
    detail: str,
    now: datetime | None = None,
) -> None:
    if not config.enabled or config.offline_delivery == "drop":
        return
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=config.offline_retention_days)
    events = [event for event in load_notification_outbox(path) if event.occurred_at >= cutoff]
    events.append(NotificationEvent(action=action, detail=detail, occurred_at=current))
    persist_notification_outbox(path, events[-config.offline_max_events :])


def _default_sendmail(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SYSTEM_SENDMAIL_PATH, "-t"], input=payload, text=True, capture_output=True, check=False
    )


def _message(*, recipient: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return message.as_string()


def send_test_notification(
    *,
    config: NotificationsConfig,
    runner: SendmailRunner = _default_sendmail,
) -> tuple[bool, str]:
    if not config.enabled:
        return False, "Notifications are disabled"
    if not config.recipient.strip():
        return False, "Notification recipient is not configured"
    try:
        payload = _message(
            recipient=config.recipient,
            subject=f"[BMGateway] notification test: {socket.gethostname()}",
            body="BMGateway system-mail notification delivery is working.\n",
        )
        completed = runner(payload)
    except (OSError, ValueError) as error:
        return False, str(error)
    if completed.returncode == 0:
        return True, "Test email sent"
    return False, completed.stderr.strip() or completed.stdout.strip() or "sendmail failed"


def deliver_notification_outbox(
    *,
    path: Path,
    config: NotificationsConfig,
    runner: SendmailRunner = _default_sendmail,
) -> tuple[bool, str]:
    try:
        events = load_notification_outbox(path)
    except NotificationOutboxError as error:
        return False, str(error)
    if not events:
        return True, "No pending notifications"
    if not config.enabled or not config.recipient.strip():
        return False, "Notification delivery is not configured"
    if config.offline_delivery == "drop":
        path.unlink(missing_ok=True)
        return True, "Pending notifications dropped"
    if config.offline_delivery == "summary":
        body = "\n".join(
            [
                f"BMGateway recovered notification delivery on {socket.gethostname()}.",
                "",
                f"Events retained: {len(events)}",
                f"First event: {events[0].occurred_at.isoformat()}",
                f"Last event: {events[-1].occurred_at.isoformat()}",
                "",
                *[
                    f"- {event.occurred_at.isoformat()} {event.action}: {event.detail}"
                    for event in events[-20:]
                ],
            ]
        )
        try:
            payloads = [
                _message(
                    recipient=config.recipient,
                    subject="[BMGateway] notification summary",
                    body=body,
                )
            ]
        except ValueError as error:
            return False, str(error)
    else:
        for index, event in enumerate(events):
            try:
                payload = _message(
                    recipient=config.recipient,
                    subject=f"[BMGateway] {event.action}",
                    body=f"{event.occurred_at.isoformat()}\n\n{event.detail}\n",
                )
                completed = runner(payload)
            except (OSError, ValueError) as error:
                return False, str(error)
            if completed.returncode != 0:
                return (
                    False,
                    completed.stderr.strip() or completed.stdout.strip() or "sendmail failed",
                )
            remaining = events[index + 1 :]
            try:
                if remaining:
                    persist_notification_outbox(path, remaining)
                else:
                    path.unlink(missing_ok=True)
            except (NotificationOutboxError, OSError) as error:
                return False, str(error)
        return True, "Pending notifications delivered"
    for payload in payloads:
        try:
            completed = runner(payload)
        except (OSError, ValueError) as error:
            return False, str(error)
        if completed.returncode != 0:
            return False, completed.stderr.strip() or completed.stdout.strip() or "sendmail failed"
    path.unlink(missing_ok=True)
    return True, "Pending notifications delivered"
