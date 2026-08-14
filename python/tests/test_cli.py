from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from bm_gateway import __version__, cli
from bm_gateway.bluetooth_recovery import BluetoothRecoveryRequiredError
from bm_gateway.config import load_config
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.notifications import load_notification_outbox, notification_outbox_path
from bm_gateway.self_healing import SelfHealingEvent, USBOTGWatchdogStateError


def _write_example_files(tmp_path: Path) -> tuple[Path, Path]:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "bm200_house"',
                'type = "bm200"',
                'name = "BM200 House"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
                "",
                "[[devices]]",
                'id = "bm300_van"',
                'type = "bm300pro"',
                'name = "BM300 Van"',
                'mac = "AA:BB:CC:DD:EE:02"',
                "enabled = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "gateway.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 15",
                'device_registry = "devices.toml"',
                'reader_mode = "fake"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = true",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "secret"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = true",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return config_path, devices_path


def test_main_without_args_prints_focused_help(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main([])

    captured = capsys.readouterr()

    assert result == 0
    assert "usage: bm-gateway" in captured.out
    assert "config" in captured.out
    assert "devices" in captured.out
    assert "ha" in captured.out
    assert "run" in captured.out
    assert "web" not in captured.out


def test_package_version_matches_project_metadata() -> None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"

    with pyproject_path.open("rb") as handle:
        pyproject = tomllib.load(handle)

    assert __version__ == pyproject["project"]["version"]


def test_wifi_watchdog_notifications_queue_recovery_reboot_and_restoration(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        notifications=replace(
            config.notifications,
            enabled=True,
            recipient="operator@example.test",
        ),
    )
    outbox_path = notification_outbox_path(tmp_path)

    for event in (
        SelfHealingEvent(
            action="wifi_reconnect_attempted",
            status="failed",
            details={"wifi_interface": "wlan0", "outage_seconds": 300},
        ),
        SelfHealingEvent(
            action="wifi_reboot_requested",
            status="completed",
            details={"wifi_interface": "wlan0", "outage_seconds": 900},
        ),
        SelfHealingEvent(
            action="wifi_connectivity_restored",
            status="completed",
            details={"outage_seconds": 960},
        ),
        SelfHealingEvent(action="wifi_connectivity_lost", status="failed", details={}),
    ):
        cli._queue_wifi_watchdog_notification(
            path=outbox_path,
            config=config,
            event=event,
        )

    queued = load_notification_outbox(outbox_path)

    assert [event.action for event in queued] == [
        "wifi_reconnect_attempted",
        "wifi_reboot_requested",
        "wifi_connectivity_restored",
    ]
    assert queued[0].detail == "Wi-Fi reconnect failed after 300 seconds on wlan0."
    assert queued[1].detail == "Wi-Fi reboot requested after 900 seconds on wlan0."
    assert queued[2].detail == "Wi-Fi connectivity restored after 960 seconds."


def test_wifi_watchdog_notification_uses_configured_locale(tmp_path: Path) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        notifications=replace(
            config.notifications,
            enabled=True,
            recipient="operator@example.test",
            locale="it",
        ),
    )

    cli._queue_wifi_watchdog_notification(
        path=notification_outbox_path(tmp_path),
        config=config,
        event=SelfHealingEvent(
            action="wifi_connectivity_restored",
            status="completed",
            details={"outage_seconds": 960},
        ),
    )

    assert load_notification_outbox(notification_outbox_path(tmp_path))[0].detail == (
        "Connettivita Wi-Fi ripristinata dopo 960 secondi."
    )


