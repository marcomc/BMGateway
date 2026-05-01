"""Frame preview and screenshot-ready page rendering."""

from __future__ import annotations

import html
from datetime import datetime, timedelta

from . import web_pages as shared
from .localization import localize_html
from .web_ui import (
    app_document,
    base_css,
    chart_card,
    chart_script,
    section_card,
    top_header,
)

FRAME_OVERVIEW_DEVICES_PER_PAGE = 3


def render_diagnostics_html(
    *,
    theme_preference: str = "system",
    fleet_trend_metrics: tuple[str, ...] = ("soc",),
    battery_overview_page_count: int = 1,
    language: str = "en",
) -> str:
    ordered_metrics = _ordered_fleet_metrics(fleet_trend_metrics)
    default_metric = ordered_metrics[0] if ordered_metrics else "soc"
    metric_links = "".join(
        (
            '<a class="secondary-button" '
            f'href="/frame/fleet-trend?metric={html.escape(metric)}" '
            'target="frame-preview-display">'
            f"Fleet Trend {_metric_label(metric)}</a>"
        )
        for metric in ordered_metrics
    )
    overview_links = "".join(
        (
            '<a class="secondary-button" '
            f'href="/frame/battery-overview?page={page_index}" '
            'target="frame-preview-display">'
            "<span>Battery Overview</span> "
            "<span>Page</span> "
            f"{page_index}</a>"
        )
        for page_index in range(1, max(1, battery_overview_page_count) + 1)
    )
    body = top_header(
        title="Diagnostics",
        right=(
            '<div class="hero-actions">'
            '<a class="secondary-button" href="/settings">Back to Settings</a>'
            "</div>"
        ),
    ) + section_card(
        title="Frame Preview",
        subtitle="Simulate the picture frame output from hidden USB OTG render pages.",
        body=(
            '<div class="frame-preview-tool">'
            '<div class="inline-actions">'
            f"{metric_links}"
            f"{overview_links}"
            "</div>"
            '<div class="frame-preview-shell">'
            '<iframe class="frame-preview-display" name="frame-preview-display" '
            f'src="/frame/fleet-trend?metric={html.escape(default_metric)}" '
            'aria-label="Frame Preview"></iframe>'
            "</div>"
            "</div>"
        ),
    )
    return app_document(
        title="Diagnostics",
        body=body,
        active_nav="settings",
        theme_preference=theme_preference,
        language=language,
    )


def _ordered_fleet_metrics(metrics: tuple[str, ...]) -> tuple[str, ...]:
    enabled = set(metrics)
    preferred_order = ("soc", "temperature", "voltage")
    return tuple(metric for metric in preferred_order if metric in enabled)


def render_frame_fleet_trend_html(
    *,
    chart_points: list[dict[str, object]],
    legend: list[tuple[str, str]],
    show_chart_markers: bool,
    appearance: str,
    default_chart_range: str,
    default_chart_metric: str,
    width: int,
    height: int,
    language: str = "en",
) -> str:
    chart_id = "frame-fleet-trend-chart"
    range_value = shared._sanitize_default_chart_range(default_chart_range)
    metric_value = (
        default_chart_metric if default_chart_metric in {"voltage", "soc", "temperature"} else "soc"
    )
    latest_timestamp, device_values = _fleet_trend_latest_values(
        chart_points=chart_points,
        legend=legend,
        metric=metric_value,
        range_value=range_value,
    )
    device_value_markup = "".join(
        (
            '<span class="frame-device-value" translate="no">'
            f'<span class="legend-swatch" style="background:{html.escape(color)}"></span>'
            f"{html.escape(label)} {html.escape(value)}"
            "</span>"
        )
        for label, color, value in device_values
    )
    body = (
        '<section class="frame-fleet-trend-section">'
        '<div class="frame-fleet-header">'
        '<h1 class="frame-title">'
        "<span>Fleet Trend</span>"
        f" · <span>{html.escape(_metric_label(metric_value))}</span>"
        f" · <span>{html.escape(_range_label(range_value))}</span>"
        f" · <span>Latest:</span> <span>{html.escape(latest_timestamp)}</span>"
        "</h1>"
        f'<div class="frame-device-values">{device_value_markup}</div>'
        "</div>"
        + chart_card(
            chart_id=chart_id,
            title="Fleet Trend",
            subtitle="",
            points=chart_points,
            range_options=shared._visible_chart_range_options(),
            default_range=range_value,
            default_metric=metric_value,
            legend=legend or [("No devices", "#95a3b8")],
            show_markers=show_chart_markers,
        ).replace(
            f'<div class="chart-frame" id="{chart_id}" ',
            f'<div class="chart-frame" id="{chart_id}" data-chart-compact="true" ',
            1,
        )
        + "</section>"
    )
    return _frame_document(
        title="Fleet Trend",
        body=body,
        script=chart_script(chart_id, language=language or "en"),
        appearance=appearance,
        width=width,
        height=height,
        language=language,
    )


