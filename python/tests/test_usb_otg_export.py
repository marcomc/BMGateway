from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from bm_gateway.config import load_config
from bm_gateway.device_registry import Device
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.usb_otg import usb_otg_support_installed
from bm_gateway.usb_otg_export import (
    build_drive_export_command,
    effective_refresh_interval_seconds,
    export_due,
    mark_usb_otg_exported,
    render_usb_otg_export_images,
    update_usb_otg_drive,
)
from PIL import Image


def _fake_frame_renderer(
    html_text: str,
    output_path: Path,
    width: int,
    height: int,
    image_format: str,
) -> None:
    assert "frame-capture-root" in html_text
    image = Image.new("RGB", (width, height), "#111214")
    if image_format == "jpeg":
        image.save(output_path, format="JPEG")
    elif image_format == "png":
        image.save(output_path, format="PNG")
    else:
        image.save(output_path, format="BMP")


def test_usb_otg_support_detects_installed_helper_and_mkfs_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    helper = tmp_path / "bm-gateway-usb-otg-frame-test"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr("bm_gateway.usb_otg.shutil.which", lambda _name: "/usr/sbin/mkfs.vfat")

    assert usb_otg_support_installed(drive_helper_path=helper)


def _snapshot() -> GatewaySnapshot:
    return GatewaySnapshot(
        generated_at="2026-04-23T10:00:00+02:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=False,
        mqtt_connected=False,
        devices_total=2,
        devices_online=2,
        poll_interval_seconds=300,
        devices=[
            DeviceReading(
                id="bm200_house",
                type="bm200",
                name="House Battery",
                mac="AA:BB:CC:DD:EE:01",
                enabled=True,
                connected=True,
                voltage=13.12,
                soc=88,
                temperature=22.4,
                rssi=-48,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2026-04-23T10:00:00+02:00",
                adapter="hci0",
                driver="bm200",
            ),
            DeviceReading(
                id="bm200_van",
                type="bm200",
                name="Van Battery",
                mac="AA:BB:CC:DD:EE:02",
                enabled=True,
                connected=True,
                voltage=12.75,
                soc=71,
                temperature=24.0,
                rssi=-55,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2026-04-23T10:00:00+02:00",
                adapter="hci0",
                driver="bm200",
            ),
        ],
    )


def test_render_usb_otg_export_images_creates_configured_frame_size(tmp_path: Path) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(
            config.usb_otg,
            image_width_px=480,
            image_height_px=234,
            image_format="jpeg",
        ),
    )
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="House Battery",
            mac="AA:BB:CC:DD:EE:01",
            color_key="green",
        ),
        Device(
            id="bm200_van",
            type="bm200",
            name="Van Battery",
            mac="AA:BB:CC:DD:EE:02",
            color_key="blue",
        ),
    ]

    files = render_usb_otg_export_images(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        database_path=tmp_path / "gateway.db",
        output_dir=tmp_path,
        page_renderer=_fake_frame_renderer,
    )

    assert [file.name for file in files] == ["battery-overview-01.jpg", "fleet-trend-soc.jpg"]
    for file in files:
        with Image.open(file) as image:
            assert image.size == (480, 234)


def test_render_usb_otg_export_images_creates_selected_fleet_metric_images(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(
            config.usb_otg,
            export_battery_overview=False,
            fleet_trend_metrics=("voltage", "temperature"),
            fleet_trend_device_ids=("bm200_van",),
        ),
    )
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="House Battery",
            mac="AA:BB:CC:DD:EE:01",
            color_key="green",
        ),
        Device(
            id="bm200_van",
            type="bm200",
            name="Van Battery",
            mac="AA:BB:CC:DD:EE:02",
            color_key="blue",
        ),
    ]

    files = render_usb_otg_export_images(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        database_path=tmp_path / "gateway.db",
        output_dir=tmp_path,
        page_renderer=_fake_frame_renderer,
    )

    assert [file.name for file in files] == [
        "fleet-trend-voltage.jpg",
        "fleet-trend-temperature.jpg",
    ]


def test_build_drive_export_command_targets_installed_usb_otg_helper(tmp_path: Path) -> None:
    config = load_config(Path("python/config/config.toml.example"))

    command = build_drive_export_command(config, tmp_path)

    assert command[:4] == ["sudo", "-n", "/usr/local/bin/bm-gateway-usb-otg-frame-test", "setup"]
    assert "--source-dir" in command
    assert str(tmp_path) in command
    assert "--image-path" in command
    assert config.usb_otg.image_path in command


def test_update_usb_otg_drive_makes_staging_directory_readable_by_helper(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(config, usb_otg=replace(config.usb_otg, enabled=True))
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="House Battery",
            mac="AA:BB:CC:DD:EE:01",
            color_key="green",
        )
    ]
    observed: dict[str, int] = {}

    def _runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        source_dir = Path(command[command.index("--source-dir") + 1])
        files = list(source_dir.iterdir())
        observed["source_mode"] = source_dir.stat().st_mode & 0o777
        observed["file_mode"] = files[0].stat().st_mode & 0o777
        return subprocess.CompletedProcess(command, 0, "", "")

    result = update_usb_otg_drive(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        database_path=tmp_path / "gateway.db",
        runner=_runner,
        page_renderer=_fake_frame_renderer,
    )

    assert result.exported
    assert observed == {"source_mode": 0o755, "file_mode": 0o644}


def test_usb_otg_export_due_uses_poll_interval_when_refresh_interval_is_zero(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        source_path=tmp_path / "config.toml",
        usb_otg=replace(config.usb_otg, enabled=True, refresh_interval_seconds=0),
    )

    assert effective_refresh_interval_seconds(config) == config.gateway.poll_interval_seconds
    assert export_due(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc),
    )

    mark_usb_otg_exported(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc),
    )

    assert not export_due(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 1, tzinfo=timezone.utc),
    )
    assert export_due(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 5, tzinfo=timezone.utc),
    )
