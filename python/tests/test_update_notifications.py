from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from email import policy
from email.parser import Parser
from pathlib import Path

import pytest
from bm_gateway import notifications, update_notifications
from bm_gateway.config import AppConfig, NotificationsConfig, load_config
from bm_gateway.localization import supported_locale_codes, translation_for


def _config() -> AppConfig:
    config = load_config(Path("python/config/config.toml.example"))
    return replace(
        config,
        notifications=NotificationsConfig(
            enabled=True,
            recipient="operator@example.test",
            locale="en",
            offline_delivery="individual",
        ),
    )


def test_completed_update_is_durable_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    monkeypatch.setattr(update_notifications, "lifecycle_wall_clock_is_synchronized", lambda: True)
    monkeypatch.setattr(
        update_notifications, "deliver_notification_outbox", lambda **_kwargs: (False, "offline")
    )

    result = update_notifications.record_update_notification(
        config=config,
        state_dir=tmp_path,
        previous_revision="a" * 40,
        current_revision="b" * 40,
        reboot_required=True,
    )
    duplicate = update_notifications.record_update_notification(
        config=config,
        state_dir=tmp_path,
        previous_revision="a" * 40,
        current_revision="b" * 40,
        reboot_required=True,
    )

    assert result.queued is True
    assert result.delivered is False
    assert duplicate.queued is False
    events = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    event = events[0]
    assert event.action == "software_update_completed"
    assert event.update_outcome == "completed"
    assert event.update_from_revision == "a" * 40
    assert event.update_to_revision == "b" * 40
    assert event.update_reboot_required is True


@pytest.mark.parametrize("locale", supported_locale_codes())
@pytest.mark.parametrize("reboot_required", [False, True])
def test_completed_update_uses_the_delivery_locale(
    tmp_path: Path, locale: str, reboot_required: bool
) -> None:
    config = _config()
    config = replace(config, notifications=replace(config.notifications, locale=locale))
    path = notifications.notification_outbox_path(tmp_path)
    notifications.queue_notification_event_once(
        path=path,
        config=config.notifications,
        action="software_update_completed",
        detail="",
        idempotency_key="update",
        update_outcome="completed",
        update_from_revision="a" * 40,
        update_to_revision="b" * 40,
        update_reboot_required=reboot_required,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    sent: list[str] = []

    def send(payload: str) -> subprocess.CompletedProcess[str]:
        sent.append(payload)
        return subprocess.CompletedProcess(["sendmail"], 0, "", "")

    delivered, _detail = notifications.deliver_notification_outbox(
        path=path, config=config.notifications, runner=send
    )
    assert delivered
    message = Parser(policy=policy.default).parsestr(sent[0])
    text = translation_for(locale).gettext
    template = (
        "BMGateway updated from {previous_revision} to {current_revision}. A reboot is required."
        if reboot_required
        else (
            "BMGateway updated from {previous_revision} to {current_revision}. "
            "No reboot is required."
        )
    )
    assert text("Software update completed") in str(message["Subject"])
    expected_detail = text(template).format(previous_revision="a" * 40, current_revision="b" * 40)
    assert expected_detail in message.get_content()


def test_failed_update_is_queued_without_a_reboot_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    monkeypatch.setattr(update_notifications, "lifecycle_wall_clock_is_synchronized", lambda: False)
    monkeypatch.setattr(
        update_notifications,
        "deliver_notification_outbox",
        lambda **kwargs: pytest.fail(f"delivery called with {kwargs}"),
    )

    result = update_notifications.record_update_notification(
        config=config,
        state_dir=tmp_path,
        previous_revision="a" * 40,
        failure_stage="install",
    )

    assert result.queued is True
    events = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    event = events[0]
    assert event.action == "software_update_failed"
    assert event.update_outcome == "failed"
    assert event.update_stage == "install"
    assert event.update_to_revision is None
    assert event.update_reboot_required is None
    assert event.occurred_at is None


@pytest.mark.parametrize(
    ("current_revision", "reboot_required", "failure_stage"),
    [
        ("a" * 40, False, None),
        (None, None, None),
        (None, False, "install"),
        (None, None, "invalid"),
    ],
)
def test_update_notification_rejects_ambiguous_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    current_revision: str | None,
    reboot_required: bool | None,
    failure_stage: str | None,
) -> None:
    monkeypatch.setattr(update_notifications, "lifecycle_wall_clock_is_synchronized", lambda: True)
    with pytest.raises(ValueError):
        update_notifications.record_update_notification(
            config=_config(),
            state_dir=tmp_path,
            previous_revision="a" * 40,
            current_revision=current_revision,
            reboot_required=reboot_required,
            failure_stage=failure_stage,
        )
