from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from bm_gateway.config import load_config
from bm_gateway.self_healing import (
    default_schedule_reboot,
    default_wifi_reconnect,
    evaluate_self_healing,
    new_self_healing_state,
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

    def _offline(_host: str) -> bool:
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
    assert reboot_calls == 1


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
        connectivity_checker=lambda _host: False,
    )
    restored = evaluate_self_healing(
        config=config,
        state=state,
        now_monotonic=30.0,
        connectivity_checker=lambda _host: True,
    )

    assert [event.action for event in lost] == ["wifi_connectivity_lost"]
    assert [event.action for event in restored] == ["wifi_connectivity_restored"]
    assert state.wifi_outage_started_monotonic is None


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
