"""Reusable server-rendered UI primitives for the BMGateway web interface."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
from typing import Iterable

from .localization import localize_html
from .web_assets import chart_script_source, web_css_source


def _join_classes(*values: str) -> str:
    return " ".join(value for value in values if value)


def app_document(
    *,
    title: str,
    body: str,
    active_nav: str = "home",
    primary_device_id: str = "",
    version_label: str = "",
    theme_preference: str = "",
    head_extra: str = "",
    script: str = "",
    language: str = "en",
) -> str:
    theme_attr = (
        f' data-theme-preference="{html.escape(theme_preference)}"' if theme_preference else ""
    )
    icon_links = """<link rel="icon" href="/favicon.png" sizes="32x32" type="image/png">
    <link rel="icon" href="/favicon.svg" type="image/svg+xml">
    <link rel="apple-touch-icon" href="/apple-touch-icon.png">
    <link rel="manifest" href="/site.webmanifest">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">"""
    document = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    {icon_links}
    <style>
{base_css()}
    </style>
    {head_extra}
  </head>
  <body{theme_attr}>
    <div class="app-shell">
      <a class="skip-link" href="#main-content">Skip to main content</a>
      <main class="page-shell" id="main-content">
        {body}
      </main>
      {bottom_nav(active_nav, primary_device_id=primary_device_id)}
    </div>
    {script}
  </body>
</html>
"""
    return localize_html(document, language)


def base_css() -> str:
    return web_css_source()


def top_header(
    *,
    title: str,
    subtitle: str = "",
    subtitle_lines: Iterable[str] | None = None,
    eyebrow: str = "",
    right: str = "",
) -> str:
    subtitle_markup = ""
    lines = [line.strip() for line in (subtitle_lines or ()) if line and line.strip()]
    if not lines and subtitle:
        lines = [subtitle.strip()]
    if lines:
        subtitle_markup = "".join(
            f'<div class="header-subtitle-line">{html.escape(line)}</div>' for line in lines
        )
        subtitle_markup = f'<div class="header-subtitles">{subtitle_markup}</div>'
    return (
        '<header class="top-header"><div>'
        f"<h1>{html.escape(title)}</h1>"
        f"{subtitle_markup}"
        f"</div>{right}</header>"
    )


def section_card(
    *,
    title: str = "",
    subtitle: str = "",
    body: str,
    right: str = "",
    classes: str = "",
) -> str:
    if title:
        subtitle_html = (
            f'<div class="section-subtitle">{html.escape(subtitle)}</div>' if subtitle else ""
        )
        header = (
            '<div class="section-title-row">'
            "<div>"
            f'<h2 class="section-title">{html.escape(title)}</h2>'
            f"{subtitle_html}"
            "</div>"
            f"{right}</div>"
        )
    else:
        header = ""
    return f'<section class="{_join_classes("section-card", classes)}">{header}{body}</section>'


def summary_card(label: str, value: str, *, subvalue: str = "", classes: str = "") -> str:
    subvalue_html = f'<div class="subvalue">{html.escape(subvalue)}</div>' if subvalue else ""
    return (
        f'<div class="{_join_classes("summary-card", classes)}">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        f"{subvalue_html}"
        "</div>"
    )


def metric_tile(
    *,
    label: str,
    value: str,
    tone: str = "blue",
    subvalue: str = "",
    detail_html: str = "",
) -> str:
    subvalue_html = f'<div class="subvalue">{html.escape(subvalue)}</div>' if subvalue else ""
    return (
        f'<div class="metric-tile {html.escape(tone)}">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        f"{detail_html}"
        f"{subvalue_html}"
        "</div>"
    )


def status_badge(label: str, *, kind: str) -> str:
    return f'<span class="status-badge {html.escape(kind)}">{html.escape(label)}</span>'


def api_chip(label: str) -> str:
    return f'<span class="api-chip">{html.escape(label)}</span>'


def button(label: str, *, kind: str = "primary", button_type: str = "submit") -> str:
    class_name = {
        "primary": "primary-button",
        "secondary": "secondary-button",
        "ghost": "ghost-button",
    }[kind]
    return f'<button class="{class_name}" type="{html.escape(button_type)}">{html.escape(label)}</button>'


def settings_row(label: str, value: str) -> str:
    return (
        '<div class="settings-row">'
        f'<div class="settings-label">{html.escape(label)}</div>'
        f'<div class="settings-value">{html.escape(value)}</div>'
        "</div>"
    )


def settings_control_row(label: str, control_html: str, *, help_text: str = "") -> str:
    help_markup = (
        f'<div class="inline-field-help">{html.escape(help_text)}</div>' if help_text else ""
    )
    return (
        '<div class="settings-row">'
        f'<div class="settings-label">{html.escape(label)}</div>'
        f'<div class="settings-control">{control_html}{help_markup}</div>'
        "</div>"
    )


def banner_strip(message: str, *, kind: str = "warning", trailing: str = "") -> str:
    return (
        f'<div class="banner-strip {html.escape(kind)}" role="status" aria-live="polite">'
        f"<div>{message}</div>{trailing}</div>"
    )


def tone_card(body: str, *, tone: str, extra_class: str = "", style: str = "") -> str:
    class_name = _join_classes("tone-card", html.escape(tone), extra_class)
    style_attr = f' style="{html.escape(style)}"' if style else ""
    return f'<article class="{class_name}"{style_attr}>{body}</article>'


def device_icon(icon_key: str, *, label: str, frame_class: str = "") -> str:
    safe_key = html.escape(icon_key)
    safe_label = html.escape(label)
    class_name = _join_classes("device-icon-frame", frame_class)
    return (
        f'<div class="{class_name}" data-icon-key="{safe_key}" aria-hidden="true">'
        f"{_device_icon_svg(icon_key, label=safe_label)}"
        "</div>"
    )


def icon_picker_option(icon_key: str, *, label: str, checked: bool = False) -> str:
    checked_attr = " checked" if checked else ""
    safe_key = html.escape(icon_key)
    safe_label = html.escape(label)
    return (
        '<label class="icon-picker-card">'
        f'<input type="radio" name="icon_key" value="{safe_key}"{checked_attr}>'
        '<span class="icon-picker-surface">'
        f"{device_icon(icon_key, label=label)}"
        f'<span class="icon-picker-label">{safe_label}</span>'
        "</span>"
        "</label>"
    )


def _device_icon_svg(icon_key: str, *, label: str) -> str:
    title = f"<title>{label}</title>"
    if icon_key in {"car_12v", "vehicle_car"}:
        content = """
