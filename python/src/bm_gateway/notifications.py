"""Bounded system-mail notifications and offline incident delivery."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Iterator

from .config import NotificationsConfig, is_valid_notification_recipient
from .localization import translation_for

SendmailRunner = Callable[[str], subprocess.CompletedProcess[str]]
SYSTEM_SENDMAIL_PATH = "/usr/sbin/sendmail"
OFFLINE_DELIVERY_MODES = ("summary", "individual", "drop")
SENDMAIL_TIMEOUT_SECONDS = 30


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


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise NotificationOutboxError(
            f"Cannot sync notification outbox directory: {error}"
        ) from error


@contextmanager
def _notification_outbox_lock(path: Path) -> Iterator[None]:
    lock_handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.parent / f".{path.name}.lock"
        lock_handle = lock_path.open(mode="a+", encoding="utf-8")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
    except OSError as error:
        if lock_handle is not None:
            lock_handle.close()
        raise NotificationOutboxError(f"Cannot lock notification outbox: {error}") from error
    try:
        yield
    finally:
        assert lock_handle is not None
        lock_handle.close()


def _remove_notification_outbox(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise NotificationOutboxError(f"Cannot remove notification outbox: {error}") from error
    _fsync_directory(path.parent)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise NotificationOutboxError("Notification timestamps must include a UTC offset")
    return value.astimezone(timezone.utc)


def _canonical_event(*, action: object, detail: object, occurred_at: datetime) -> NotificationEvent:
    normalized_action = str(action).strip()
    if not normalized_action:
        raise NotificationOutboxError("Notification outbox contains an event without an action")
    return NotificationEvent(
        action=normalized_action,
        detail=str(detail).strip(),
        occurred_at=_aware_utc(occurred_at),
    )


def _load_notification_outbox_unlocked(path: Path) -> list[NotificationEvent]:
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
        events.append(
            _canonical_event(
                action=item.get("action", ""),
                detail=item.get("detail", ""),
                occurred_at=occurred_at,
            )
        )
    return events


def load_notification_outbox(path: Path) -> list[NotificationEvent]:
    with _notification_outbox_lock(path):
        return _load_notification_outbox_unlocked(path)


def _persist_notification_outbox_unlocked(path: Path, events: list[NotificationEvent]) -> None:
    normalized_events: list[NotificationEvent] = []
    for event in events:
        normalized_events.append(
            _canonical_event(
                action=event.action,
                detail=event.detail,
                occurred_at=event.occurred_at,
            )
        )
    payload = json.dumps([event.to_dict() for event in normalized_events], indent=2) + "\n"
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
        _fsync_directory(path.parent)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise NotificationOutboxError(f"Cannot persist notification outbox: {error}") from error


def persist_notification_outbox(path: Path, events: list[NotificationEvent]) -> None:
    with _notification_outbox_lock(path):
        _persist_notification_outbox_unlocked(path, events)


def _retained_events(
    *, path: Path, config: NotificationsConfig, now: datetime
) -> list[NotificationEvent]:
    now = _aware_utc(now)
    events = _load_notification_outbox_unlocked(path)
    cutoff = now - timedelta(days=config.offline_retention_days)
    retained = [event for event in events if event.occurred_at >= cutoff]
    retained = retained[-config.offline_max_events :]
    if len(retained) != len(events):
        if retained:
            _persist_notification_outbox_unlocked(path, retained)
        else:
            _remove_notification_outbox(path)
    return retained


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
    with _notification_outbox_lock(path):
        current = _aware_utc(now or datetime.now(timezone.utc))
        events = _retained_events(path=path, config=config, now=current)
        events.append(NotificationEvent(action=action, detail=detail, occurred_at=current))
        _persist_notification_outbox_unlocked(path, events[-config.offline_max_events :])


def _default_sendmail(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SYSTEM_SENDMAIL_PATH, "-t"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=SENDMAIL_TIMEOUT_SECONDS,
    )


def _message(*, recipient: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return message.as_string()


def _text(config: NotificationsConfig, key: str, **values: object) -> str:
    return translation_for(config.locale).gettext(key).format(**values)


def send_test_notification(
    *,
    config: NotificationsConfig,
    runner: SendmailRunner = _default_sendmail,
) -> tuple[bool, str]:
    if not config.enabled:
        return False, "Notifications are disabled"
    if not config.recipient.strip():
        return False, "Notification recipient is not configured"
    if not is_valid_notification_recipient(config.recipient):
        return False, "Notification recipient is invalid"
    try:
        payload = _message(
            recipient=config.recipient,
            subject=_text(
                config,
                "[BMGateway] notification test: {hostname}",
                hostname=socket.gethostname(),
            ),
            body=_text(config, "BMGateway system-mail notification delivery is working.") + "\n",
        )
        completed = runner(payload)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    if completed.returncode == 0:
        return True, "Test email sent"
    return False, completed.stderr.strip() or completed.stdout.strip() or "sendmail failed"


def _deliver_notification_outbox_unlocked(
    *,
    path: Path,
    config: NotificationsConfig,
    runner: SendmailRunner = _default_sendmail,
    now: datetime | None = None,
) -> tuple[bool, str]:
    try:
        events = _retained_events(path=path, config=config, now=now or datetime.now(timezone.utc))
    except NotificationOutboxError as error:
        return False, str(error)
    if not events:
        return True, "No pending notifications"
    if not config.enabled or not config.recipient.strip():
        return False, "Notification delivery is not configured"
    if not is_valid_notification_recipient(config.recipient):
        return False, "Notification recipient is invalid"
    if config.offline_delivery == "drop":
        try:
            _remove_notification_outbox(path)
        except NotificationOutboxError as error:
            return False, str(error)
        return True, "Pending notifications dropped"
    if config.offline_delivery == "summary":
        body = "\n".join(
            [
                _text(
                    config,
                    "BMGateway recovered notification delivery on {hostname}.",
                    hostname=socket.gethostname(),
                ),
                "",
                _text(config, "Events retained: {count}", count=len(events)),
                _text(
                    config, "First event: {timestamp}", timestamp=events[0].occurred_at.isoformat()
                ),
                _text(
                    config, "Last event: {timestamp}", timestamp=events[-1].occurred_at.isoformat()
                ),
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
                    subject=_text(config, "[BMGateway] notification summary"),
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
                    subject=_text(
                        config, "[BMGateway] notification: {action}", action=event.action
                    ),
                    body="\n".join(
                        [
                            _text(
                                config,
                                "Occurred at: {timestamp}",
                                timestamp=event.occurred_at.isoformat(),
                            ),
                            _text(config, "Event: {action}", action=event.action),
                            _text(config, "Detail: {detail}", detail=event.detail),
                            "",
                        ]
                    ),
                )
                completed = runner(payload)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                return False, str(error)
            if completed.returncode != 0:
                return (
                    False,
                    completed.stderr.strip() or completed.stdout.strip() or "sendmail failed",
                )
            remaining = events[index + 1 :]
            try:
                if remaining:
                    _persist_notification_outbox_unlocked(path, remaining)
                else:
                    _remove_notification_outbox(path)
            except NotificationOutboxError as error:
                return False, str(error)
        return True, "Pending notifications delivered"
    for payload in payloads:
        try:
            completed = runner(payload)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            return False, str(error)
        if completed.returncode != 0:
            return False, completed.stderr.strip() or completed.stdout.strip() or "sendmail failed"
    try:
        _remove_notification_outbox(path)
    except NotificationOutboxError as error:
        return False, str(error)
    return True, "Pending notifications delivered"


def deliver_notification_outbox(
    *,
    path: Path,
    config: NotificationsConfig,
    runner: SendmailRunner = _default_sendmail,
    now: datetime | None = None,
) -> tuple[bool, str]:
    try:
        with _notification_outbox_lock(path):
            return _deliver_notification_outbox_unlocked(
                path=path,
                config=config,
                runner=runner,
                now=now,
            )
    except NotificationOutboxError as error:
        return False, str(error)
