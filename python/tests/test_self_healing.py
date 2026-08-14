from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from bm_gateway.config import load_config
from bm_gateway.self_healing import (
    USBOTGHealth,
    USBOTGWatchdogStateError,
    acknowledge_wifi_recovery_notification,
    default_connectivity_checker,
    default_schedule_reboot,
    default_usb_otg_health_check,
    default_usb_otg_rebind,
    default_wifi_reconnect,
    evaluate_self_healing,
    load_usb_otg_watchdog_state,
    load_wifi_watchdog_state,
    new_self_healing_state,
    persist_usb_otg_watchdog_state,
    persist_wifi_watchdog_state,
    usb_otg_watchdog_state_path,
    wifi_watchdog_state_path,
)


def test_self_healing_requests_periodic_reboot_once() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            periodic_reboot_enabled=True,
            periodic_reboot_hours=1,
        ),
    )
    state = new_self_healing_state(now_monotonic=100.0)
    reboot_calls = 0

    def _reboot() -> None:
        nonlocal reboot_calls
        reboot_calls += 1

    first = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=3700.0,
        reboot_action=_reboot,
    )
    second = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=7300.0,
        reboot_action=_reboot,
    )

    assert [event.action for event in first] == ["periodic_reboot_requested"]
    assert second == []
    assert reboot_calls == 1


def test_self_healing_reconnects_wifi_before_rebooting() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_watchdog_enabled=True,
            wifi_interface="wlan1",
            connectivity_check_host="192.168.1.1",
            wifi_reconnect_enabled=True,
            wifi_reconnect_after_minutes=5,
            wifi_reboot_enabled=True,
            wifi_reboot_after_minutes=15,
        ),
    )
    state = new_self_healing_state(now_monotonic=0.0)
    reconnect_calls: list[str] = []
    reboot_calls = 0

    def _offline(_host: str, _interface: str) -> bool:
        return False

    def _reconnect(interface: str) -> bool:
        reconnect_calls.append(interface)
        return True

    def _reboot() -> None:
        nonlocal reboot_calls
        reboot_calls += 1

    lost = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=10.0,
        connectivity_checker=_offline,
        reconnect_action=_reconnect,
        reboot_action=_reboot,
    )
    reconnect = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=310.0,
        connectivity_checker=_offline,
        reconnect_action=_reconnect,
        reboot_action=_reboot,
    )
    reboot = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=910.0,
        connectivity_checker=_offline,
        reconnect_action=_reconnect,
        reboot_action=_reboot,
    )

    assert [event.action for event in lost] == ["wifi_connectivity_lost"]
    assert [event.action for event in reconnect] == ["wifi_reconnect_attempted"]
    assert reconnect[0].status == "completed"
    assert [event.action for event in reboot] == ["wifi_reboot_requested"]
    assert reconnect_calls == ["wlan1"]
    assert reboot_calls == 0


def test_self_healing_resets_wifi_outage_after_connectivity_returns() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        self_healing=replace(config.self_healing, wifi_watchdog_enabled=True),
    )
    state = new_self_healing_state(now_monotonic=0.0)

    lost = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=10.0,
        connectivity_checker=lambda _host, _interface: False,
    )
    restored = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=30.0,
        connectivity_checker=lambda _host, _interface: True,
    )

    assert [event.action for event in lost] == ["wifi_connectivity_lost"]
    assert [event.action for event in restored] == ["wifi_connectivity_restored"]
    assert state.wifi_outage_started_monotonic is None


def test_wifi_watchdog_emits_restoration_after_a_persisted_reboot_request(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        self_healing=replace(
            config.self_healing,
            wifi_watchdog_enabled=True,
            wifi_reboot_enabled=True,
            wifi_reboot_after_minutes=1,
            wifi_reconnect_enabled=False,
        ),
    )
    state_path = wifi_watchdog_state_path(tmp_path)
    first = new_self_healing_state(now_monotonic=0.0)

    evaluate_self_healing(
        config=config,
        state=first,
        now_monotonic=10.0,
        connectivity_checker=lambda _host, _interface: False,
    )
    reboot = evaluate_self_healing(
        config=config,
        state=first,
        now_monotonic=70.0,
        now_wall_time=1060.0,
        connectivity_checker=lambda _host, _interface: False,
    )
    persist_wifi_watchdog_state(state_path, first)

    restarted = new_self_healing_state(now_monotonic=0.0)
    load_wifi_watchdog_state(state_path, restarted)
    restored = evaluate_self_healing(
        config=config,
        state=restarted,
        now_monotonic=10.0,
        now_wall_time=1100.0,
        connectivity_checker=lambda _host, _interface: True,
    )

    assert [event.action for event in reboot] == ["wifi_reboot_requested"]
    assert [event.action for event in restored] == ["wifi_connectivity_restored"]
    assert restored[0].details["outage_seconds"] == 100
    assert restarted.wifi_recovery_pending is True
    acknowledge_wifi_recovery_notification(state_path, restarted)
    assert restarted.wifi_recovery_pending is False