<path class="stroke-main" d="M14 38h36l-3-9c-.7-2.2-2.7-3.6-5-3.6H22c-2.3 0-4.3 1.4-5 3.6z"/>
<path class="stroke-main" d="M12 38h40v7H12z"/>
<circle class="fill-main" cx="21" cy="45" r="4.5"/>
<circle class="fill-main" cx="43" cy="45" r="4.5"/>
<path class="stroke-accent" d="M31 18v9m-4.5-4.5h9"/>
"""
    elif icon_key in {"motorcycle_12v", "vehicle_motorcycle"}:
        content = """
<circle class="fill-main" cx="20" cy="44" r="6"/>
<circle class="fill-main" cx="45" cy="44" r="6"/>
<path class="stroke-main" d="M20 44h10l6-10h7"/>
<path class="stroke-main" d="M32 34h-6l-5-7h7l4 7"/>
<path class="stroke-main" d="M42 26h6"/>
<path class="stroke-accent" d="M46 18v8m-4-4h8"/>
"""
    elif icon_key == "vehicle_scooter":
        content = """
<circle class="fill-main" cx="22" cy="44" r="5.5"/>
<circle class="fill-main" cx="44" cy="44" r="5.5"/>
<path class="stroke-main" d="M21 44h11l6-11h7"/>
<path class="stroke-main" d="M32 33h-7l-4-7h10l3 7"/>
<path class="stroke-main" d="M37 24h7"/>
<path class="stroke-accent" d="M44 18v8m-4-4h8"/>
"""
    elif icon_key == "vehicle_electric_bike":
        content = """
