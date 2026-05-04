from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from bm_gateway.system_alerts import collect_gateway_alerts


def test_collect_gateway_alerts_skips_default_host_checks_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bm_gateway.system_alerts.sys.platform", "darwin")

    alerts = collect_gateway_alerts(expected_hostname="bmgateway")

    assert alerts == []


def test_collect_gateway_alerts_detects_soft_blocked_bluetooth(tmp_path: Path) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    (bluetooth_root / "hci0").mkdir()

    rfkill_root = tmp_path / "rfkill"
    rfkill_entry = rfkill_root / "rfkill0"
    rfkill_entry.mkdir(parents=True)
    (rfkill_entry / "type").write_text("bluetooth\n", encoding="utf-8")
    (rfkill_entry / "name").write_text("hci0\n", encoding="utf-8")
    (rfkill_entry / "soft").write_text("1\n", encoding="utf-8")
    (rfkill_entry / "hard").write_text("0\n", encoding="utf-8")
    (rfkill_entry / "state").write_text("0\n", encoding="utf-8")

    def fake_run(
        command: list[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str] | None:
        _ = timeout_seconds
        if command[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")
        if command[:2] == ["journalctl", "-u"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["bluetoothctl", "show"]:
            return subprocess.CompletedProcess(command, 0, stdout="Powered: yes\n", stderr="")
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert [alert.code for alert in alerts] == ["bluetooth_soft_blocked"]
    assert alerts[0].context == {"controller": "hci0"}


def test_collect_gateway_alerts_detects_mdns_hostname_mismatch(tmp_path: Path) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    (bluetooth_root / "hci0").mkdir()

    rfkill_root = tmp_path / "rfkill"
    rfkill_entry = rfkill_root / "rfkill0"
    rfkill_entry.mkdir(parents=True)
    (rfkill_entry / "type").write_text("bluetooth\n", encoding="utf-8")
    (rfkill_entry / "name").write_text("hci0\n", encoding="utf-8")
    (rfkill_entry / "soft").write_text("0\n", encoding="utf-8")
    (rfkill_entry / "hard").write_text("0\n", encoding="utf-8")
    (rfkill_entry / "state").write_text("1\n", encoding="utf-8")

    def fake_run(
        command: list[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str] | None:
        _ = timeout_seconds
        if command == ["systemctl", "is-active", "bluetooth.service"]:
            return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")
        if command == ["systemctl", "is-active", "avahi-daemon.service"]:
            return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")
        if command[:2] == ["bluetoothctl", "show"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Controller B8:27:EB:4E:EC:55 (public)\nPowered: yes\n",
                stderr="",
            )
        if command[:2] == ["journalctl", "-u"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "Server startup complete. Host name is bmgateway-2.local. "
                    "Local service cookie is 12345.\n"
                ),
                stderr="",
            )
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert [alert.code for alert in alerts] == ["mdns_hostname_mismatch"]
    assert alerts[0].context == {
        "expected_hostname": "bmgateway.local",
        "advertised_hostname": "bmgateway-2.local",
    }