def test_run_queues_wifi_watchdog_events_before_attempting_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[notifications]\n"
        + "enabled = true\n"
        + 'recipient = "operator@example.test"\n',
        encoding="utf-8",
    )
    queued: list[tuple[str, str]] = []
    delivered_after_queue = False
    event_order: list[str] = []

    monkeypatch.setattr(
        "bm_gateway.cli._run_cycle",
        lambda **_kwargs: GatewaySnapshot(
            generated_at="2026-08-14T20:00:00+00:00",
            gateway_name="BMGateway",
            active_adapter="hci0",
            mqtt_enabled=False,
            mqtt_connected=False,
            devices_total=0,
            devices_online=0,
            poll_interval_seconds=15,
            devices=[],
        ),
    )
    monkeypatch.setattr(
        "bm_gateway.cli.evaluate_self_healing",
        lambda **_kwargs: [
            SelfHealingEvent(
                action="wifi_reconnect_attempted",
                status="completed",
                details={"wifi_interface": "wlan0", "outage_seconds": 300},
            ),
            SelfHealingEvent(
                action="wifi_reboot_requested",
                status="completed",
                details={"wifi_interface": "wlan0", "outage_seconds": 900},
            ),
            SelfHealingEvent(
                action="wifi_connectivity_restored",
                status="completed",
                details={"outage_seconds": 960},
            ),
        ],
    )

    def fake_queue(**kwargs: object) -> None:
        action = str(kwargs["action"])
        queued.append((action, str(kwargs["detail"])))
        event_order.append(f"queue:{action}")

    monkeypatch.setattr("bm_gateway.cli.queue_notification_event", fake_queue)

    def fake_delivery(**_kwargs: object) -> tuple[bool, str]:
        nonlocal delivered_after_queue
        delivered_after_queue = True
        event_order.append("deliver")
        return True, "Pending notifications delivered"

    monkeypatch.setattr("bm_gateway.cli.deliver_notification_outbox", fake_delivery)
    monkeypatch.setattr(
        "bm_gateway.cli.default_schedule_reboot", lambda: event_order.append("wifi_reboot")
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
            "--state-dir",
            str(tmp_path / "state"),
        ]
    )

    assert result == 0
    assert [action for action, _detail in queued] == [
        "wifi_reconnect_attempted",
        "wifi_reboot_requested",
        "wifi_connectivity_restored",
    ]
    assert delivered_after_queue is True
    assert event_order.index("deliver") < event_order.index("wifi_reboot")


def test_run_reports_usb_watchdog_state_error_when_wifi_state_is_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[usb_otg]\n"
        + "enabled = true\n"
        + "\n[self_healing]\n"
        + "wifi_watchdog_enabled = true\n"
        + "usb_otg_watchdog_enabled = true\n",
        encoding="utf-8",
    )
    audits: list[str] = []

    def unavailable_usb_state(*_args: object, **_kwargs: object) -> None:
        raise USBOTGWatchdogStateError("unreadable USB state")

    monkeypatch.setattr("bm_gateway.cli.load_usb_otg_watchdog_state", unavailable_usb_state)
    monkeypatch.setattr(
        "bm_gateway.cli._run_cycle",
        lambda **_kwargs: GatewaySnapshot(
            generated_at="2026-08-14T20:00:00+00:00",
            gateway_name="BMGateway",
            active_adapter="hci0",
            mqtt_enabled=False,
            mqtt_connected=False,
            devices_total=0,
            devices_online=0,
            poll_interval_seconds=15,
            devices=[],
        ),
    )
    monkeypatch.setattr("bm_gateway.cli.evaluate_self_healing", lambda **_kwargs: [])
    monkeypatch.setattr(
        "bm_gateway.cli.append_audit_event",
        lambda **kwargs: audits.append(str(kwargs["action"])),
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
            "--state-dir",
            str(tmp_path / "state"),
        ]
    )

    assert result == 0
    assert audits == ["usb_otg_watchdog_state_unavailable"]


def test_cli_version_commands_emit_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    from bm_gateway.web_cli import main as web_main

    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__

    assert web_main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_config_show_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)

    result = cli.main(["--config", str(config_path), "config", "show", "--json"])

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["gateway"]["name"] == "BMGateway"
    assert payload["gateway"]["device_registry"].endswith("devices.toml")
    assert payload["mqtt"]["base_topic"] == "bm_gateway"


