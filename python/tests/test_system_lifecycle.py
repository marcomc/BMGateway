from __future__ import annotations

import fcntl
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from email import message_from_string
from functools import partial
from pathlib import Path

import pytest
from bm_gateway import notifications, self_healing, self_healing_runtime
from bm_gateway import system_lifecycle as lifecycle
from bm_gateway.cli import main
from bm_gateway.config import AppConfig, load_config
from bm_gateway.localization import supported_locale_codes, translation_for


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    config = load_config(Path("python/config/config.toml.example"))
    monkeypatch.setattr(lifecycle, "default_reboot_boot_id", lambda: "a" * 32)
    return replace(
        config,
        notifications=replace(
            config.notifications, enabled=True, recipient="user@example.com", locale="en"
        ),
    )


def test_repeated_boot_does_not_requeue_after_delivery(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    def deliver(**kwargs: object) -> tuple[bool, str]:
        outbox = notifications.notification_outbox_path(tmp_path)
        if outbox.exists():
            sent.append(outbox.read_text())
            outbox.unlink()
        return True, "ok"

    monkeypatch.setattr(lifecycle, "deliver_notification_outbox", deliver)
    for _ in range(3):
        lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    assert len(sent) == 1
    assert "system_boot" in sent[0]


@pytest.mark.parametrize("stopping", [False, True])
def test_shutdown_guard(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopping: bool
) -> None:
    monkeypatch.setattr(lifecycle, "shutdown_in_progress", lambda: stopping)
    monkeypatch.setattr(lifecycle, "deliver_notification_outbox", lambda **_: (True, "ok"))
    lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="shutdown")
    assert notifications.notification_outbox_path(tmp_path).exists() == stopping