def test_usb_checkpoint_failure_preserves_a_prior_wifi_reboot_request() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(config.usb_otg, enabled=True),
        self_healing=replace(
            config.self_healing,
            wifi_watchdog_enabled=True,
            wifi_reboot_enabled=True,
            wifi_reboot_after_minutes=1,
            wifi_reconnect_enabled=False,
            usb_otg_watchdog_enabled=True,
            usb_otg_reboot_enabled=True,
            usb_otg_reboot_attempts=1,
        ),
    )
    state = new_self_healing_state(now_monotonic=0.0)
    evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=0.0,
        connectivity_checker=lambda _host, _interface: False,
    )

    def failed_checkpoint() -> None:
        raise USBOTGWatchdogStateError("cannot persist")

    events = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=60.0,
        connectivity_checker=lambda _host, _interface: False,
        usb_otg_health_checker=lambda _image, _gadget: USBOTGHealth(
            healthy=False,
            reason="not configured",
            udc_name=None,
            udc_state=None,
        ),
        usb_otg_state_checkpoint=failed_checkpoint,
    )

    assert [event.action for event in events] == [
        "wifi_reboot_requested",
        "usb_otg_watchdog_state_persist_failed",
    ]


def test_self_healing_rebinds_usb_otg_then_reboots_once_and_escalates() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(config.usb_otg, enabled=True),
        self_healing=replace(
            config.self_healing,
            usb_otg_watchdog_enabled=True,
            usb_otg_reboot_enabled=True,
            usb_otg_reboot_attempts=1,
        ),
    )
    state = new_self_healing_state(now_monotonic=0.0)
    rebind_calls: list[tuple[str, str]] = []
    checkpoints: list[tuple[bool, int]] = []

    def _unhealthy(_image_path: str, _gadget_name: str) -> USBOTGHealth:
        return USBOTGHealth(
            healthy=False,
            reason="UDC state is not configured",
            udc_name="3f980000.usb",
            udc_state="not attached",
        )

    def _rebind(image_path: str, gadget_name: str) -> bool:
        rebind_calls.append((image_path, gadget_name))
        return True

    def _checkpoint() -> None:
        checkpoints.append((state.usb_otg_rebind_attempted, state.usb_otg_reboot_attempts_used))

    first = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=10.0,
        usb_otg_health_checker=_unhealthy,
        usb_otg_rebind_action=_rebind,
        usb_otg_state_checkpoint=_checkpoint,
    )
    second = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=20.0,
        usb_otg_health_checker=_unhealthy,
        usb_otg_rebind_action=_rebind,
        usb_otg_state_checkpoint=_checkpoint,
    )
    third = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=30.0,
        usb_otg_health_checker=_unhealthy,
        usb_otg_rebind_action=_rebind,
        usb_otg_state_checkpoint=_checkpoint,
    )

    assert [event.action for event in first] == [
        "usb_otg_not_enumerated",
        "usb_otg_rebind_attempted",
    ]
    assert [event.action for event in second] == ["usb_otg_reboot_requested"]
    assert [event.action for event in third] == ["usb_otg_recovery_exhausted"]
    assert rebind_calls == [("/var/lib/bm-gateway/usb-otg/bmgateway-frame.img", "bmgw_frame")]
    assert state.usb_otg_reboot_attempts_used == 1
    assert checkpoints == [(True, 0), (True, 1)]


def test_self_healing_resets_usb_otg_recovery_after_enumeration_returns() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(config.usb_otg, enabled=True),
        self_healing=replace(config.self_healing, usb_otg_watchdog_enabled=True),
    )
    state = new_self_healing_state(now_monotonic=0.0)
    unhealthy = USBOTGHealth(False, "UDC state is not configured", "udc0", "not attached")
    healthy = USBOTGHealth(True, "", "udc0", "configured")

    evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=10.0,
        usb_otg_health_checker=lambda _image_path, _gadget_name: unhealthy,
        usb_otg_rebind_action=lambda _image_path, _gadget_name: True,
    )
    restored = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=20.0,
        usb_otg_health_checker=lambda _image_path, _gadget_name: healthy,
    )

    assert [event.action for event in restored] == ["usb_otg_enumeration_restored"]
    assert state.usb_otg_rebind_attempted is False
    assert state.usb_otg_reboot_attempts_used == 0
    assert state.usb_otg_escalated is False