<circle class="fill-main" cx="19" cy="44" r="6"/>
<circle class="fill-main" cx="45" cy="44" r="6"/>
<path class="stroke-main" d="M19 44h11l6-12h8"/>
<path class="stroke-main" d="M31 32h-8l-4-6h7l5 6z"/>
<path class="stroke-main" d="M38 26h5"/>
<path class="stroke-accent" d="M45 16v8m-4-4h8"/>
"""
    elif icon_key == "vehicle_van":
        content = """
<path class="stroke-main" d="M12 39h40v7H12z"/>
<path class="stroke-main" d="M14 39V28h19v11"/>
<path class="stroke-main" d="M33 39V30h9l5 5v4"/>
<circle class="fill-main" cx="22" cy="46" r="4.5"/>
<circle class="fill-main" cx="43" cy="46" r="4.5"/>
"""
    elif icon_key == "vehicle_camper":
        content = """
<path class="stroke-main" d="M10 40h44v6H10z"/>
<path class="stroke-main" d="M14 40V26h20v14"/>
<path class="stroke-main" d="M34 40V30h10l6 6v4"/>
<circle class="fill-main" cx="21" cy="46" r="4.5"/>
<circle class="fill-main" cx="44" cy="46" r="4.5"/>
<path class="stroke-accent" d="M23 30h8"/>
"""
    elif icon_key == "vehicle_truck":
        content = """
<path class="stroke-main" d="M10 40h44v6H10z"/>
<path class="stroke-main" d="M12 40V26h24v14"/>
<path class="stroke-main" d="M36 40V30h9l7 7v3"/>
<circle class="fill-main" cx="20" cy="46" r="4.5"/>
<circle class="fill-main" cx="36" cy="46" r="4.5"/>
<circle class="fill-main" cx="47" cy="46" r="4.5"/>
"""
    elif icon_key == "vehicle_bus":
        content = """
<rect class="stroke-main" x="11" y="22" width="42" height="20" rx="4"/>
<path class="stroke-main" d="M17 22v-4h30v4"/>
<path class="stroke-main" d="M18 30h28"/>
<circle class="fill-main" cx="21" cy="46" r="4.5"/>
<circle class="fill-main" cx="43" cy="46" r="4.5"/>
"""
    elif icon_key == "vehicle_boat":
        content = """
<path class="stroke-main" d="M18 37h28l-6 8H24z"/>
<path class="stroke-main" d="M30 20v17"/>
<path class="stroke-main" d="M30 20l8 6h-8"/>
<path class="stroke-accent" d="M18 48c3-2 6-2 9 0 3-2 6-2 9 0 3-2 6-2 9 0"/>
"""
    elif icon_key == "vehicle_tractor":
        content = """
<circle class="fill-main" cx="20" cy="44" r="8"/>
<circle class="fill-main" cx="44" cy="45" r="4.5"/>
<path class="stroke-main" d="M20 44h15l5-9h8"/>
<path class="stroke-main" d="M31 35V24h10v11"/>
<path class="stroke-main" d="M24 32h7"/>
"""
    elif icon_key == "vehicle_atv":
        content = """
<circle class="fill-main" cx="19" cy="44" r="5"/>
<circle class="fill-main" cx="45" cy="44" r="5"/>
<path class="stroke-main" d="M19 44h12l5-9h9"/>
<path class="stroke-main" d="M31 35h-8l-3-6h9l4 6"/>
<path class="stroke-accent" d="M44 18v8m-4-4h8"/>
"""
    elif icon_key == "vehicle_machinery":
        content = """
<rect class="stroke-main" x="18" y="26" width="20" height="13" rx="2"/>
<path class="stroke-main" d="M38 31h8l6 7"/>
<circle class="fill-main" cx="23" cy="45" r="5"/>
<circle class="fill-main" cx="44" cy="45" r="7"/>
<path class="stroke-main" d="M18 39h25"/>
"""
    elif icon_key == "vehicle_other":
        content = """