def test_pending_previous_boot_survives_failed_queue_and_new_boot(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = notifications.queue_notification_event_once

    def fail_queue(**kwargs: object) -> bool:
        raise notifications.NotificationOutboxError("queue failed")

    monkeypatch.setattr(lifecycle, "queue_notification_event_once", fail_queue)
    with pytest.raises(notifications.NotificationOutboxError):
        lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    monkeypatch.setattr(lifecycle, "default_reboot_boot_id", lambda: "b" * 32)
    monkeypatch.setattr(lifecycle, "queue_notification_event_once", queue)
    monkeypatch.setattr(lifecycle, "deliver_notification_outbox", lambda **_: (True, "ok"))
    lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    events = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert len(events) == 2
    assert len({e.idempotency_key for e in events}) == 2
    data = json.loads((tmp_path / "runtime/system_lifecycle_state.json").read_text())
    assert data["pending"] == []


@pytest.mark.parametrize("after_replace", [False, True])
def test_runtime_completes_failed_lifecycle_ack_before_delivery(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_replace: bool
) -> None:
    save = lifecycle._save
    failed = False

    def fail_ack(path: Path, data: dict[str, object]) -> None:
        nonlocal failed
        if not data["pending"] and not failed:
            failed = True
            if after_replace:
                save(path, data)
            raise notifications.NotificationOutboxError("ACK failed")
        save(path, data)

    monkeypatch.setattr(lifecycle, "_save", fail_ack)
    with pytest.raises(notifications.NotificationOutboxError):
        lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    delivered: list[int] = []

    def deliver(**kwargs: object) -> tuple[bool, str]:
        data = json.loads((tmp_path / "runtime/system_lifecycle_state.json").read_text())
        assert not data["pending"]
        usb_path = self_healing.usb_otg_watchdog_state_path(tmp_path)
        with (usb_path.parent / f".{usb_path.name}.lock").open("a+") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        outbox = notifications.notification_outbox_path(tmp_path)
        events = notifications.load_notification_outbox(outbox)
        delivered.append(len(events))
        if outbox.exists():
            outbox.unlink()
        return True, "No pending notifications"

    monkeypatch.setattr(self_healing_runtime, "deliver_notification_outbox", deliver)
    monkeypatch.setattr(lifecycle, "deliver_notification_outbox", deliver)
    self_healing_runtime.run_self_healing(
        config=config, state=self_healing.new_self_healing_state(), state_dir=tmp_path
    )
    lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    assert delivered == [1, 0]


@pytest.mark.parametrize("condition", ["usb_corrupt", "usb_pending", "wifi_pending"])
def test_lifecycle_does_not_deliver_unacknowledged_watchdog_events(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    state = self_healing.new_self_healing_state()
    usb_path = self_healing.usb_otg_watchdog_state_path(tmp_path)
    if condition == "usb_corrupt":
        usb_path.parent.mkdir(parents=True)
        usb_path.write_text("corrupt")
    elif condition == "usb_pending":
        state.usb_otg_escalation_notification_pending = True
        state.usb_otg_escalation_id = "pending"
        self_healing.persist_usb_otg_watchdog_state(usb_path, state)
    else:
        state.wifi_recovery_pending = True
        state.wifi_recovery_interface = "wlan0"
        self_healing.persist_wifi_watchdog_state(
            self_healing.wifi_watchdog_state_path(tmp_path), state
        )
    monkeypatch.setattr(
        lifecycle, "deliver_notification_outbox", lambda **_: pytest.fail("unsafe delivery")
    )
    lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    assert notifications.notification_outbox_path(tmp_path).exists()


@pytest.mark.parametrize("enabled,policy", [(False, "summary"), (True, "drop")])
def test_disabled_policy_does_not_queue(
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    policy: str,
) -> None:
    config = replace(
        config,
        notifications=replace(config.notifications, enabled=enabled, offline_delivery=policy),
    )
    lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    assert not notifications.notification_outbox_path(tmp_path).exists()


def test_corrupt_lifecycle_state_does_not_disable_wifi_reconnect(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_watchdog_enabled=True,
            wifi_reconnect_enabled=True,
            wifi_reconnect_after_minutes=1,
        ),
    )
    directory = tmp_path / "runtime"
    directory.mkdir()
    (directory / "system_lifecycle_state.json").write_text("corrupt")
    state = self_healing.new_self_healing_state(now_monotonic=0)
    state.wifi_outage_started_monotonic = 0
    reconnects: list[str] = []

    def reconnect(interface: str) -> bool:
        reconnects.append(interface)
        return True

    monkeypatch.setattr(
        self_healing_runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            now_monotonic=120,
            connectivity_checker=lambda *_: False,
            reconnect_action=reconnect,
        ),
    )
    monkeypatch.setattr(
        self_healing_runtime, "deliver_notification_outbox", lambda **_: pytest.fail("delivery")
    )
    events = self_healing_runtime.run_self_healing(config=config, state=state, state_dir=tmp_path)
    assert reconnects
    assert "lifecycle_notification_handoff_failed" in [event.action for event in events]


