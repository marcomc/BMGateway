"""Home page rendering for the BMGateway web interface."""

from __future__ import annotations

import html
from urllib.parse import quote

from . import display_version
from . import web_pages as shared
from .web_ui import (
    app_document,
    chart_card,
    chart_script,
    section_card,
    top_header,
)


def render_home_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    chart_points: list[dict[str, object]],
    legend: list[tuple[str, str]],
    show_chart_markers: bool = False,
    visible_device_limit: int = 4,
    appearance: str = "system",
    default_chart_range: str = "7",
    default_chart_metric: str = "soc",
    language: str = "en",
) -> str:
    version_label = display_version()
    resolved_default_chart_range = shared._sanitize_default_chart_range(default_chart_range)
    primary_device_id = shared._primary_device_id(snapshot, devices)
    overview_track_id = "home-overview-track"
    overview_scroller = home_overview_scroller_html(
        snapshot=snapshot,
        devices=devices,
        visible_device_limit=visible_device_limit,
        track_id=overview_track_id,
        include_controls=True,
    )
    chart_id = "home-overview-chart"
    body = (
        top_header(
            title="BMGateway",
            right=(
                f'<div class="header-build-badge" translate="no">{html.escape(version_label)}</div>'
            ),
        )
        + section_card(
            title="Battery Overview",
            subtitle="Touch the charge circle to open device details.",
            body=overview_scroller,
        )
        + (
            '<section class="home-add-device-strip">'
            '<a class="primary-button icon-button home-add-device-button" href="/devices/new">'
            '<span class="button-icon" aria-hidden="true">+</span>'
            "<span>Add Device</span></a>"
            "</section>"
        )
        + chart_card(
            chart_id=chart_id,
            title="Fleet Trend",
            subtitle="",
            points=chart_points,
            range_options=shared._visible_chart_range_options(),
            default_range=resolved_default_chart_range,
            default_metric=default_chart_metric,
            legend=legend or [("No devices", "#95a3b8")],
            show_markers=show_chart_markers,
        )
    )
    return app_document(
        title="BMGateway",
        body=body,
        active_nav="home",
        primary_device_id=primary_device_id,
        version_label=version_label,
        theme_preference=appearance,
        language=language,
        script=chart_script(chart_id, language=language)
        + shared._home_overview_script(overview_track_id),
    )


def home_overview_scroller_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    visible_device_limit: int,
    track_id: str,
    include_controls: bool,
) -> str:
    snapshot_devices = shared._merge_snapshot_devices(snapshot, devices)
    device_cards: list[str] = []
    for index, device in enumerate(snapshot_devices):
        if not isinstance(device, dict):
            continue
        color_key = shared._device_color_key(device, fallback_index=index)
        device_accent = shared._device_accent_color(device, fallback_index=index)
        device_id = str(device.get("id", ""))
        voltage_value = shared._format_number(device.get("voltage"), digits=2, suffix="V")
        voltage_text = html.escape(voltage_value)
        temperature_text = html.escape(
            shared._format_number(device.get("temperature"), digits=1, suffix="°C")
        )
        device_name_text = html.escape(str(device.get("name", device_id)))
        badge_stack_markup = shared._device_badge_stack_markup(
            device,
            badge_class="battery-tile-icon battery-card-badge",
            stack_class="home-orb-badges",
        )
        vehicle_text = html.escape(shared._vehicle_summary(device))
        battery_summary = shared._battery_home_metadata_summary(device)
        battery_meta_html = (
            ""
            if battery_summary == "Battery details not set"
            else f"<div class='meta battery-card-meta-extra'>{html.escape(battery_summary)}</div>"
        )
        circle_status = shared._battery_card_status_markup(device, inline=True)
        gauge_value = html.escape(shared._format_number(device.get("soc"), digits=0, suffix="%"))
        gauge_inner = (
            '<div class="home-orb-layout">'
            '<div class="home-orb-head">'
            '<div class="device-card-copy battery-card-copy home-orb-copy">'
            f"<div class='meta meta-name'>{device_name_text}</div>"
            f"<div class='meta meta-context'>{vehicle_text}</div>"
            f"{battery_meta_html}"
            "</div>"
            f"{badge_stack_markup}"
            "</div>"
            '<div class="home-orb-center">'
            f'<div class="battery-card-gauge-value">{gauge_value}</div>'
            f"{circle_status}"
            f'<div class="battery-card-gauge-label">{temperature_text}</div>'
            f'<div class="battery-card-gauge-subvalue">{voltage_text}</div>'
            "</div>"
            "</div>"
        )
        gauge_markup = shared._soc_gauge_markup(
            soc_value=device.get("soc"),
            compact=True,
            inner_html=gauge_inner,
            accent_css=device_accent,
        )
        device_href = f"/device?device_id={quote(device_id)}"
        device_cards.append(
            f"<article class='home-overview-card home-overview-orb-shell'>"
            f"<a class='home-overview-card-link home-overview-orb tone-card {color_key}' "
            f"href='{device_href}' aria-label='Open details for {device_name_text}' "
            f"style='{shared._tone_card_style(color_key)}'>"
            f"{gauge_markup}"
            "</a>"
            "</article>"
        )
    overview_pages = shared._chunk_overview_cards(
        device_cards,
        device_slots=visible_device_limit,
        add_card="",
    )
    is_paginated = len(overview_pages) > 1
    overview_pages_html = "".join(
        (
            f'<div class="{_overview_page_class(page, is_paginated=is_paginated)}" '
            f'style="{_overview_page_style(page)}">' + "".join(page) + "</div>"
        )
        for page in overview_pages
    )
    overview_controls = ""
    if include_controls and is_paginated:
        overview_controls = (
            '<div class="home-overview-controls">'
            f'<button type="button" class="ghost-button home-overview-arrow" '
            f'data-overview-target="{track_id}" data-direction="previous" '
            'aria-label="Show previous home cards">Prev</button>'
            f'<button type="button" class="ghost-button home-overview-arrow" '
            f'data-overview-target="{track_id}" data-direction="next" '
            'aria-label="Show next home cards">Next</button>'
            "</div>"
        )
    return (
        overview_controls
        + f'<div id="{track_id}" class="home-overview-scroller'
        + ("" if is_paginated else " is-single-page")
        + f'">{overview_pages_html}</div>'
    )


def _overview_page_style(page: list[str]) -> str:
    columns, rows = shared._overview_layout_dimensions(len(page))
    return f"--overview-columns: {columns}; --overview-rows: {rows};"


def _overview_page_class(page: list[str], *, is_paginated: bool) -> str:
    return shared._overview_page_class(len(page), is_single_page=not is_paginated)
