"""Bounded system-mail notifications and offline incident delivery."""

from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from .config import NotificationsConfig

SendmailRunner = Callable[[str], subprocess.CompletedProcess[str]]
SYSTEM_SENDMAIL_PATH = "/usr/sbin/sendmail"
OFFLINE_DELIVERY_MODES = ("summary", "individual", "drop")


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
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    events: list[NotificationEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            occurred_at = datetime.fromisoformat(str(item["occurred_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        action = str(item.get("action", "")).strip()
        detail = str(item.get("detail", "")).strip()
        if action:
            events.append(NotificationEvent(action, detail, occurred_at))
    return events


def persist_notification_outbox(path: Path, events: list[NotificationEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([event.to_dict() for event in events], indent=2) + "\n",
        encoding="utf-8",
    )


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
        completed = runner(
            _message(
                recipient=config.recipient,
                subject=f"[BMGateway] notification test: {socket.gethostname()}",
                body="BMGateway system-mail notification delivery is working.\n",
            )
        )
    except OSError as error:
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
    events = load_notification_outbox(path)
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
        payloads = [
            _message(
                recipient=config.recipient, subject="[BMGateway] notification summary", body=body
            )
        ]
    else:
        payloads = [
            _message(
                recipient=config.recipient,
                subject=f"[BMGateway] {event.action}",
                body=f"{event.occurred_at.isoformat()}\n\n{event.detail}\n",
            )
            for event in events
        ]
    for payload in payloads:
        try:
            completed = runner(payload)
        except OSError as error:
            return False, str(error)
        if completed.returncode != 0:
            return False, completed.stderr.strip() or completed.stdout.strip() or "sendmail failed"
    path.unlink(missing_ok=True)
    return True, "Pending notifications delivered"