@pytest.mark.parametrize("stage", ["registration", "ack"])
@pytest.mark.parametrize("after_replace", [False, True])
def test_real_lifecycle_checkpoint_failure_retries_without_duplicate(
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    after_replace: bool,
) -> None:
    real_replace = os.replace
    real_fsync = os.fsync
    armed = False
    failed = False

    def replace_file(source: str, destination: Path) -> None:
        nonlocal armed, failed
        if destination.name == "system_lifecycle_state.json":
            pending = bool(json.loads(Path(source).read_text())["pending"])
            if not failed and pending == (stage == "registration"):
                if not after_replace:
                    failed = True
                    raise OSError("replace failure")
                armed = True
        real_replace(source, destination)

    def fsync(descriptor: int) -> None:
        nonlocal armed, failed
        if armed:
            armed = False
            failed = True
            raise OSError("directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(lifecycle, "deliver_notification_outbox", lambda **_: (True, "ok"))
    with monkeypatch.context() as failure:
        failure.setattr(os, "replace", replace_file)
        failure.setattr(os, "fsync", fsync)
        with pytest.raises(notifications.NotificationOutboxError):
            lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    assert failed
    lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    events = notifications.load_notification_outbox(
        notifications.notification_outbox_path(tmp_path)
    )
    assert len(events) == 1


def test_many_offline_boots_bound_pending_intents_and_preserve_current_receipt(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(config, notifications=replace(config.notifications, offline_max_events=2))

    def fail_queue(**kwargs: object) -> bool:
        raise notifications.NotificationOutboxError("offline storage")

    monkeypatch.setattr(lifecycle, "queue_notification_event_once", fail_queue)
    for number in range(10):
        monkeypatch.setattr(lifecycle, "default_reboot_boot_id", lambda n=number: f"{n:032x}")
        with pytest.raises(notifications.NotificationOutboxError):
            lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    path = tmp_path / "runtime/system_lifecycle_state.json"
    before = path.read_text()
    with pytest.raises(notifications.NotificationOutboxError):
        lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")
    assert path.read_text() == before
    assert len(json.loads(before)["pending"]) == 2


def test_cleanup_failure_preserves_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_dump(*args: object, **kwargs: object) -> None:
        raise OSError("primary write failure")

    def fail_cleanup(*args: object, **kwargs: object) -> None:
        raise OSError("cleanup failure")

    monkeypatch.setattr(json, "dump", fail_dump)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(notifications.NotificationOutboxError) as raised:
        lifecycle._save(tmp_path / "state.json", {})
    assert str(raised.value.__cause__) == "primary write failure"


@pytest.mark.parametrize("locale", supported_locale_codes())
def test_lifecycle_cli_errors_use_configured_locale(
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    locale: str,
) -> None:
    from bm_gateway import cli

    config = replace(config, notifications=replace(config.notifications, locale=locale))
    monkeypatch.setattr(cli, "load_config", lambda _: config)

    def fail(**kwargs: object) -> None:
        raise notifications.NotificationOutboxError("Cannot load lifecycle notification state")

    monkeypatch.setattr(lifecycle, "notify_system_lifecycle", fail)
    assert main(["lifecycle", "boot", "--state-dir", str(tmp_path)]) == 1
    assert capsys.readouterr().err.strip() == translation_for(locale).gettext(
        "Cannot load lifecycle notification state"
    )


@pytest.mark.parametrize("event", ["boot", "shutdown"])
@pytest.mark.parametrize("locale", supported_locale_codes())
def test_lifecycle_cli_rejects_invalid_config_before_mutation(
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    event: str,
    locale: str,
) -> None:
    from bm_gateway import cli

    config = replace(
        config,
        notifications=replace(config.notifications, locale=locale, offline_max_events=0),
    )
    monkeypatch.setattr(cli, "load_config", lambda _: config)
    monkeypatch.setattr(
        lifecycle,
        "notify_system_lifecycle",
        lambda **_: pytest.fail("lifecycle state mutated for invalid config"),
    )

    assert main(["lifecycle", event, "--state-dir", str(tmp_path)]) == 1
    assert capsys.readouterr().err.strip() == translation_for(locale).gettext(
        "notifications.offline_max_events must be between 1 and 1000"
    )
    assert not (tmp_path / "runtime").exists()


def test_generated_shutdown_unit_is_armed_independently_of_boot_delivery() -> None:
    source = Path("rpi-setup/scripts/install-service.sh").read_text()
    shutdown = source.split("cat > /etc/systemd/system/bm-gateway-lifecycle.service <<EOF", 1)[
        1
    ].split("\nEOF", 1)[0]
    boot = source.split("cat > /etc/systemd/system/bm-gateway-boot-notification.service <<EOF", 1)[
        1
    ].split("\nEOF", 1)[0]
    assert "ExecStart=/usr/bin/true" in shutdown
    assert "RemainAfterExit=yes" in shutdown
    assert " lifecycle shutdown " in shutdown
    assert " lifecycle boot " not in shutdown
    assert "Requires=systemd-time-wait-sync.service" not in shutdown
    assert "systemd-time-wait-sync.service" not in shutdown
    assert "Before=bm-gateway.service" in shutdown
    assert "Requires=systemd-time-wait-sync.service" in boot
    assert "After=network-online.target systemd-time-wait-sync.service" in boot
    assert "time-sync.target" not in boot
    assert "Before=bm-gateway.service" not in boot
    assert "systemctl enable systemd-time-wait-sync.service" not in source
    assert "Restart=on-failure" in boot
    assert "StartLimitIntervalSec=300" in boot
    assert "StartLimitBurst=3" in boot
    assert " lifecycle boot " in boot


def test_operator_docs_cover_lifecycle_units_and_validation() -> None:
    lifecycle_unit = "bm-gateway-lifecycle.service"
    boot_unit = "bm-gateway-boot-notification.service"
    documents = {
        path: Path(path).read_text()
        for path in (
            "rpi-setup/README.md",
            "rpi-setup/macos-imager-cli.md",
            "rpi-setup/manual-setup.md",
        )
    }

    manual_setup = documents["rpi-setup/manual-setup.md"]
    normalized_manual_setup = " ".join(manual_setup.split())
    assert (
        "Boot recording waits for synchronized wall-clock time without delaying "
        "runtime or web activation."
    ) in normalized_manual_setup
    for unit in (lifecycle_unit, boot_unit):
        assert f"- `/etc/systemd/system/{unit}`" in manual_setup
        assert f"sudo systemctl status {unit}" in manual_setup

    rpi_readme = documents["rpi-setup/README.md"]
    for unit in (lifecycle_unit, boot_unit):
        assert f"- `/etc/systemd/system/{unit}`" in rpi_readme
        assert f'"{unit}<br/>' in rpi_readme
    assert f"- `{lifecycle_unit}` for shutdown notifications" in rpi_readme
    assert f"- `{boot_unit}` for boot notifications" in rpi_readme

    macos_setup = documents["rpi-setup/macos-imager-cli.md"]
    assert f"- installs and enables `{lifecycle_unit}`" in macos_setup
    assert f"- installs and enables `{boot_unit}`" in macos_setup

    for path in ("rpi-setup/macos-imager-cli.md", "rpi-setup/manual-setup.md"):
        document = documents[path]
        assert f"systemctl is-enabled {lifecycle_unit} {boot_unit}" in document
        assert (
            f"systemctl is-active bm-gateway.service bm-gateway-web.service {lifecycle_unit}"
            in document
        )
        assert f"--value {boot_unit}" in document
        assert "--property=Result" in document
        assert "--property=ExecMainStatus" in document


@pytest.mark.parametrize("locale", supported_locale_codes())
def test_lifecycle_mail_renders_in_delivery_locale(
    config: AppConfig, tmp_path: Path, locale: str
) -> None:
    outbox = notifications.notification_outbox_path(tmp_path)
    for action in ["system_boot", "system_shutdown"]:
        notifications.queue_notification_event_once(
            path=outbox,
            config=config.notifications,
            action=action,
            detail="",
            idempotency_key=action,
        )
    rendered: list[str] = []

    def sendmail(payload: str) -> subprocess.CompletedProcess[str]:
        body = message_from_string(payload).get_payload(decode=True)
        assert isinstance(body, bytes)
        rendered.append(body.decode())
        return subprocess.CompletedProcess(["sendmail"], 0, "", "")

    assert notifications.deliver_notification_outbox(
        path=outbox, config=replace(config.notifications, locale=locale), runner=sendmail
    )[0]
    text = translation_for(locale).gettext
    assert text("System started") in rendered[0]
    assert text("The system is shutting down or rebooting.") in rendered[0]


def test_expired_intents_are_pruned_but_current_boot_receipts_survive(
    config: AppConfig, tmp_path: Path
) -> None:
    path = tmp_path / "runtime/system_lifecycle_state.json"
    lifecycle._save(
        path,
        {
            "boot_id": "a" * 32,
            "recorded": ["boot"],
            "pending": [
                {
                    "boot_id": "a" * 32,
                    "action": "boot",
                    "occurred_at": "2000-01-01T00:00:00+00:00",
                }
            ],
        },
    )
    with self_healing.usb_otg_watchdog_transaction(
        self_healing.usb_otg_watchdog_state_path(tmp_path), self_healing.new_self_healing_state()
    ):
        lifecycle.transfer_lifecycle_notifications(config=config, state_dir=tmp_path)
    data = json.loads(path.read_text())
    assert data["recorded"] == ["boot"] and not data["pending"]
    assert not notifications.notification_outbox_path(tmp_path).exists()


def test_failed_reload_durability_does_not_deliver(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runtime/system_lifecycle_state.json"
    lifecycle._save(path, {"boot_id": "a" * 32, "recorded": ["boot"], "pending": []})
    original = os.fsync

    def fail_sync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == path.stat().st_ino:
            raise OSError("durability uncertain")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_sync)
    monkeypatch.setattr(
        lifecycle, "deliver_notification_outbox", lambda **_: pytest.fail("delivery")
    )
    with pytest.raises(notifications.NotificationOutboxError):
        lifecycle.notify_system_lifecycle(config=config, state_dir=tmp_path, action="boot")


@pytest.mark.parametrize("policy", ["periodic", "wifi", "usb_otg", "combined"])
@pytest.mark.parametrize("failure", ["read", "ack_before", "ack_after"])
def test_lifecycle_failure_preserves_independently_durable_reboots(
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
    failure: str,
) -> None:
    enabled = {"periodic", "wifi", "usb_otg"} if policy == "combined" else {policy}
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            periodic_reboot_enabled="periodic" in enabled,
            periodic_reboot_hours=1,
            wifi_watchdog_enabled="wifi" in enabled,
            wifi_reconnect_enabled=False,
            wifi_reboot_enabled=True,
            wifi_reboot_after_minutes=1,
            usb_otg_watchdog_enabled="usb_otg" in enabled,
            usb_otg_reboot_enabled=True,
            usb_otg_reboot_attempts=1,
        ),
    )
    lifecycle_path = tmp_path / "runtime/system_lifecycle_state.json"
    lifecycle._save(
        lifecycle_path,
        {"boot_id": "a" * 32, "recorded": ["boot"], "pending": []},
    )
    real_save = lifecycle._save

    def fail_ack(path: Path, data: dict[str, object]) -> None:
        if failure == "ack_after":
            real_save(path, data)
        raise notifications.NotificationOutboxError("lifecycle ACK failed")

    monkeypatch.setattr(lifecycle, "_save", fail_ack)
    state = self_healing.new_self_healing_state(now_monotonic=0)
    state.wifi_outage_started_monotonic = 0
    state.usb_otg_rebind_attempted = True
    self_healing.persist_usb_otg_watchdog_state(
        self_healing.usb_otg_watchdog_state_path(tmp_path), state
    )
    monkeypatch.setattr(self_healing_runtime, "default_reboot_boot_id", lambda: "boot-one")
    monkeypatch.setattr(
        self_healing_runtime,
        "evaluate_self_healing",
        partial(
            self_healing.evaluate_self_healing,
            now_monotonic=7200,
            connectivity_checker=lambda *_: False,
            usb_otg_health_checker=lambda *_: self_healing.USBOTGHealth(
                False, "not attached", "controller", "powered"
            ),
            usb_otg_rebind_action=lambda *_: pytest.fail("unexpected rebind"),
            usb_otg_boot_id_reader=lambda: "boot-one",
        ),
    )
    monkeypatch.setattr(
        self_healing_runtime, "deliver_notification_outbox", lambda **_: pytest.fail("delivery")
    )
    scheduled: list[bool] = []

    def schedule() -> None:
        durable = self_healing.new_self_healing_state()
        with self_healing.usb_otg_watchdog_state_path(tmp_path).open() as source:
            usb = json.load(source)
        self_healing.load_wifi_watchdog_state(
            self_healing.wifi_watchdog_state_path(tmp_path), durable
        )
        if "periodic" in enabled:
            assert usb["periodic_reboot_requested"]
            assert usb["periodic_reboot_scheduled_boot_id"] == "boot-one"
        if "wifi" in enabled:
            assert durable.wifi_recovery_phase == "reboot_authorized"
            assert durable.wifi_reboot_scheduled_boot_id == "boot-one"
        if "usb_otg" in enabled:
            assert usb["pending_action"] == "reboot"
            assert usb["pending_reboot_boot_id"] == "boot-one"
            assert usb["reboot_attempts_used"] == 1
        scheduled.append(True)

    monkeypatch.setattr(self_healing_runtime, "default_schedule_reboot", schedule)
    for cycle in range(2):
        if failure == "read":
            lifecycle_path.write_text("corrupt")
        else:
            real_save(
                lifecycle_path,
                {
                    "boot_id": "a" * 32,
                    "recorded": ["boot"],
                    "pending": [
                        {
                            "boot_id": "a" * 32,
                            "action": "boot",
                            "occurred_at": datetime.now(UTC).isoformat(),
                        }
                    ],
                },
            )
        if cycle:
            state = self_healing.new_self_healing_state(now_monotonic=7200)
        events = self_healing_runtime.run_self_healing(
            config=config, state=state, state_dir=tmp_path
        )
        actions = {event.action for event in events}
        assert "lifecycle_notification_handoff_failed" in actions
        assert {f"{name}_reboot_requested" for name in enabled} <= actions
    assert scheduled == [True, True]