def _metric_label(metric: str) -> str:
    return {
        "voltage": "Voltage",
        "soc": "SoC",
        "temperature": "Temperature",
    }.get(metric, metric)


def _range_label(range_value: str) -> str:
    return dict(shared._visible_chart_range_options()).get(range_value, range_value)


def _metric_value(value: object, metric: str) -> str:
    if not isinstance(value, int | float):
        return "--"
    if metric == "voltage":
        return f"{value:.2f}V"
    if metric == "temperature":
        return f"{value:.1f}°C"
    return f"{value:.0f}%"


def _parse_point_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _point_series_key(point: dict[str, object]) -> str:
    return str(point.get("series_id") or point.get("series") or "")


def _legend_series_keys(
    *,
    legend: list[tuple[str, str]],
    chart_points: list[dict[str, object]],
) -> list[tuple[str, str, str]]:
    keys_by_label: dict[str, list[str]] = {}
    for point in chart_points:
        label = str(point.get("series", ""))
        key = _point_series_key(point)
        if not label or not key:
            continue
        label_keys = keys_by_label.setdefault(label, [])
        if key not in label_keys:
            label_keys.append(key)

    consumed_by_label: dict[str, int] = {}
    output: list[tuple[str, str, str]] = []
    for label, color in legend:
        consumed = consumed_by_label.get(label, 0)
        candidates = keys_by_label.get(label, [])
        key = candidates[consumed] if consumed < len(candidates) else label
        consumed_by_label[label] = consumed + 1
        output.append((label, color, key))
    return output


def _fleet_trend_latest_values(
    *,
    chart_points: list[dict[str, object]],
    legend: list[tuple[str, str]],
    metric: str,
    range_value: str,
) -> tuple[str, list[tuple[str, str, str]]]:
    legend_keys = _legend_series_keys(legend=legend, chart_points=chart_points)
    timestamped_points = [
        (timestamp, point)
        for point in chart_points
        if (timestamp := _parse_point_timestamp(point.get("ts"))) is not None
    ]
    if not timestamped_points:
        return "No data", [(label, color, "--") for label, color, _key in legend_keys]

    newest = max(timestamp for timestamp, _point in timestamped_points)
    if range_value not in {"all", "raw"}:
        try:
            cutoff = newest - timedelta(days=int(range_value))
            timestamped_points = [
                (timestamp, point) for timestamp, point in timestamped_points if timestamp >= cutoff
            ]
        except ValueError:
            pass
    latest_by_series: dict[str, tuple[datetime, dict[str, object]]] = {}
    for timestamp, point in timestamped_points:
        series = _point_series_key(point)
        if not series:
            continue
        previous = latest_by_series.get(series)
        if previous is None or timestamp >= previous[0]:
            latest_by_series[series] = (timestamp, point)

    latest_timestamp = max(
        (timestamp for timestamp, _point in latest_by_series.values()),
        default=newest,
    ).strftime("%Y-%m-%d %H:%M")
    device_values = [
        (
            label,
            color,
            _metric_value(latest_by_series[key][1].get(metric), metric)
            if key in latest_by_series
            else "--",
        )
        for label, color, key in legend_keys
    ]
    return latest_timestamp, device_values


