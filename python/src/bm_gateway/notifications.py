"""Bounded system-mail notifications and offline incident delivery."""

from __future__ import annotations

import fcntl
import json
import os
import re
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Iterator

from .config import NotificationsConfig, is_valid_notification_recipient
from .localization import supported_locale_codes, translation_for

SendmailRunner = Callable[[str], subprocess.CompletedProcess[str]]
SYSTEM_SENDMAIL_PATH = "/usr/sbin/sendmail"
OFFLINE_DELIVERY_MODES = ("summary", "individual", "drop")
SENDMAIL_TIMEOUT_SECONDS = 30
_USB_ESCALATION_ACTION = "usb_otg_recovery_exhausted"
_USB_ESCALATION_TEMPLATE = (
    "USB OTG frame enumeration remained unavailable after {attempts} reboot attempt(s): {reason}"
)
_LEGACY_USB_HEALTH_REASONS = (
    "USB OTG backing image is missing",
    "USB OTG gadget is not configured",
    "USB OTG gadget status is unreadable",
    "USB OTG gadget is detached",
    "USB OTG controller state is unreadable",
    "UDC state is not configured",
)
_MISSING = object()
_WIFI_TEMPLATES = {
    (
        "wifi_reconnect_attempted",
        "completed",
    ): "Wi-Fi reconnect succeeded after {outage_seconds} seconds on {wifi_interface}.",
    (
        "wifi_reconnect_attempted",
        "failed",
    ): "Wi-Fi reconnect failed after {outage_seconds} seconds on {wifi_interface}.",
    (
        "wifi_reboot_requested",
        "completed",
    ): "Wi-Fi reboot requested after {outage_seconds} seconds on {wifi_interface}.",
    (
        "wifi_connectivity_restored",
        "completed",
    ): "Wi-Fi connectivity restored after {outage_seconds} seconds.",
}


class NotificationOutboxError(RuntimeError):
    """The pending-notification state cannot be safely read or written."""


@dataclass(frozen=True)
class NotificationEvent:
    action: str
    detail: str
    occurred_at: datetime
    idempotency_key: str = ""
    usb_otg_reason: str | None = None
    usb_otg_reboot_attempts: int | None = None
    wifi_outcome: str | None = None
    wifi_interface: str | None = None
    wifi_outage_seconds: int | None = None

    def to_dict(self) -> dict[str, str | int]:
        event = _canonical_event(
            action=self.action,
            detail=self.detail,
            occurred_at=self.occurred_at,
            idempotency_key=self.idempotency_key,
            usb_otg_reason=self.usb_otg_reason if self.usb_otg_reason is not None else _MISSING,
            usb_otg_reboot_attempts=(
                self.usb_otg_reboot_attempts
                if self.usb_otg_reboot_attempts is not None
                else _MISSING
            ),
            wifi_outcome=self.wifi_outcome if self.wifi_outcome is not None else _MISSING,
            wifi_interface=self.wifi_interface if self.wifi_interface is not None else _MISSING,
            wifi_outage_seconds=(
                self.wifi_outage_seconds if self.wifi_outage_seconds is not None else _MISSING
            ),
        )
        payload: dict[str, str | int] = {
            "action": event.action,
            "detail": event.detail,
            "occurred_at": event.occurred_at.isoformat(),
        }
        if event.idempotency_key:
            payload["idempotency_key"] = event.idempotency_key
        if event.usb_otg_reason is not None and event.usb_otg_reboot_attempts is not None:
            payload["usb_otg_reason"] = event.usb_otg_reason
            payload["usb_otg_reboot_attempts"] = event.usb_otg_reboot_attempts
        if event.wifi_outcome is not None:
            assert event.wifi_interface is not None and event.wifi_outage_seconds is not None
            payload["wifi_outcome"] = event.wifi_outcome
            payload["wifi_interface"] = event.wifi_interface
            payload["wifi_outage_seconds"] = event.wifi_outage_seconds
        return payload


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


