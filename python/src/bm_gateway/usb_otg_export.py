"""USB OTG picture-frame image export support."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, SupportsFloat, SupportsIndex, cast

from PIL import Image, ImageDraw, ImageFont

from .config import AppConfig
from .device_registry import COLOR_CATALOG, Device
from .models import DeviceReading, GatewaySnapshot
from .state_store import fetch_recent_history
from .web_pages import DEVICE_COLOR_HEX

DriveCommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class USBOTGExportResult:
    exported: bool
    reason: str
    files: tuple[Path, ...] = ()


LIGHT_PALETTE = {
    "bg": "#e9edf3",
    "surface": "#ffffff",
    "surface_soft": "#f6f9fd",
    "chart": "#f7f9fc",
    "border": "#d7e0ea",
    "text": "#111827",
    "muted": "#526071",
    "soft": "#8995a6",
    "grid": "#c4cfdc",
    "ok": "#17c45a",
    "error": "#ef4444",
    "offline": "#95a3b8",
}

DARK_PALETTE = {
    "bg": "#111214",
    "surface": "#1c1c1e",
    "surface_soft": "#242428",
    "chart": "#16181d",
    "border": "#545458",
    "text": "#f5f5f7",
    "muted": "#c6c6d0",
    "soft": "#858591",
    "grid": "#525b68",
    "ok": "#48de89",
    "error": "#ff7a7f",
    "offline": "#9aa7bb",
}


def effective_refresh_interval_seconds(config: AppConfig) -> int:
    if config.usb_otg.refresh_interval_seconds > 0:
        return config.usb_otg.refresh_interval_seconds
    return config.gateway.poll_interval_seconds


def _palette(config: AppConfig) -> dict[str, str]:
    return DARK_PALETTE if config.usb_otg.appearance == "dark" else LIGHT_PALETTE


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists() and (bold == ("Bold" in candidate) or not bold):
            try:
                return ImageFont.truetype(candidate, size=size)
            except (ImportError, OSError):
                continue
    return ImageFont.load_default()


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    *,
    fill: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int | None = None,
) -> None:
    text = value
    if max_width is not None:
        ellipsis = "..."
        while text and draw.textlength(text, font=font) > max_width:
            text = text[:-1]
        if text != value:
            while text and draw.textlength(text + ellipsis, font=font) > max_width:
                text = text[:-1]
            text = text + ellipsis if text else ellipsis
    draw.text(xy, text, fill=fill, font=font)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    clean = value.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def _mix(color: str, background: str, amount: float) -> str:
    c1 = _hex_to_rgb(color)
    c2 = _hex_to_rgb(background)
    mixed = tuple(
        round((channel * amount) + (base * (1 - amount)))
        for channel, base in zip(c1, c2, strict=True)
    )
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def _device_color(device: Device, index: int) -> str:
    if device.color_key in COLOR_CATALOG:
        return DEVICE_COLOR_HEX[device.color_key]
    keys = tuple(COLOR_CATALOG)
    return DEVICE_COLOR_HEX[keys[index % len(keys)]]


def _snapshot_by_id(snapshot: GatewaySnapshot) -> dict[str, DeviceReading]:
    return {reading.id: reading for reading in snapshot.devices}


def _format_temp(reading: DeviceReading | None) -> str:
    if reading is None or reading.temperature is None:
        return "--"
    return f"{reading.temperature:.1f}C"


def _save(image: Image.Image, path: Path, image_format: str) -> None:
    if image_format == "jpeg":
        image.convert("RGB").save(path, format="JPEG", quality=92, optimize=True)
    elif image_format == "png":
        image.save(path, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(path, format="BMP")


def _extension(image_format: str) -> str:
    return "jpg" if image_format == "jpeg" else image_format


def render_battery_overview_images(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    output_dir: Path,
) -> tuple[Path, ...]:
    palette = _palette(config)
    width = config.usb_otg.image_width_px
    height = config.usb_otg.image_height_px
    per_image = config.usb_otg.overview_devices_per_image
    snapshot_devices = _snapshot_by_id(snapshot)
    real_devices = [device for device in devices if device.enabled]
    if not real_devices:
        real_devices = devices
    pages = [
        real_devices[index : index + per_image] for index in range(0, len(real_devices), per_image)
    ]
    pages = pages or [[]]
    files: list[Path] = []
    title_font = _font(max(13, height // 16), bold=True)
    small_font = _font(max(8, height // 30))
    label_font = _font(max(9, height // 26), bold=True)
    value_font = _font(max(15, height // 10), bold=True)
    metric_font = _font(max(8, height // 34), bold=True)

    for page_index, page_devices in enumerate(pages, start=1):
        image = Image.new("RGB", (width, height), palette["bg"])
        draw = ImageDraw.Draw(image)
        margin = max(8, width // 40)
        header_h = max(26, height // 8)
        _text(draw, (margin, margin - 1), "Battery Overview", fill=palette["text"], font=title_font)
        _text(
            draw,
            (margin, margin + max(13, height // 17)),
            snapshot.generated_at.replace("T", " ")[:19],
            fill=palette["muted"],
            font=small_font,
        )
        if len(pages) > 1:
            page_label = f"{page_index}/{len(pages)}"
            label_w = int(draw.textlength(page_label, font=small_font))
            _text(
                draw,
                (width - margin - label_w, margin + max(13, height // 17)),
                page_label,
                fill=palette["muted"],
                font=small_font,
            )

        count = len(page_devices)
        rows = 2 if count > 5 else 1
        cols = max(1, min(5, (count + rows - 1) // rows))
        gap = max(5, width // 80)
        grid_top = header_h
        card_w = (width - margin * 2 - gap * (cols - 1)) // cols
        card_h = (height - grid_top - margin - gap * (rows - 1)) // rows

        for index, device in enumerate(page_devices):
            row = index // cols
            col = index % cols
            left = margin + col * (card_w + gap)
            top = grid_top + row * (card_h + gap)
            right = left + card_w
            bottom = top + card_h
            accent = _device_color(device, index)
            reading = snapshot_devices.get(device.id)
            connected = bool(reading and reading.connected)
            state_color = palette["ok"] if connected else palette["offline"]
            card_fill = _mix(accent, palette["surface"], 0.12)
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=8,
                fill=card_fill,
                outline=_mix(accent, palette["border"], 0.42),
                width=1,
            )
            draw.rounded_rectangle((left + 1, top + 1, right - 1, top + 5), radius=4, fill=accent)
            _text(
                draw,
                (left + 6, top + 9),
                device.name,
                fill=palette["text"],
                font=label_font,
                max_width=card_w - 12,
            )
            _text(
                draw,
                (left + 6, top + 22),
                "online" if connected else (reading.state if reading else "waiting"),
                fill=state_color,
                font=small_font,
                max_width=card_w - 12,
            )
            soc = f"{reading.soc}%" if reading else "--%"
            voltage = f"{reading.voltage:.2f}V" if reading else "-- V"
            soc_w = int(draw.textlength(soc, font=value_font))
            _text(
                draw,
                (left + (card_w - soc_w) // 2, top + max(35, card_h // 2 - 6)),
                soc,
                fill=accent,
                font=value_font,
            )
            metric_y = bottom - max(16, card_h // 5)
            _text(draw, (left + 7, metric_y), voltage, fill=palette["text"], font=metric_font)
            temp = _format_temp(reading)
            temp_w = int(draw.textlength(temp, font=metric_font))
            _text(
                draw,
                (right - 7 - temp_w, metric_y),
                temp,
                fill=palette["muted"],
                font=metric_font,
            )

        path = output_dir / (
            f"battery-overview-{page_index:02d}.{_extension(config.usb_otg.image_format)}"
        )
        _save(image, path, config.usb_otg.image_format)
        files.append(path)
    return tuple(files)


def _series_points(rows: Iterable[dict[str, object]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index, row in enumerate(rows):
        soc = row.get("soc")
        if soc is None:
            soc = row.get("avg_soc")
        try:
            value = float(cast(str | SupportsFloat | SupportsIndex, soc))
        except (TypeError, ValueError):
            continue
        points.append((float(index), max(0.0, min(100.0, value))))
    return points


def render_fleet_trend_image(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    database_path: Path,
    output_dir: Path,
) -> Path:
    palette = _palette(config)
    width = config.usb_otg.image_width_px
    height = config.usb_otg.image_height_px
    image = Image.new("RGB", (width, height), palette["bg"])
    draw = ImageDraw.Draw(image)
    margin = max(8, width // 40)
    title_font = _font(max(13, height // 16), bold=True)
    small_font = _font(max(8, height // 30))
    _text(draw, (margin, margin - 1), "Fleet Trend", fill=palette["text"], font=title_font)
    _text(
        draw,
        (margin, margin + max(13, height // 17)),
        "State of charge across all monitored batteries",
        fill=palette["muted"],
        font=small_font,
        max_width=width - margin * 2,
    )
    chart_left = margin + 4
    chart_top = max(42, height // 5)
    chart_right = width - margin - 4
    chart_bottom = height - max(32, height // 7)
    draw.rounded_rectangle(
        (chart_left, chart_top, chart_right, chart_bottom),
        radius=8,
        fill=palette["chart"],
        outline=palette["border"],
    )
    for step in range(1, 4):
        y = chart_top + (chart_bottom - chart_top) * step // 4
        draw.line((chart_left + 6, y, chart_right - 6, y), fill=palette["grid"], width=1)

    enabled_devices = [device for device in devices if device.enabled] or devices
    snapshot_by_id = _snapshot_by_id(snapshot)
    for index, device in enumerate(enabled_devices):
        rows = fetch_recent_history(database_path, device_id=device.id, limit=80)
        points = _series_points(rows)
        if not points and device.id in snapshot_by_id:
            points = [(0.0, float(snapshot_by_id[device.id].soc))]
        if not points:
            continue
        accent = _device_color(device, index)
        max_x = max(point[0] for point in points) or 1.0
        coords = [
            (
                chart_left + 8 + round((chart_right - chart_left - 16) * (x / max_x)),
                chart_bottom - 8 - round((chart_bottom - chart_top - 16) * (y / 100.0)),
            )
            for x, y in points
        ]
        if len(coords) == 1:
            x, y = coords[0]
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=accent)
        else:
            draw.line(coords, fill=accent, width=2, joint="curve")

    legend_y = chart_bottom + 8
    legend_x = margin
    for index, device in enumerate(enabled_devices[:8]):
        accent = _device_color(device, index)
        draw.rounded_rectangle(
            (legend_x, legend_y + 3, legend_x + 8, legend_y + 11),
            radius=4,
            fill=accent,
        )
        _text(
            draw,
            (legend_x + 12, legend_y),
            device.name,
            fill=palette["muted"],
            font=small_font,
            max_width=max(40, width // 4),
        )
        legend_x += min(width // 3, 12 + int(draw.textlength(device.name, font=small_font)) + 16)
        if legend_x > width - margin - 40:
            break

    path = output_dir / f"fleet-trend.{_extension(config.usb_otg.image_format)}"
    _save(image, path, config.usb_otg.image_format)
    return path


def render_usb_otg_export_images(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    database_path: Path,
    output_dir: Path,
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    if config.usb_otg.export_battery_overview:
        files.extend(
            render_battery_overview_images(
                config=config,
                devices=devices,
                snapshot=snapshot,
                output_dir=output_dir,
            )
        )
    if config.usb_otg.export_fleet_trend:
        files.append(
            render_fleet_trend_image(
                config=config,
                devices=devices,
                snapshot=snapshot,
                database_path=database_path,
                output_dir=output_dir,
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
) -> USBOTGExportResult:
    if not config.usb_otg.enabled:
        return USBOTGExportResult(exported=False, reason="disabled")
    if not config.usb_otg.export_battery_overview and not config.usb_otg.export_fleet_trend:
        return USBOTGExportResult(exported=False, reason="no images enabled")
    with tempfile.TemporaryDirectory(prefix="bm-gateway-usb-otg-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        files = render_usb_otg_export_images(
            config=config,
            devices=devices,
            snapshot=snapshot,
            database_path=database_path,
            output_dir=temp_dir,
        )
        _prepare_source_dir_for_root_helper(temp_dir, files)
        completed = runner(build_drive_export_command(config, temp_dir))
        if completed.returncode != 0:
            reason = completed.stderr.strip() or completed.stdout.strip() or "drive helper failed"
            return USBOTGExportResult(exported=False, reason=reason, files=files)
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
    return (current - previous).total_seconds() >= effective_refresh_interval_seconds(config)


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