def render_frame_battery_overview_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    page: int,
    devices_per_page: int,
    appearance: str,
    width: int,
    height: int,
    language: str = "en",
) -> str:
    latest_timestamp = _battery_overview_latest_timestamp(snapshot)
    page_devices = _battery_overview_page_devices(
        snapshot=snapshot,
        devices=devices,
        page=page,
        devices_per_page=devices_per_page,
    )
    card_size = _overview_card_size_px(
        card_count=max(1, len(page_devices)),
        width=width,
        height=height,
    )
    grid_markup = _frame_battery_cards_html(
        devices=page_devices,
        card_size=card_size,
        width=width,
        height=height,
    )
    body = (
        '<section class="frame-overview-section">'
        '<h1 class="frame-title">'
        "<span>Battery Overview</span>"
        f" · <span>Latest:</span> <span>{html.escape(latest_timestamp)}</span>"
        "</h1>"
        f'<div class="frame-battery-stage" style="--frame-overview-card-size: {card_size}px;">'
        f"{grid_markup}"
        "</div>"
        "</section>"
    )
    return _frame_document(
        title="Battery Overview",
        body=body,
        script="",
        appearance=appearance,
        width=width,
        height=height,
        language=language,
    )


def frame_battery_overview_page_count(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    devices_per_page: int,
) -> int:
    return len(
        _battery_overview_pages(
            snapshot=snapshot,
            devices=devices,
            devices_per_page=devices_per_page,
        )
    )


def _battery_overview_page_devices(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    page: int,
    devices_per_page: int,
) -> list[dict[str, object]]:
    pages = _battery_overview_pages(
        snapshot=snapshot,
        devices=devices,
        devices_per_page=devices_per_page,
    )
    page_index = max(0, min(page - 1, len(pages) - 1))
    return pages[page_index]


def _battery_overview_pages(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    devices_per_page: int,
) -> list[list[dict[str, object]]]:
    snapshot_devices = snapshot.get("devices", [])
    snapshot_device_rows = snapshot_devices if isinstance(snapshot_devices, list) else []
    snapshot_by_id = {
        str(device.get("id", "")): device
        for device in snapshot_device_rows
        if isinstance(device, dict) and str(device.get("id", ""))
    }
    merged_devices = [
        {**snapshot_by_id.get(str(device.get("id", "")), {}), **device}
        for device in devices
        if isinstance(device, dict)
    ]
    if not merged_devices:
        merged_devices = [device for device in snapshot_device_rows if isinstance(device, dict)]
    enabled_devices = [device for device in merged_devices if bool(device.get("enabled", True))]
    if enabled_devices:
        merged_devices = enabled_devices
    if not merged_devices:
        return [[]]

    page_size = _effective_frame_overview_devices_per_page(devices_per_page)
    return [
        merged_devices[index : index + page_size]
        for index in range(0, len(merged_devices), page_size)
    ]


def _effective_frame_overview_devices_per_page(_configured_devices_per_page: int) -> int:
    return FRAME_OVERVIEW_DEVICES_PER_PAGE


def _frame_overview_layout_dimensions(card_count: int) -> tuple[int, int]:
    if card_count <= FRAME_OVERVIEW_DEVICES_PER_PAGE:
        return max(1, card_count), 1
    return shared._overview_layout_dimensions(card_count)