def test_usb_otg_watchdog_state_survives_a_runtime_restart(tmp_path: Path) -> None:
    state_path = usb_otg_watchdog_state_path(tmp_path)
    initial = new_self_healing_state(now_monotonic=0.0)
    initial.usb_otg_rebind_attempted = True
    initial.usb_otg_reboot_attempts_used = 1
    initial.usb_otg_escalated = True

    persist_usb_otg_watchdog_state(state_path, initial)

    restored = new_self_healing_state(now_monotonic=0.0)
    load_usb_otg_watchdog_state(state_path, restored)

    assert restored.usb_otg_rebind_attempted is True
    assert restored.usb_otg_reboot_attempts_used == 1
    assert restored.usb_otg_escalated is True


def test_default_usb_otg_health_check_requires_configured_udc(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "frame.img"
    image_path.write_bytes(b"image")
    gadget_path = tmp_path / "configfs" / "usb_gadget" / "bmgw_frame"
    gadget_path.mkdir(parents=True)
    (gadget_path / "UDC").write_text("udc0\n", encoding="utf-8")
    state_path = tmp_path / "udc" / "udc0" / "state"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("configured\n", encoding="utf-8")

    health = default_usb_otg_health_check(
        str(image_path),
        "bmgw_frame",
        configfs_root=tmp_path / "configfs",
        udc_root=tmp_path / "udc",
    )

    assert health == USBOTGHealth(True, "", "udc0", "configured")

    state_path.write_text("not attached\n", encoding="utf-8")
    assert (
        default_usb_otg_health_check(
            str(image_path),
            "bmgw_frame",
            configfs_root=tmp_path / "configfs",
            udc_root=tmp_path / "udc",
        ).reason
        == "UDC state is not configured"
    )


def test_default_usb_otg_rebind_uses_scoped_helper(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr("bm_gateway.self_healing.subprocess.run", _run)

    assert default_usb_otg_rebind("/var/lib/bm-gateway/usb-otg/frame.img", "bmgw_frame")
    assert captured["command"] == [
        "sudo",
        "-n",
        "/usr/local/bin/bm-gateway-usb-otg-frame-test",
        "refresh",
        "--image-path",
        "/var/lib/bm-gateway/usb-otg/frame.img",
        "--gadget-name",
        "bmgw_frame",
    ]


def test_default_connectivity_checker_checks_configured_interface(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _which(command: str) -> str | None:
        return "/usr/bin/ping" if command == "ping" else None

    def _run(command: list[str], **_kwargs: object) -> object:
        captured["command"] = command

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr("bm_gateway.self_healing.shutil.which", _which)
    monkeypatch.setattr("bm_gateway.self_healing.subprocess.run", _run)

    assert default_connectivity_checker("1.1.1.1", "wlan0") is True
    assert captured["command"] == ["ping", "-c", "1", "-W", "3", "-I", "wlan0", "1.1.1.1"]


def test_default_wifi_reconnect_prefers_networkmanager(monkeypatch: MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def _which(command: str) -> str | None:
        return "/usr/bin/nmcli" if command == "nmcli" else None

    def _run(command: list[str], **_kwargs: object) -> object:
        commands.append(command)

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr("bm_gateway.self_healing.shutil.which", _which)
    monkeypatch.setattr("bm_gateway.self_healing.subprocess.run", _run)

    assert default_wifi_reconnect("wlan0") is True
    assert commands == [
        ["sudo", "-n", "nmcli", "radio", "wifi", "on"],
        ["sudo", "-n", "nmcli", "device", "connect", "wlan0"],
    ]


def test_default_schedule_reboot_uses_non_interactive_systemctl(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _popen(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("bm_gateway.self_healing.subprocess.Popen", _popen)

    default_schedule_reboot()

    assert captured["command"] == ["/bin/sh", "-lc", "sleep 1 && sudo -n systemctl reboot"]
    assert captured["kwargs"] == {
        "stdout": -3,
        "stderr": -3,
        "start_new_session": True,
    }