def test_config_validate_reports_valid_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)

    result = cli.main(["--config", str(config_path), "config", "validate"])

    captured = capsys.readouterr()

    assert result == 0
    assert "Configuration is valid." in captured.out
    assert "2 devices loaded" in captured.out


def test_devices_list_emits_registry_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)

    result = cli.main(["--config", str(config_path), "devices", "list", "--json"])

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert len(payload["devices"]) == 2
    assert payload["devices"][0]["id"] == "bm200_house"
    assert payload["devices"][1]["enabled"] is False


def test_ha_contract_emits_topics_and_entities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)

    result = cli.main(["--config", str(config_path), "ha", "contract", "--json"])

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["gateway"]["state_topic"] == "bm_gateway/gateway/state"
    assert payload["devices"][0]["discovery_topic"] == "homeassistant/device/bm200_house/config"
    assert "voltage" in payload["devices"][0]["entities"]


def test_ha_discovery_writes_export_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    output_dir = tmp_path / "discovery"

    result = cli.main(
        [
            "--config",
            str(config_path),
            "ha",
            "discovery",
            "--output-dir",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert "homeassistant/device/bm_gateway/config" in captured.out
    assert (output_dir / "homeassistant__device__bm_gateway__config.json").exists()
    assert (output_dir / "homeassistant__device__bm200_house__config.json").exists()


def test_main_uses_sys_argv_when_no_explicit_argv_is_passed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["bm-gateway", "--config", str(config_path), "config", "validate"],
    )

    result = cli.main()

    captured = capsys.readouterr()

    assert result == 0
    assert "Configuration is valid." in captured.out


def test_run_once_writes_snapshot_and_emits_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
            "--dry-run",
            "--state-dir",
            str(state_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["devices_total"] == 2
    assert payload["devices_online"] == 1
    assert (state_dir / "runtime" / "latest_snapshot.json").exists()


def test_run_dry_run_export_now_skips_usb_otg_drive_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"
    update_calls: list[object] = []
    marker_calls: list[object] = []

    def _update_drive(**kwargs: object) -> object:
        update_calls.append(kwargs)
        raise AssertionError("dry-run must not update the USB OTG drive")

    def _mark_exported(**kwargs: object) -> None:
        marker_calls.append(kwargs)

    monkeypatch.setattr("bm_gateway.usb_otg_export.update_usb_otg_drive", _update_drive)
    monkeypatch.setattr("bm_gateway.usb_otg_export.mark_usb_otg_exported", _mark_exported)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
            "--dry-run",
            "--export-usb-otg-now",
            "--state-dir",
            str(state_dir),
        ]
    )

    assert result == 0
    assert update_calls == []
    assert marker_calls == []
    assert (state_dir / "runtime" / "latest_snapshot.json").exists()


def test_bm_gateway_main_help_does_not_advertise_web_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["--help"])

    captured = capsys.readouterr()

    assert result == 0
    assert "bm-gateway-web" not in captured.out
    assert "  web " not in captured.out


def test_removed_web_command_falls_back_to_main_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["web"])

    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "invalid choice: 'web'" in captured.err


