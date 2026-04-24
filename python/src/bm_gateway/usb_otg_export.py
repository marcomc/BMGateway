"""USB OTG picture-frame image export support."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from typing import Any, Callable

from .config import AppConfig
from .device_registry import Device
from .localization import resolve_locale_preference
from .models import GatewaySnapshot
from .web_pages import _fleet_chart_points
from .web_pages_frame import (
    render_frame_battery_overview_html,
    render_frame_fleet_trend_html,
)

DriveCommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
FramePageRenderer = Callable[[str, Path, int, int, str], None]
ProgressReporter = Callable[[int, int, str], None]
_CHROMIUM_HEADLESS_WINDOW_VERTICAL_INSET_PX = 87


@dataclass(frozen=True)
class USBOTGExportResult:
    exported: bool
    reason: str
    files: tuple[Path, ...] = ()


def effective_refresh_interval_seconds(config: AppConfig) -> int:
    if config.usb_otg.refresh_interval_seconds > 0:
        return config.usb_otg.refresh_interval_seconds
    return config.gateway.poll_interval_seconds


def _extension(image_format: str) -> str:
    return "jpg" if image_format == "jpeg" else image_format


def _pillow_image_module() -> Any:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised only in minimal installs
        raise RuntimeError(
            "Pillow is required for USB OTG frame image export. "
            "Install bm-gateway with the usb-otg extra."
        ) from exc
    return Image


def expected_usb_otg_export_steps(config: AppConfig, devices: list[Device]) -> int:
    image_count = 0
    if config.usb_otg.export_battery_overview:
        per_image = config.usb_otg.overview_devices_per_image
        real_devices = [device for device in devices if device.enabled]
        if not real_devices:
            real_devices = devices
        image_count += max(1, (len(real_devices) + per_image - 1) // per_image)
    if config.usb_otg.export_fleet_trend:
        image_count += len(config.usb_otg.fleet_trend_metrics)
    return image_count + 1


def _save_screenshot_as_format(source_png: Path, path: Path, image_format: str) -> None:
    Image = _pillow_image_module()
    image = Image.open(source_png)
    if image_format == "jpeg":
        image.convert("RGB").save(path, format="JPEG", quality=92, optimize=True)
    elif image_format == "png":
        image.save(path, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(path, format="BMP")


def _export_language(config: AppConfig) -> str:
    return resolve_locale_preference(config.web.language, None)


def _crop_screenshot_to_frame(source_png: Path, path: Path, width: int, height: int) -> None:
    Image = _pillow_image_module()
    with Image.open(source_png) as image:
        image.crop((0, 0, width, height)).save(path, format="PNG")


def _chromium_capture_height(frame_height: int) -> int:
    return frame_height + _CHROMIUM_HEADLESS_WINDOW_VERTICAL_INSET_PX


def _find_chromium() -> str:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        candidate = which(name)
        if candidate:
            return candidate
    macos_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if macos_chrome.exists():
        return str(macos_chrome)
    raise RuntimeError(
        "Chromium is required for USB OTG frame screenshots. "
        "Install USB OTG support tools or install the chromium package."
    )


def _render_frame_page_with_chromium(
    html_text: str,
    output_path: Path,
    width: int,
    height: int,
    image_format: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bm-gateway-frame-page-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        html_path = temp_dir / "frame.html"
        png_path = temp_dir / "frame.png"
        cropped_png_path = temp_dir / "frame-cropped.png"
        html_path.write_text(html_text, encoding="utf-8")
        capture_height = _chromium_capture_height(height)
        command = [
            _find_chromium(),
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--hide-scrollbars",
            "--virtual-time-budget=1200",
            f"--window-size={width},{capture_height}",
            f"--screenshot={png_path}",
            html_path.as_uri(),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
        if completed.returncode != 0 or not png_path.exists():
            reason = (
                completed.stderr.strip() or completed.stdout.strip() or "Chromium screenshot failed"
            )
            raise RuntimeError(reason)
        _crop_screenshot_to_frame(png_path, cropped_png_path, width, height)
        _save_screenshot_as_format(cropped_png_path, output_path, image_format)


def render_battery_overview_images(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    output_dir: Path,
    page_renderer: FramePageRenderer = _render_frame_page_with_chromium,
    progress: ProgressReporter | None = None,
    completed_offset: int = 0,
    total_steps: int = 0,
) -> tuple[Path, ...]:
    width = config.usb_otg.image_width_px
    height = config.usb_otg.image_height_px
    per_image = config.usb_otg.overview_devices_per_image
    real_devices = [device for device in devices if device.enabled]
    if not real_devices:
        real_devices = devices
    pages = [
        real_devices[index : index + per_image] for index in range(0, len(real_devices), per_image)
    ]
    pages = pages or [[]]
    files: list[Path] = []
    serialized_devices = [device.to_dict() for device in devices]

    for page_index, _page_devices in enumerate(pages, start=1):
        path = output_dir / (
            f"battery-overview-{page_index:02d}.{_extension(config.usb_otg.image_format)}"
        )
        page_html = render_frame_battery_overview_html(
            snapshot=snapshot.to_dict(),
            devices=serialized_devices,
            page=page_index,
            devices_per_page=per_image,
            appearance=config.usb_otg.appearance,
            width=width,
            height=height,
            language=_export_language(config),
        )
        page_renderer(page_html, path, width, height, config.usb_otg.image_format)
        files.append(path)
        if progress is not None:
            progress(completed_offset + len(files), total_steps, "Rendered frame image")
    return tuple(files)


def _fleet_metric_filename(metric: str) -> str:
    return f"fleet-trend-{metric}"


def render_fleet_trend_image(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    database_path: Path,
    output_dir: Path,
    metric: str,
    page_renderer: FramePageRenderer = _render_frame_page_with_chromium,
    progress: ProgressReporter | None = None,
    completed_step: int = 0,
    total_steps: int = 0,
) -> Path:
    width = config.usb_otg.image_width_px
    height = config.usb_otg.image_height_px
    path = (
        output_dir / f"{_fleet_metric_filename(metric)}.{_extension(config.usb_otg.image_format)}"
    )
    serialized_devices = [device.to_dict() for device in devices]
    chart_points, legend = _fleet_chart_points(
        database_path=database_path,
        devices=serialized_devices,
    )
    page_html = render_frame_fleet_trend_html(
        chart_points=chart_points,
        legend=legend,
        show_chart_markers=False,
        appearance=config.usb_otg.appearance,
        default_chart_range=config.usb_otg.fleet_trend_range,
        default_chart_metric=metric,
        width=width,
        height=height,
        language=_export_language(config),
    )
    page_renderer(page_html, path, width, height, config.usb_otg.image_format)
    if progress is not None:
        progress(completed_step, total_steps, "Rendered frame image")
    return path


def _fleet_trend_export_devices(config: AppConfig, devices: list[Device]) -> list[Device]:
    selected_ids = set(config.usb_otg.fleet_trend_device_ids)
    if not selected_ids:
        return devices
    return [device for device in devices if device.id in selected_ids]


def render_usb_otg_export_images(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    database_path: Path,
    output_dir: Path,
    page_renderer: FramePageRenderer = _render_frame_page_with_chromium,
    progress: ProgressReporter | None = None,
    total_steps: int | None = None,
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    resolved_total_steps = total_steps or expected_usb_otg_export_steps(config, devices)
    if config.usb_otg.export_battery_overview:
        files.extend(
            render_battery_overview_images(
                config=config,
                devices=devices,
                snapshot=snapshot,
                output_dir=output_dir,
                page_renderer=page_renderer,
                progress=progress,
                completed_offset=len(files),
                total_steps=resolved_total_steps,
            )
        )
    if config.usb_otg.export_fleet_trend:
        for metric in config.usb_otg.fleet_trend_metrics:
            files.append(
                render_fleet_trend_image(
                    config=config,
                    devices=_fleet_trend_export_devices(config, devices),
                    snapshot=snapshot,
                    database_path=database_path,
                    output_dir=output_dir,
                    metric=metric,
                    page_renderer=page_renderer,
                    progress=progress,
                    completed_step=len(files) + 1,
                    total_steps=resolved_total_steps,
                )
            )
    return tuple(files)


def build_drive_export_command(config: AppConfig, source_dir: Path) -> list[str]:
    return [
        "sudo",
        "-n",
        "/usr/local/bin/bm-gateway-usb-otg-frame-test",
        "setup",
        "--source-dir",
        str(source_dir),
        "--image-path",
        config.usb_otg.image_path,
        "--size-mb",
        str(config.usb_otg.size_mb),
        "--gadget-name",
        config.usb_otg.gadget_name,
    ]


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)


def _prepare_source_dir_for_root_helper(source_dir: Path, files: tuple[Path, ...]) -> None:
    source_dir.chmod(0o755)
    for file_path in files:
        file_path.chmod(0o644)


def update_usb_otg_drive(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    database_path: Path,
    runner: DriveCommandRunner = _default_runner,
    page_renderer: FramePageRenderer = _render_frame_page_with_chromium,
    progress: ProgressReporter | None = None,
    force: bool = False,
) -> USBOTGExportResult:
    if not config.usb_otg.enabled and not force:
        return USBOTGExportResult(exported=False, reason="disabled")
    if not config.usb_otg.export_battery_overview and not config.usb_otg.export_fleet_trend:
        return USBOTGExportResult(exported=False, reason="no images enabled")
    total_steps = expected_usb_otg_export_steps(config, devices)
    if progress is not None:
        progress(0, total_steps, "Preparing USB OTG frame image export")
    with tempfile.TemporaryDirectory(prefix="bm-gateway-usb-otg-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        files = render_usb_otg_export_images(
            config=config,
            devices=devices,
            snapshot=snapshot,
            database_path=database_path,
            output_dir=temp_dir,
            page_renderer=page_renderer,
            progress=progress,
            total_steps=total_steps,
        )
        _prepare_source_dir_for_root_helper(temp_dir, files)
        if progress is not None:
            progress(max(0, total_steps - 1), total_steps, "Writing images to USB OTG drive")
        completed = runner(build_drive_export_command(config, temp_dir))
        if completed.returncode != 0:
            reason = completed.stderr.strip() or completed.stdout.strip() or "drive helper failed"
            if progress is not None:
                progress(total_steps, total_steps, "USB OTG frame image export failed")
            return USBOTGExportResult(exported=False, reason=reason, files=files)
    if progress is not None:
        progress(total_steps, total_steps, "USB OTG frame images exported")
    return USBOTGExportResult(exported=True, reason="exported", files=files)


def export_due(
    *,
    config: AppConfig,
    state_dir: Path | None,
    now: datetime | None = None,
) -> bool:
    if not config.usb_otg.enabled:
        return False
    current = now or datetime.now(tz=timezone.utc)
    marker = usb_otg_export_marker_path(config, state_dir=state_dir)
    if not marker.exists():
        return True
    try:
        previous = datetime.fromisoformat(marker.read_text(encoding="utf-8").strip())
    except ValueError:
        return True
    elapsed_seconds = (current - previous).total_seconds()
    return elapsed_seconds < 0 or elapsed_seconds >= effective_refresh_interval_seconds(config)


def usb_otg_export_marker_path(config: AppConfig, *, state_dir: Path | None = None) -> Path:
    base_dir = (
        state_dir
        if state_dir is not None
        else (config.source_path.parent / config.gateway.data_dir)
    )
    return base_dir / "runtime" / "usb_otg_last_export.txt"


def mark_usb_otg_exported(
    *,
    config: AppConfig,
    state_dir: Path | None,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(tz=timezone.utc)
    marker = usb_otg_export_marker_path(config, state_dir=state_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(current.isoformat(), encoding="utf-8")