def _canonical_event(
    *,
    action: object,
    detail: object,
    occurred_at: datetime,
    idempotency_key: object = "",
    usb_otg_reason: object = _MISSING,
    usb_otg_reboot_attempts: object = _MISSING,
    wifi_outcome: object = _MISSING,
    wifi_interface: object = _MISSING,
    wifi_outage_seconds: object = _MISSING,
) -> NotificationEvent:
    normalized_action = str(action).strip()
    if not normalized_action:
        raise NotificationOutboxError("Notification outbox contains an event without an action")
    normalized_detail = str(detail).strip()
    reason: str | None = None
    attempts: int | None = None
    if usb_otg_reason is not _MISSING or usb_otg_reboot_attempts is not _MISSING:
        if (
            normalized_action != _USB_ESCALATION_ACTION
            or not isinstance(usb_otg_reason, str)
            or not isinstance(usb_otg_reboot_attempts, int)
            or isinstance(usb_otg_reboot_attempts, bool)
            or usb_otg_reboot_attempts < 0
        ):
            raise NotificationOutboxError("Notification outbox contains an invalid event")
        reason, attempts = usb_otg_reason, usb_otg_reboot_attempts
    elif normalized_action == _USB_ESCALATION_ACTION:
        legacy = _legacy_usb_detail(normalized_detail)
        if legacy is not None:
            reason, attempts = legacy
    if reason is not None and attempts is not None:
        normalized_detail = _USB_ESCALATION_TEMPLATE.format(attempts=attempts, reason=reason)
    wifi: tuple[str, str, int] | None = None
    if any(value is not _MISSING for value in (wifi_outcome, wifi_interface, wifi_outage_seconds)):
        if (
            not isinstance(wifi_outcome, str)
            or (normalized_action, wifi_outcome) not in _WIFI_TEMPLATES
            or not isinstance(wifi_interface, str)
            or not isinstance(wifi_outage_seconds, int)
            or isinstance(wifi_outage_seconds, bool)
            or wifi_outage_seconds < 0
        ):
            raise NotificationOutboxError("Notification outbox contains an invalid event")
        wifi = wifi_outcome, wifi_interface, wifi_outage_seconds
    else:
        wifi = _legacy_wifi_detail(normalized_action, normalized_detail)
    if wifi is not None:
        normalized_detail = _WIFI_TEMPLATES[(normalized_action, wifi[0])].format(
            wifi_interface=wifi[1], outage_seconds=wifi[2]
        )
    return NotificationEvent(
        action=normalized_action,
        detail=normalized_detail,
        occurred_at=_aware_utc(occurred_at),
        idempotency_key=str(idempotency_key).strip(),
        usb_otg_reason=reason,
        usb_otg_reboot_attempts=attempts,
        wifi_outcome=wifi[0] if wifi else None,
        wifi_interface=wifi[1] if wifi else None,
        wifi_outage_seconds=wifi[2] if wifi else None,
    )


def _legacy_wifi_detail(action: str, detail: str) -> tuple[str, str, int] | None:
    matches: set[tuple[str, str, int]] = set()
    for (candidate, outcome), template in _WIFI_TEMPLATES.items():
        if candidate != action:
            continue
        for locale in supported_locale_codes():
            pattern = (
                re.escape(translation_for(locale).gettext(template))
                .replace(re.escape("{outage_seconds}"), r"(?P<seconds>0|[1-9][0-9]*)")
                .replace(re.escape("{wifi_interface}"), r"(?P<interface>[A-Za-z0-9_.-]{1,15})")
            )
            match = re.fullmatch(pattern, detail)
            if match is not None:
                try:
                    seconds = int(match["seconds"])
                except ValueError:
                    continue
                matches.add((outcome, match.groupdict().get("interface", ""), seconds))
    return next(iter(matches)) if len(matches) == 1 else None