def test_bm_gateway_web_render_outputs_html_from_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from bm_gateway.web_cli import main as web_main

    config_path, _devices_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"
    cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
            "--dry-run",
            "--state-dir",
            str(state_dir),
        ]
    )

    result = web_main(
        [
            "render",
            "--snapshot-file",
            str(state_dir / "runtime" / "latest_snapshot.json"),
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert "<title>BMGateway Status</title>" in captured.out


def test_run_reloads_config_and_device_registry_between_iterations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text("", encoding="utf-8")
    config_path = tmp_path / "gateway.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 1",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "127.0.0.1"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    observed_devices: list[list[str]] = []

    def fake_run_cycle(**kwargs: object) -> GatewaySnapshot:
        devices = kwargs["devices"]
        assert isinstance(devices, list)
        observed_devices.append([device.id for device in devices])
        if len(observed_devices) == 1:
            devices_path.write_text(
                "\n".join(
                    [
                        "[[devices]]",
                        'id = "ancell_bm200"',
                        'type = "bm200"',
                        'name = "Ancell BM200"',
                        'mac = "A1:B2:C3:D4:E5:F6"',
                        "enabled = true",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return GatewaySnapshot(
            generated_at="2026-04-18T23:00:00+02:00",
            gateway_name="BMGateway",
            active_adapter="hci0",
            mqtt_enabled=False,
            mqtt_connected=False,
            devices_total=len(devices),
            devices_online=0,
            poll_interval_seconds=1,
            devices=[],
        )

    monkeypatch.setattr("bm_gateway.cli._run_cycle", fake_run_cycle)
    monkeypatch.setattr("bm_gateway.cli.sleep_interval", lambda _seconds: None)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--iterations",
            "2",
            "--dry-run",
        ]
    )

    assert result == 0
    assert observed_devices == [[], ["ancell_bm200"]]


def test_run_returns_error_when_bluetooth_recovery_is_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text("", encoding="utf-8")
    config_path = tmp_path / "gateway.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 1",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "live"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "127.0.0.1"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_cycle(**_kwargs: object) -> GatewaySnapshot:
        raise BluetoothRecoveryRequiredError(
            error=RuntimeError("fatal dbus transport"),
            recovery_attempted=True,
        )

    monkeypatch.setattr("bm_gateway.cli._run_cycle", fake_run_cycle)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--once",
        ]
    )

    captured = capsys.readouterr()

    assert result == 1
    assert "Bluetooth recovery requested" in captured.err


def test_run_requests_bluetooth_recovery_after_consecutive_all_timeout_cycles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _devices_path = _write_example_files(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'reader_mode = "fake"',
            'reader_mode = "live"',
        ),
        encoding="utf-8",
    )
    timeout_snapshot = GatewaySnapshot(
        generated_at="2026-05-30T18:00:00+02:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=False,
        mqtt_connected=False,
        devices_total=1,
        devices_online=0,
        poll_interval_seconds=1,
        devices=[
            DeviceReading(
                id="bm200_house",
                type="bm200",
                name="BM200 House",
                mac="AA:BB:CC:DD:EE:01",
                enabled=True,
                connected=False,
                voltage=0.0,
                soc=0,
                temperature=None,
                rssi=None,
                state="error",
                error_code="timeout",
                error_detail="timed out",
                last_seen="",
                adapter="hci0",
                driver="bm200",
                last_attempt="2026-05-30T18:00:00+02:00",
            )
        ],
    )
    cycle_count = {"count": 0}
    recovery_errors: list[str] = []

    def fake_run_cycle(**_kwargs: object) -> GatewaySnapshot:
        cycle_count["count"] += 1
        return timeout_snapshot

    def fake_require_bluetooth_recovery(error: BaseException) -> None:
        recovery_errors.append(str(error))
        raise BluetoothRecoveryRequiredError(error=error, recovery_attempted=True)

    monkeypatch.setattr("bm_gateway.cli._run_cycle", fake_run_cycle)
    monkeypatch.setattr(
        "bm_gateway.cli.require_bluetooth_recovery",
        fake_require_bluetooth_recovery,
    )
    monkeypatch.setattr("bm_gateway.cli.collect_gateway_alerts", lambda **_kwargs: [])
    monkeypatch.setattr("bm_gateway.cli.sleep_interval", lambda _seconds: None)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "run",
            "--iterations",
            "3",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()

    assert result == 1
    assert cycle_count["count"] == 2
    assert recovery_errors == [
        "No enabled live devices came online for 2 consecutive cycles; "
        "readings were timeout or device_not_found."
    ]
    assert "Bluetooth recovery requested" in captured.err
