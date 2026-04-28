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
    _chromium_capture_height,
    _compact_frame_chart_points,
    _crop_screenshot_to_frame,
    _run_chromium_screenshot,
    build_drive_export_command,
    effective_refresh_interval_seconds,
    expected_usb_otg_export_steps,
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


def test_crop_screenshot_to_frame_preserves_top_left_frame(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "target.png"
    image = Image.new("RGB", (4, 5), "#000000")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((2, 1), (0, 255, 0))
    image.putpixel((3, 4), (0, 0, 255))
    image.save(source, format="PNG")

    _crop_screenshot_to_frame(source, target, 3, 2)

    with Image.open(target) as cropped:
        assert cropped.size == (3, 2)
        assert cropped.getpixel((0, 0)) == (255, 0, 0)
        assert cropped.getpixel((2, 1)) == (0, 255, 0)


def test_chromium_capture_height_compensates_headless_window_inset() -> None:
    assert _chromium_capture_height(234) == 321
    assert _chromium_capture_height(1080) == 1167


def test_chromium_screenshot_timeout_kills_process_group(
    monkeypatch: MonkeyPatch,
) -> None:
    killed: list[tuple[int, int]] = []

    class FakeProcess:
        pid = 1234
        returncode = -15

        def __init__(self) -> None:
            self.calls = 0

        def communicate(self, timeout: int | None = None) -> tuple[str, str]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(["chromium"], timeout or 0.0)
            return "", ""

    monkeypatch.setattr(
        "bm_gateway.usb_otg_export.subprocess.Popen",
        lambda *_, **__: FakeProcess(),
    )
    monkeypatch.setattr(
        "bm_gateway.usb_otg_export.os.killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    try:
        _run_chromium_screenshot(["chromium"])
    except RuntimeError as exc:
        assert "Chromium screenshot timed out" in str(exc)
    else:  # pragma: no cover - defensive assertion guard
        raise AssertionError("expected Chromium timeout")

    assert killed == [(1234, 15)]


def test_compact_frame_chart_points_limits_dense_series_and_keeps_latest() -> None:
    points = [
        {
            "ts": f"2026-04-27T{8 + index // 60:02d}:{index % 60:02d}:00+00:00",
            "series_id": "bm200_house",
            "kind": "raw",
            "soc": index,
        }
        for index in range(240)
    ]

    compacted = _compact_frame_chart_points(points, range_value="7", limit=24)

    assert len(compacted) <= 24
    assert compacted[-1]["soc"] == 239
    raw_values = [point.get("soc") for point in compacted if point.get("kind") == "raw"]
    assert raw_values[:4] == [0, 20, 40, 60]


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


def test_render_usb_otg_export_images_limits_overview_to_selected_frame_devices(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(
            config.usb_otg,
            export_battery_overview=True,
            export_fleet_trend=False,
            overview_devices_per_image=5,
            fleet_trend_device_ids=("bm200_house", "bm200_van"),
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
        Device(
            id="bm200_boat",
            type="bm200",
            name="Boat Battery",
            mac="AA:BB:CC:DD:EE:03",
            color_key="orange",
        ),
    ]
    base_snapshot = _snapshot()
    snapshot = replace(
        base_snapshot,
        devices=[
            *base_snapshot.devices,
            DeviceReading(
                id="bm200_boat",
                type="bm200",
                name="Boat Battery",
                mac="AA:BB:CC:DD:EE:03",
                enabled=True,
                connected=True,
                voltage=12.51,
                soc=64,
                temperature=19.5,
                rssi=-60,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2026-04-23T10:00:00+02:00",
                adapter="hci0",
                driver="bm200",
            ),
        ],
    )
    rendered_pages: list[str] = []

    def _capturing_frame_renderer(
        html_text: str,
        output_path: Path,
        width: int,
        height: int,
        image_format: str,
    ) -> None:
        rendered_pages.append(html_text)
        _fake_frame_renderer(html_text, output_path, width, height, image_format)

    files = render_usb_otg_export_images(
        config=config,
        devices=devices,
        snapshot=snapshot,
        database_path=tmp_path / "gateway.db",
        output_dir=tmp_path,
        page_renderer=_capturing_frame_renderer,
    )

    assert expected_usb_otg_export_steps(config, devices) == 2
    assert [file.name for file in files] == ["battery-overview-01.jpg"]
    combined_html = "\n".join(rendered_pages)
    assert "House Battery" in combined_html
    assert "Van Battery" in combined_html
    assert "Boat Battery" not in combined_html


def test_render_usb_otg_export_images_keeps_stale_frame_selection_empty(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(
            config.usb_otg,
            export_battery_overview=True,
            export_fleet_trend=False,
            overview_devices_per_image=5,
            fleet_trend_device_ids=("renamed_battery",),
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
    rendered_pages: list[str] = []

    def _capturing_frame_renderer(
        html_text: str,
        output_path: Path,
        width: int,
        height: int,
        image_format: str,
    ) -> None:
        rendered_pages.append(html_text)
        _fake_frame_renderer(html_text, output_path, width, height, image_format)

    files = render_usb_otg_export_images(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        database_path=tmp_path / "gateway.db",
        output_dir=tmp_path,
        page_renderer=_capturing_frame_renderer,
    )

    assert expected_usb_otg_export_steps(config, devices) == 2
    assert [file.name for file in files] == ["battery-overview-01.jpg"]
    combined_html = "\n".join(rendered_pages)
    assert "House Battery" not in combined_html
    assert "Van Battery" not in combined_html


def test_render_usb_otg_export_images_caps_overview_pages_at_three_devices(
    tmp_path: Path,
) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        usb_otg=replace(
            config.usb_otg,
            export_battery_overview=True,
            export_fleet_trend=False,
            overview_devices_per_image=5,
        ),
    )
    devices = [
        Device(
            id=f"bm200_{index}",
            type="bm200",
            name=f"Battery {index}",
            mac=f"AA:BB:CC:DD:EE:{index:02X}",
            color_key="green",
        )
        for index in range(1, 6)
    ]
    rendered_pages: list[str] = []

    def _capturing_frame_renderer(
        html_text: str,
        output_path: Path,
        width: int,
        height: int,
        image_format: str,
    ) -> None:
        rendered_pages.append(html_text)
        _fake_frame_renderer(html_text, output_path, width, height, image_format)

    files = render_usb_otg_export_images(
        config=config,
        devices=devices,
        snapshot=replace(_snapshot(), devices=[]),
        database_path=tmp_path / "gateway.db",
        output_dir=tmp_path,
        page_renderer=_capturing_frame_renderer,
    )

    assert expected_usb_otg_export_steps(config, devices) == 3
    assert [file.name for file in files] == ["battery-overview-01.jpg", "battery-overview-02.jpg"]
    assert "Battery 1" in rendered_pages[0]
    assert "Battery 2" in rendered_pages[0]
    assert "Battery 3" in rendered_pages[0]
    assert "Battery 4" not in rendered_pages[0]
    assert "Battery 5" not in rendered_pages[0]
    assert "Battery 4" in rendered_pages[1]
    assert "Battery 5" in rendered_pages[1]


def test_render_usb_otg_export_images_uses_configured_web_language(tmp_path: Path) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    config = replace(
        config,
        web=replace(config.web, language="it"),
        usb_otg=replace(
            config.usb_otg,
            image_format="png",
            export_battery_overview=True,
            export_fleet_trend=True,
        ),
    )
    devices = [
        Device(
            id="spare_nlp5",
            type="bm200",
            name="Spare NLP5",
            mac="AA:BB:CC:DD:EE:01",
            color_key="green",
            installed_in_vehicle=True,
            vehicle_type="bench",
        )
    ]
    base_snapshot = _snapshot()
    snapshot = replace(
        base_snapshot,
        devices=[
            replace(base_snapshot.devices[0], id="spare_nlp5", name="Spare NLP5"),
            replace(base_snapshot.devices[1], id="spare_nlp20", name="Spare NLP20"),
        ],
    )
    rendered_pages: list[str] = []

    def _capturing_frame_renderer(
        html_text: str,
        output_path: Path,
        width: int,
        height: int,
        image_format: str,
    ) -> None:
        rendered_pages.append(html_text)
        _fake_frame_renderer(html_text, output_path, width, height, image_format)

    render_usb_otg_export_images(
        config=config,
        devices=devices,
        snapshot=snapshot,
        database_path=tmp_path / "gateway.db",
        output_dir=tmp_path,
        page_renderer=_capturing_frame_renderer,
    )

    combined_html = "\n".join(rendered_pages)
    assert '<html lang="it" dir="ltr">' in combined_html
    assert "Panoramica batteria" in combined_html
    assert "Andamento flotta" in combined_html
    assert "Banco" in combined_html
    assert "Battery Overview" not in combined_html
    assert "Fleet Trend" not in combined_html
    assert "Bench" not in combined_html


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
        assert source_dir.parent == tmp_path / "runtime"
        return subprocess.CompletedProcess(command, 0, "", "")

    result = update_usb_otg_drive(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        database_path=tmp_path / "runtime" / "gateway.db",
        runner=_runner,
        page_renderer=_fake_frame_renderer,
    )

    assert result.exported
    assert observed == {"source_mode": 0o755, "file_mode": 0o644}


def test_update_usb_otg_drive_returns_failure_when_rendering_fails(tmp_path: Path) -> None:
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

    def _failing_renderer(
        html_text: str,
        output_path: Path,
        width: int,
        height: int,
        image_format: str,
    ) -> None:
        raise RuntimeError("render failed")

    result = update_usb_otg_drive(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        database_path=tmp_path / "runtime" / "gateway.db",
        page_renderer=_failing_renderer,
    )

    assert result.exported is False
    assert result.reason == "render failed"


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
    mark_usb_otg_exported(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 10, tzinfo=timezone.utc),
    )

    assert export_due(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 2, tzinfo=timezone.utc),
    )
    mark_usb_otg_exported(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc),
    )

    assert export_due(
        config=config,
        state_dir=tmp_path,
        now=datetime(2026, 4, 23, 10, 5, tzinfo=timezone.utc),
    )