<rect class="fill-main" x="17" y="17" width="30" height="30" rx="10"/>
<path class="stroke-main" d="M32 24v10"/>
<circle class="fill-accent" cx="32" cy="40" r="2.2"/>
"""
    elif icon_key == "lead_acid_battery":
        content = """
<rect class="fill-main" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M22 33c3.5-4 6.5-4 10 0s6.5 4 10 0"/>
<path class="stroke-accent" d="M32 26v14"/>
"""
    elif icon_key == "agm_battery":
        content = """
<rect class="fill-main" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M24 39l8-13 8 13h-16z"/>
<path class="stroke-accent" d="M32 29v6"/>
"""
    elif icon_key == "efb_battery":
        content = """
<rect class="fill-main" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M22 29h20M22 35h20M22 41h20"/>
<path class="stroke-accent" d="M27 24v5"/>
"""
    elif icon_key == "gel_battery":
        content = """
<rect class="fill-main" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="fill-accent" d="M32 25c-3 4-5 7-5 10.2A5 5 0 0037 35c0-3.2-2-6.2-5-10z"/>
"""
    elif icon_key == "lithium_battery":
        content = """
<rect class="fill-main" x="20" y="12" width="24" height="40" rx="8"/>
<path class="stroke-main" d="M28 12V8h8v4"/>
<path class="stroke-accent" d="M34 22l-5 9h4l-3 10 8-12h-4l4-7z"/>
"""
    elif icon_key == "custom_battery":
        content = """
<rect class="fill-main" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M21 39c5-7 8-5 11-8s5-4 11-4"/>
<circle class="fill-accent" cx="24" cy="35" r="2.5"/>
<circle class="fill-accent" cx="33" cy="31" r="2.5"/>
<circle class="fill-accent" cx="42" cy="27" r="2.5"/>
"""
    else:
        content = """
<rect class="fill-main" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M24 32h16"/>
<path class="stroke-accent" d="M32 24v16"/>
"""
    return (
        '<svg class="device-icon-svg" viewBox="0 0 64 64" fill="none" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="'
        f"{label}"
        '">'
        f"{title}{content}</svg>"
    )


def bottom_nav(active_nav: str, *, primary_device_id: str = "") -> str:
    history_href = "/history"
    if primary_device_id:
        history_href = f"/history?device_id={html.escape(primary_device_id)}"
    items = [
        ("home", "/", "Home"),
        ("history", history_href, "History"),
        ("devices", "/devices", "Devices"),
        ("settings", "/settings", "Settings"),
    ]
    links = []
    for item_id, href, label in items:
        classes = "nav-link active" if active_nav == item_id else "nav-link"
        current = ' aria-current="page"' if active_nav == item_id else ""
        links.append(
            f'<a class="{classes}" href="{href}"{current}>'
            f"{_nav_icon(item_id, label=label)}"
            f'<span class="nav-label">{html.escape(label)}</span>'
            "</a>"
        )
    return (
        '<nav class="bottom-nav" aria-label="Primary">'
        f'<div class="bottom-nav-inner">{"".join(links)}</div></nav>'
    )


def _nav_icon(item_id: str, *, label: str) -> str:
    if item_id == "home":
        body = """
<rect class="fill-main" x="6" y="8" width="12" height="10" rx="2.2"/>
<path class="stroke-main" d="M10 8V6h4v2m-2 2v6"/>
<path class="stroke-main" d="M15 10h4v6a2 2 0 01-2 2h-2"/>
"""
    elif item_id == "history":
        body = """
<path class="stroke-main" d="M5 18h14"/>
<path class="stroke-main" d="M7 18V7h10v11"/>
<path class="stroke-main" d="M9 14l2-2 2 1 3-4"/>
"""
    elif item_id == "devices":
        body = """