@pytest.mark.parametrize("start", [0, 1])
@pytest.mark.parametrize("web", [0, 1])
@pytest.mark.parametrize("action", ["enable", "restart"])
@pytest.mark.parametrize(
    "unit",
    [
        "bm-gateway-lifecycle.service",
        "bm-gateway-boot-notification.service",
        "bm-gateway.service",
        "bm-gateway-web.service",
    ],
)
def test_installer_notification_activation_failure_is_nonfatal(
    start: int, web: int, action: str, unit: str
) -> None:
    source = Path("rpi-setup/scripts/install-service.sh").read_text()
    block = source.split("\nsystemctl daemon-reload\n", 1)[1].split(
        "\nprintf 'Installed runtime service", 1
    )[0]
    script = """set -euo pipefail
systemctl() {
  printf '%s\\n' "$*"
  if [[ "$*" == "$failure" ]]; then
    printf 'injected systemctl failure: %s\\n' "$*" >&2
    return 1
  fi
}
"""
    systemctl_action = action
    if action == "restart" and unit == "bm-gateway-boot-notification.service":
        systemctl_action = "restart --no-block"
    result = subprocess.run(
        ["bash", "-c", script + block],
        env={
            **os.environ,
            "failure": f"{systemctl_action} {unit}",
            "start_services": str(start),
            "enable_web": str(web),
            "enable_glances": "0",
            "enable_cockpit": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    attempted = (action == "enable" or start == 1) and (
        unit != "bm-gateway-web.service" or web == 1
    )
    optional = unit in {"bm-gateway-lifecycle.service", "bm-gateway-boot-notification.service"}
    fatal = attempted and not optional
    assert result.returncode == int(fatal)
    assert bool(result.stderr) == attempted
    if not fatal:
        assert "enable bm-gateway.service" in result.stdout
        assert ("restart bm-gateway.service" in result.stdout) == bool(start)
        assert ("restart bm-gateway-web.service" in result.stdout) == bool(start and web)
        assert ("restart --no-block bm-gateway-boot-notification.service" in result.stdout) == bool(
            start
        )
        assert "restart --no-block bm-gateway.service" not in result.stdout
        assert "restart --no-block bm-gateway-web.service" not in result.stdout
