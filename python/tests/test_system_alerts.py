from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from bm_gateway.system_alerts import GatewayAlert, collect_gateway_alerts, describe_gateway_alert


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
    hci0 = bluetooth_root / "hci0"
    hci0.mkdir()
    (hci0 / "address").write_text("B8:27:EB:4E:EC:55\n", encoding="utf-8")

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


def test_collect_gateway_alerts_reports_bluetoothctl_controller_identifier(tmp_path: Path) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    hci0 = bluetooth_root / "hci0"
    hci0.mkdir()
    (hci0 / "address").write_text("B8:27:EB:4E:EC:55\n", encoding="utf-8")

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
                stdout="Controller B8:27:EB:4E:EC:55 (public)\nPowered: no\n",
                stderr="",
            )
        if command[:2] == ["journalctl", "-u"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert [alert.code for alert in alerts] == ["bluetooth_powered_off"]
    assert alerts[0].context == {
        "controller": "B8:27:EB:4E:EC:55",
        "power_state": "",
    }


def test_collect_gateway_alerts_ignores_blocked_non_selected_adapter(tmp_path: Path) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    (bluetooth_root / "hci0").mkdir()
    (bluetooth_root / "hci1").mkdir()

    rfkill_root = tmp_path / "rfkill"
    rfkill0 = rfkill_root / "rfkill0"
    rfkill0.mkdir(parents=True)
    (rfkill0 / "type").write_text("bluetooth\n", encoding="utf-8")
    (rfkill0 / "name").write_text("hci0\n", encoding="utf-8")
    (rfkill0 / "soft").write_text("1\n", encoding="utf-8")
    (rfkill0 / "hard").write_text("0\n", encoding="utf-8")
    (rfkill0 / "state").write_text("0\n", encoding="utf-8")

    rfkill1 = rfkill_root / "rfkill1"
    rfkill1.mkdir(parents=True)
    (rfkill1 / "type").write_text("bluetooth\n", encoding="utf-8")
    (rfkill1 / "name").write_text("hci1\n", encoding="utf-8")
    (rfkill1 / "soft").write_text("0\n", encoding="utf-8")
    (rfkill1 / "hard").write_text("0\n", encoding="utf-8")
    (rfkill1 / "state").write_text("1\n", encoding="utf-8")

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
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway",
        configured_adapter="hci1",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert alerts == []


def test_collect_gateway_alerts_reports_missing_configured_adapter(tmp_path: Path) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    (bluetooth_root / "hci1").mkdir()

    rfkill_root = tmp_path / "rfkill"

    def fake_run(
        command: list[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str] | None:
        _ = (command, timeout_seconds)
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway",
        configured_adapter="hci0",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert [alert.code for alert in alerts] == ["bluetooth_controller_missing"]
    assert alerts[0].context == {"controller": "hci0"}


def test_collect_gateway_alerts_queries_power_state_for_selected_adapter(tmp_path: Path) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    hci0 = bluetooth_root / "hci0"
    hci0.mkdir()
    (hci0 / "address").write_text("AA:BB:CC:DD:EE:00\n", encoding="utf-8")
    hci1 = bluetooth_root / "hci1"
    hci1.mkdir()
    (hci1 / "address").write_text("B8:27:EB:4E:EC:55\n", encoding="utf-8")

    rfkill_root = tmp_path / "rfkill"
    rfkill0 = rfkill_root / "rfkill0"
    rfkill0.mkdir(parents=True)
    (rfkill0 / "type").write_text("bluetooth\n", encoding="utf-8")
    (rfkill0 / "name").write_text("hci0\n", encoding="utf-8")
    (rfkill0 / "soft").write_text("0\n", encoding="utf-8")
    (rfkill0 / "hard").write_text("0\n", encoding="utf-8")
    (rfkill0 / "state").write_text("1\n", encoding="utf-8")

    rfkill1 = rfkill_root / "rfkill1"
    rfkill1.mkdir(parents=True)
    (rfkill1 / "type").write_text("bluetooth\n", encoding="utf-8")
    (rfkill1 / "name").write_text("hci1\n", encoding="utf-8")
    (rfkill1 / "soft").write_text("0\n", encoding="utf-8")
    (rfkill1 / "hard").write_text("0\n", encoding="utf-8")
    (rfkill1 / "state").write_text("1\n", encoding="utf-8")

    seen_commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str] | None:
        _ = timeout_seconds
        seen_commands.append(command)
        if command == ["systemctl", "is-active", "bluetooth.service"]:
            return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")
        if command == ["systemctl", "is-active", "avahi-daemon.service"]:
            return subprocess.CompletedProcess(command, 0, stdout="active\n", stderr="")
        if command == ["bluetoothctl", "show"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Controller AA:BB:CC:DD:EE:00 (public)\nPowered: no\n",
                stderr="",
            )
        if command == ["bluetoothctl", "show", "B8:27:EB:4E:EC:55"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Controller B8:27:EB:4E:EC:55 (public)\nPowered: yes\n",
                stderr="",
            )
        if command[:2] == ["journalctl", "-u"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway",
        configured_adapter="hci1",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert alerts == []
    assert ["bluetoothctl", "show", "B8:27:EB:4E:EC:55"] in seen_commands
    assert ["bluetoothctl", "show"] not in seen_commands


def test_describe_gateway_alert_reports_missing_configured_adapter() -> None:
    alert = GatewayAlert(
        code="bluetooth_controller_missing",
        severity="error",
        runbook="troubleshooting-bluetooth.md",
        context={"controller": "hci0"},
    )

    assert describe_gateway_alert(alert) == (
        "Configured Bluetooth adapter hci0 is missing. "
        "See the Raspberry Pi hardware audit or Bluetooth recovery runbook."
    )


def test_collect_gateway_alerts_does_not_append_local_to_qualified_hostname(
    tmp_path: Path,
) -> None:
    bluetooth_root = tmp_path / "bluetooth"
    bluetooth_root.mkdir()
    hci0 = bluetooth_root / "hci0"
    hci0.mkdir()
    (hci0 / "address").write_text("B8:27:EB:4E:EC:55\n", encoding="utf-8")

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
                    "Server startup complete. Host name is bmgateway.local. "
                    "Local service cookie is 12345.\n"
                ),
                stderr="",
            )
        return None

    alerts = collect_gateway_alerts(
        expected_hostname="bmgateway.local",
        bluetooth_sysfs_root=bluetooth_root,
        rfkill_root=rfkill_root,
        run_command=fake_run,
    )

    assert alerts == []