def _legacy_usb_detail(detail: str) -> tuple[str, int] | None:
    """Recognize only complete shipped templates with an unambiguous known reason."""
    matches: set[tuple[str, int]] = set()
    for locale in supported_locale_codes():
        text = translation_for(locale).gettext
        pattern = (
            re.escape(text(_USB_ESCALATION_TEMPLATE))
            .replace(re.escape("{attempts}"), r"(?P<attempts>0|[1-9][0-9]*)")
            .replace(re.escape("{reason}"), r"(?P<reason>.+)")
        )
        match = re.fullmatch(pattern, detail)
        if match is None:
            continue
        try:
            attempts = int(match["attempts"])
        except ValueError:
            # Python bounds oversized decimal conversion; preserve opaque legacy text.
            continue
        for reason in _LEGACY_USB_HEALTH_REASONS:
            if match["reason"] in {reason, text(reason)}:
                matches.add((reason, attempts))
    return next(iter(matches)) if len(matches) == 1 else None


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
                idempotency_key=item.get("idempotency_key", ""),
                usb_otg_reason=item.get("usb_otg_reason", _MISSING),
                usb_otg_reboot_attempts=item.get("usb_otg_reboot_attempts", _MISSING),
                wifi_outcome=item.get("wifi_outcome", _MISSING),
                wifi_interface=item.get("wifi_interface", _MISSING),
                wifi_outage_seconds=item.get("wifi_outage_seconds", _MISSING),
            )
        )
    return events


def load_notification_outbox(path: Path) -> list[NotificationEvent]:
    with _notification_outbox_lock(path):
        return _load_notification_outbox_unlocked(path)


def _persist_notification_outbox_unlocked(path: Path, events: list[NotificationEvent]) -> None:
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


def _canonicalize_outbox(
    *,
    events: list[NotificationEvent],
    config: NotificationsConfig,
    retention_reference: datetime,
) -> list[NotificationEvent]:
    reference = _aware_utc(retention_reference)
    cutoff = reference - timedelta(days=config.offline_retention_days)
    retained = [
        replace(event, occurred_at=min(event.occurred_at, reference))
        for event in events
        if event.occurred_at >= cutoff
    ]
    retained.sort(key=lambda event: event.occurred_at)
    return retained[-config.offline_max_events :]


def _retained_events(
    *, path: Path, config: NotificationsConfig, retention_reference: datetime
) -> list[NotificationEvent]:
    events = _load_notification_outbox_unlocked(path)
    retained = _canonicalize_outbox(
        events=events,
        config=config,
        retention_reference=retention_reference,
    )
    if retained != events:
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
    idempotency_key: str = "",
    usb_otg_reason: str | None = None,
    usb_otg_reboot_attempts: int | None = None,
    wifi_outcome: str | None = None,
    wifi_interface: str | None = None,
    wifi_outage_seconds: int | None = None,
    now: datetime | None = None,
    retention_now: datetime | None = None,
) -> None:
    if not config.enabled or config.offline_delivery == "drop":
        return
    with _notification_outbox_lock(path):
        current = datetime.now(timezone.utc)
        occurred_at = _aware_utc(now or current)
        retention_reference = _aware_utc(retention_now or current)
        events = _retained_events(
            path=path,
            config=config,
            retention_reference=retention_reference,
        )
        event = NotificationEvent(
            action=action,
            detail=detail,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            usb_otg_reason=usb_otg_reason,
            usb_otg_reboot_attempts=usb_otg_reboot_attempts,
            wifi_outcome=wifi_outcome,
            wifi_interface=wifi_interface,
            wifi_outage_seconds=wifi_outage_seconds,
        )
        event.to_dict()
        events.append(event)
        retained = _canonicalize_outbox(
            events=events,
            config=config,
            retention_reference=retention_reference,
        )
        if retained:
            _persist_notification_outbox_unlocked(path, retained)
        else:
            _remove_notification_outbox(path)