<rect class="stroke-main" x="5.5" y="6.5" width="14" height="3.5" rx="1.2"/>
<rect class="stroke-main" x="5.5" y="11.5" width="14" height="3.5" rx="1.2"/>
<rect class="stroke-main" x="5.5" y="16.5" width="14" height="3.5" rx="1.2"/>
"""
    else:
        body = """
<circle class="stroke-main" cx="12" cy="12" r="3.5"/>
<path class="stroke-main" d="M12 4.5v2.2m0 10.6v2.2M4.5 12h2.2m10.6 0h2.2M6.9 6.9l1.6 1.6m7 7l1.6 1.6m0-10.2l-1.6 1.6m-7 7l-1.6 1.6"/>
"""
    return (
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-hidden="true">'
        f"<title>{html.escape(label)}</title>{body}</svg>"
    )


def chart_card(
    *,
    chart_id: str,
    title: str,
    subtitle: str,
    points: list[dict[str, object]],
    range_options: Iterable[tuple[str, str]],
    default_range: str,
    default_metric: str,
    legend: list[tuple[str, str]],
    show_markers: bool = False,
) -> str:
    points_json = html.escape(json.dumps(points, separators=(",", ":")))
    legend_html = "".join(
        '<button type="button" class="legend-item active" '
        f'data-series-label="{html.escape(label)}" aria-pressed="true">'
        f'<span class="legend-swatch" style="background:{html.escape(color)}"></span>'
        f'<span class="legend-label">{html.escape(label)}</span>'
        "</button>"
        for label, color in legend
    )
    range_buttons = "".join(
        (
            f'<button type="button" data-range="{html.escape(value)}" '
            f'data-range-label="{html.escape(label)}" '
            f'class="{"active" if value == default_range else ""}">'
            f"{html.escape(label)}</button>"
        )
        for value, label in range_options
    )
    metric_buttons = "".join(
        (
            f'<button type="button" data-metric="{html.escape(value)}" '
            f'class="{"active" if value == default_metric else ""}">'
            f"{html.escape(label)}"
            "</button>"
        )
        for value, label in (
            ("voltage", "Voltage"),
            ("soc", "SoC"),
            ("temperature", "Temperature"),
        )
    )
    subtitle_html = (
        f'<div class="section-subtitle">{html.escape(subtitle)}</div>' if subtitle else ""
    )
    return (
        '<section class="chart-card">'
        '<div class="chart-card-header">'
        '<div class="section-title-row chart-title-row">'
        '<div class="chart-title-block">'
        f'<h2 class="section-title">{html.escape(title)}</h2>'
        f"{subtitle_html}"
        "</div>"
        '<div class="control-rail chart-metric-rail">'
        f'<div class="control-segment tab-strip">{metric_buttons}</div>'
        "</div>"
        "</div>"
        '<div class="control-rail chart-range-rail">'
        f'<div class="control-segment range-strip">{range_buttons}</div>'
        "</div>"
        "</div>"
        f'<div class="chart-legend">{legend_html}</div>'
        '<div class="chart-frame-shell">'
        f'<button type="button" class="chart-nav-arrow previous" '
        f'data-chart-nav="previous" data-chart-id="{html.escape(chart_id)}" '
        'aria-label="Show previous range">‹</button>'
        f'<div class="chart-frame" id="{html.escape(chart_id)}" '
        f'data-chart-points="{points_json}" '
        f'data-show-markers="{str(show_markers).lower()}">'
        '<div class="chart-canvas"></div>'
        '<div class="chart-tooltip" aria-hidden="true"></div>'
        "</div>"
        f'<button type="button" class="chart-nav-arrow next" '
        f'data-chart-nav="next" data-chart-id="{html.escape(chart_id)}" '
        'aria-label="Show next range">›</button>'
        "</div>"
        f'<div class="chart-meta" id="{html.escape(chart_id)}-meta"></div>'
        "</section>"
    )


def chart_script(*chart_ids: str) -> str:
    ids = json.dumps(list(chart_ids))
    script = chart_script_source()
    script = script.replace("{ids}", ids).replace("{{", "{").replace("}}", "}")
    return script