def _overview_card_size_px(
    *,
    card_count: int,
    width: int,
    height: int,
) -> int:
    columns, rows = _frame_overview_layout_dimensions(card_count)
    gap = 4
    frame_padding = 8
    title_and_gap = 18
    horizontal_space = max(1, width - frame_padding - ((columns - 1) * gap))
    vertical_space = max(1, height - frame_padding - title_and_gap - ((rows - 1) * gap))
    return max(1, int(min(horizontal_space / columns, vertical_space / rows)))


def _frame_battery_cards_html(
    *,
    devices: list[dict[str, object]],
    card_size: int,
    width: int,
    height: int,
) -> str:
    cards: list[str] = []
    columns, rows = _frame_overview_layout_dimensions(len(devices or [{}]))
    gap = 4
    top = 22
    frame_padding = 4
    horizontal_space = width - (frame_padding * 2)
    vertical_space = height - top - frame_padding
    cell_width = (horizontal_space - ((columns - 1) * gap)) / columns
    cell_height = (vertical_space - ((rows - 1) * gap)) / rows
    for index, device in enumerate(devices or [{}]):
        row = index // columns
        column = index % columns
        left = frame_padding + (column * (cell_width + gap)) + ((cell_width - card_size) / 2)
        card_top = top + (row * (cell_height + gap)) + ((cell_height - card_size) / 2)
        color = shared._device_accent_color(device, fallback_index=index)
        name = html.escape(str(device.get("name") or device.get("id") or "Battery"))
        context = html.escape(shared._vehicle_summary(device))
        meta = shared._battery_home_metadata_summary(device)
        meta_markup = (
            ""
            if meta == "Battery details not set"
            else f'<div class="frame-battery-meta">{html.escape(meta)}</div>'
        )
        soc_text = html.escape(shared._format_number(device.get("soc"), digits=0, suffix="%"))
        voltage_text = html.escape(
            shared._format_number(device.get("voltage"), digits=2, suffix="V")
        )
        temperature_text = html.escape(
            shared._format_number(device.get("temperature"), digits=1, suffix="°C")
        )
        status_markup = shared._battery_card_status_markup(device, inline=True)
        soc_value = shared._coerce_float(device.get("soc"), default=0.0)
        degrees = max(0.0, min(100.0, soc_value)) * 3.6
        cards.append(
            '<article class="frame-battery-card" '
            f'style="--card-accent: {html.escape(color)}; '
            f"--battery-degrees: {degrees:.1f}deg; "
            f"left: {left:.1f}px; top: {card_top:.1f}px; "
            f'width: {card_size}px; height: {card_size}px;">'
            '<div class="frame-battery-inner">'
            '<div class="frame-battery-copy">'
            f'<div class="frame-battery-name">{name}</div>'
            f'<div class="frame-battery-context">{context}</div>'
            f"{meta_markup}"
            "</div>"
            '<div class="frame-battery-center">'
            f'<div class="frame-battery-soc">{soc_text}</div>'
            f"{status_markup}"
            f'<div class="frame-battery-detail">{temperature_text}</div>'
            f'<div class="frame-battery-detail">{voltage_text}</div>'
            "</div>"
            "</div>"
            "</article>"
        )
    return '<div class="frame-battery-grid">' + "".join(cards) + "</div>"


def _battery_overview_latest_timestamp(snapshot: dict[str, object]) -> str:
    devices = snapshot.get("devices")
    timestamps: list[datetime] = []
    if isinstance(devices, list):
        for device in devices:
            if not isinstance(device, dict):
                continue
            timestamp = _parse_point_timestamp(device.get("last_seen"))
            if timestamp is not None:
                timestamps.append(timestamp)
    if not timestamps:
        generated_at = _parse_point_timestamp(snapshot.get("generated_at"))
        if generated_at is not None:
            timestamps.append(generated_at)
    if not timestamps:
        return "No data"
    return max(timestamps).strftime("%Y-%m-%d %H:%M")


