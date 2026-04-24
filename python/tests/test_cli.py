from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from bm_gateway import cli
from bm_gateway.models import GatewaySnapshot


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