def queue_notification_event_once(
    *,
    path: Path,
    config: NotificationsConfig,
    action: str,
    detail: str,
    idempotency_key: str,
    usb_otg_reason: str | None = None,
    usb_otg_reboot_attempts: int | None = None,
    wifi_outcome: str | None = None,
    wifi_interface: str | None = None,
    wifi_outage_seconds: int | None = None,
    now: datetime | None = None,
    retention_now: datetime | None = None,
) -> bool:
    """Durably queue an event unless its stable identity is already pending."""
    if not config.enabled or config.offline_delivery == "drop":
        return False
    with _notification_outbox_lock(path):
        current = datetime.now(timezone.utc)
        occurred_at = _aware_utc(now or current)
        retention_reference = _aware_utc(retention_now or current)
        events = _retained_events(
            path=path,
            config=config,
            retention_reference=retention_reference,
        )
        if any(event.idempotency_key == idempotency_key for event in events):
            # A visible earlier replacement may still lack directory durability.
            _persist_notification_outbox_unlocked(path, events)
            return False
        event = NotificationEvent(
            action=action,
            detail=detail,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            usb_otg_reason=usb_otg_reason,
            usb_otg_reboot_attempts=usb_otg_reboot_attempts,
            wifi_outcome=wifi_outcome,
            wifi_interface=wifi_interface,
            wifi_outage_seconds=wifi_outage_seconds,
        )
        event.to_dict()
        events.append(event)
        retained = _canonicalize_outbox(
            events=events,
            config=config,
            retention_reference=retention_reference,
        )
        if retained:
            _persist_notification_outbox_unlocked(path, retained)
        else:
            _remove_notification_outbox(path)
        return True


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


def _action_label(config: NotificationsConfig, action: str) -> str:
    if action == "system_boot":
        return _text(config, "System started")
    if action == "system_shutdown":
        return _text(config, "System shutting down")
    if action == "usb_otg_recovery_exhausted":
        return _text(config, "USB OTG recovery exhausted")
    if action == "wifi_reconnect_attempted":
        return _text(config, "Wi-Fi reconnect attempted")
    if action == "wifi_reboot_requested":
        return _text(config, "Wi-Fi reboot requested")
    if action == "wifi_connectivity_restored":
        return _text(config, "Wi-Fi connectivity restored")
    return action


def _event_detail(config: NotificationsConfig, event: NotificationEvent) -> str:
    if event.action == "system_boot":
        return _text(config, "A system boot was observed. This is not an application restart.")
    if event.action == "system_shutdown":
        return _text(config, "The system is shutting down or rebooting.")
    if event.wifi_outcome is not None:
        return _text(
            config,
            _WIFI_TEMPLATES[(event.action, event.wifi_outcome)],
            wifi_interface=event.wifi_interface,
            outage_seconds=event.wifi_outage_seconds,
        )
    if event.usb_otg_reason is None or event.usb_otg_reboot_attempts is None:
        return event.detail
    reason = translation_for(config.locale).gettext(event.usb_otg_reason)
    return _text(
        config, _USB_ESCALATION_TEMPLATE, attempts=event.usb_otg_reboot_attempts, reason=reason
    )


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
        events = _retained_events(
            path=path,
            config=config,
            retention_reference=now or datetime.now(timezone.utc),
        )
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
                    "BMGateway notification summary on {hostname}.",
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
                    f"- {event.occurred_at.isoformat()} "
                    f"{_action_label(config, event.action)}: {_event_detail(config, event)}"
                    for event in events
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
                        config,
                        "[BMGateway] notification: {action}",
                        action=_action_label(config, event.action),
                    ),
                    body="\n".join(
                        [
                            _text(
                                config,
                                "Occurred at: {timestamp}",
                                timestamp=event.occurred_at.isoformat(),
                            ),
                            _text(
                                config,
                                "Event: {action}",
                                action=_action_label(config, event.action),
                            ),
                            _text(config, "Detail: {detail}", detail=_event_detail(config, event)),
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