def _frame_document(
    *,
    title: str,
    body: str,
    script: str,
    appearance: str,
    width: int,
    height: int,
    language: str = "en",
) -> str:
    safe_title = html.escape(title)
    theme_attr = html.escape(appearance)
    width = max(1, width)
    height = max(1, height)
    document = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width={width}, initial-scale=1">
    <title>{safe_title}</title>
    <style>
{base_css()}
      html,
      body {{
        width: {width}px;
        height: {height}px;
        margin: 0;
        overflow: hidden;
      }}
      body {{
        --frame-width: {width}px;
        --frame-height: {height}px;
        background: var(--bg-app);
      }}
      .frame-capture-root {{
        width: var(--frame-width);
        height: var(--frame-height);
        overflow: hidden;
        pointer-events: none;
      }}
      .frame-capture-root .chart-card,
      .frame-fleet-trend-section,
      .frame-overview-section {{
        width: var(--frame-width);
        height: var(--frame-height);
        box-sizing: border-box;
        margin: 0;
      }}
      .frame-capture-root .chart-card {{
        position: absolute;
        inset: 30px 0 0;
        min-height: 0;
        height: auto;
        padding: 0;
        border: 0;
        border-radius: 0;
        background: transparent;
      }}
      .frame-capture-root .chart-card-header,
      .frame-capture-root .chart-legend,
      .frame-capture-root .chart-nav-arrow,
      .frame-capture-root .chart-tooltip,
      .frame-capture-root .chart-meta {{
        display: none;
      }}
      .frame-capture-root .section-title {{
        font-size: 18px;
      }}
      .frame-capture-root .control-segment button {{
        min-height: 28px;
        padding: 0 10px;
        font-size: 12px;
      }}
      .frame-capture-root .chart-legend {{
        margin: 6px 0;
      }}
      .frame-capture-root .chart-frame-shell {{
        position: absolute;
        inset: 0;
        min-height: 0;
        height: 100%;
      }}
      .frame-capture-root .chart-frame {{
        position: absolute;
        inset: 0;
        height: auto;
        padding: 0;
        border: 0;
        border-radius: 0;
        background: transparent;
        cursor: default;
        overflow: hidden;
      }}
      .frame-capture-root .chart-canvas {{
        height: 100%;
      }}
      .frame-capture-root .chart-canvas svg {{
        width: 100%;
        height: 100%;
      }}
      .frame-overview-section {{
        position: relative;
        display: block;
        padding: 0;
        background: var(--bg-app);
      }}
      .frame-fleet-trend-section {{
        position: relative;
        display: block;
        padding: 0;
        background: var(--bg-app);
      }}
      .frame-title {{
        margin: 0 0 8px;
        font-size: 18px;
        line-height: 1.1;
      }}
      .frame-overview-section .frame-title {{
        position: absolute;
        top: 3px;
        left: 4px;
        z-index: 2;
        margin: 0;
        font-size: 12px;
      }}
      .frame-fleet-header {{
        position: absolute;
        top: 10px;
        right: 2px;
        left: 5px;
        z-index: 2;
        margin-bottom: 0;
        padding: 0;
      }}
      .frame-fleet-header .frame-title {{
        margin-bottom: 1px;
        font-size: 8px;
        line-height: 1.25;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .frame-device-values {{
        display: flex;
        flex-wrap: wrap;
        gap: 1px 5px;
        margin-top: 0;
        color: var(--text-primary);
        font-size: 8px;
        font-weight: 700;
      }}
      .frame-device-value {{
        display: inline-flex;
        align-items: center;
        gap: 2px;
      }}
      .frame-device-value .legend-swatch {{
        width: 7px;
        height: 7px;
      }}
      .frame-overview-page-window {{
        position: relative;
        overflow: visible;
        min-height: 0;
      }}
      .frame-battery-stage {{
        position: absolute;
        inset: 0;
      }}
      .frame-overview-page-window .home-overview-scroller,
      .frame-overview-page-window .home-overview-page {{
        height: 100%;
      }}
      .frame-battery-grid {{
        position: absolute;
        inset: 0;
      }}
      .frame-battery-card {{
        position: absolute;
        border-radius: 50%;
        background:
          conic-gradient(
            var(--card-accent) 0deg var(--battery-degrees),
            rgba(191, 207, 198, 0.55) var(--battery-degrees) 360deg
          );
        box-shadow:
          0 0 28px color-mix(in srgb, var(--card-accent) 20%, transparent),
          0 10px 22px color-mix(in srgb, var(--card-accent) 14%, transparent);
        overflow: hidden;
      }}
      .frame-battery-card::after {{
        content: "";
        position: absolute;
        inset: 12%;
        border-radius: 50%;
        background: radial-gradient(
          circle at 30% 24%,
          color-mix(in srgb, var(--card-accent) 28%, var(--gauge-inner-start)) 0%,
          color-mix(in srgb, var(--card-accent) 14%, var(--gauge-inner-mid)) 48%,
          var(--gauge-inner-ring) 68%,
          var(--gauge-inner-end) 100%
        );
      }}
      .frame-battery-inner {{
        position: absolute;
        inset: 0;
        z-index: 1;
        display: grid;
        grid-template-rows: auto 1fr;
        padding: 14%;
        color: var(--gauge-text-strong);
      }}
      .frame-battery-copy {{
        min-width: 0;
      }}
      .frame-battery-name {{
        overflow: hidden;
        color: var(--text-primary);
        font-size: 10px;
        font-weight: 800;
        line-height: 1.02;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .frame-battery-context,
      .frame-battery-meta {{
        overflow: hidden;
        color: var(--text-secondary);
        font-size: 7px;
        font-weight: 700;
        line-height: 1.08;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .frame-battery-center {{
        display: flex;
        min-height: 0;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding-top: 4px;
        text-align: center;
      }}
      .frame-battery-soc {{
        font-size: 32px;
        font-weight: 800;
        line-height: 0.95;
      }}
      .frame-battery-center .battery-card-status-inline {{
        font-size: 7px;
        font-weight: 800;
        line-height: 1.1;
      }}
      .frame-battery-detail {{
        color: var(--gauge-text-soft);
        font-size: 9px;
        font-weight: 800;
        line-height: 1.05;
      }}
      .frame-overview-page-window .home-overview-page,
      .frame-overview-page-window .home-overview-page.is-single-page,
      .frame-overview-page-window .home-overview-page.is-single-page.page-two-cards,
      .frame-overview-page-window .home-overview-page.is-single-page.page-one-card,
      .frame-overview-page-window .home-overview-page.page-multi-cards {{
        width: 100%;
        grid-template-columns: repeat(var(--overview-columns), minmax(0, 1fr));
        grid-template-rows: repeat(var(--overview-rows), minmax(0, 1fr));
        align-items: center;
        justify-items: center;
        gap: 4px;
        margin: 0;
      }}
      .frame-overview-page-window .home-overview-card {{
        width: var(--frame-overview-card-size);
        height: var(--frame-overview-card-size);
        max-width: 100%;
        align-self: center;
        justify-self: center;
      }}
      .frame-overview-page-window .home-overview-card-link {{
        overflow: visible;
      }}
      .frame-overview-page-window .home-overview-orb .battery-card-gauge {{
        width: calc(var(--frame-overview-card-size) - 8px);
        height: calc(var(--frame-overview-card-size) - 8px);
        max-width: 100%;
        max-height: 100%;
      }}
      .frame-overview-page-window .home-orb-layout {{
        padding: 12%;
        font-size: 0.82rem;
      }}
      .frame-overview-page-window .home-overview-scroller {{
        transform: translateX(calc(var(--frame-page-index) * -100%));
      }}
    </style>
  </head>
  <body data-theme-preference="{theme_attr}">
    <main class="frame-capture-root">{body}</main>
    {script}
  </body>
</html>
"""
    return localize_html(document, language)
