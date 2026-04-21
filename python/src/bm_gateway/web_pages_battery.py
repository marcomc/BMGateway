"""Battery overview page rendering for the BMGateway web interface."""

from __future__ import annotations

import html
from urllib.parse import quote

from . import display_version
from . import web_pages as shared
from .web_ui import (
    app_document,
    banner_strip,
    chart_card,
    chart_script,
    section_card,
    tone_card,
    top_header,
)


def render_battery_html(
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
) -> str:
    version_label = display_version()
    primary_device_id = shared._primary_device_id(snapshot, devices)
    snapshot_devices = shared._merge_snapshot_devices(snapshot, devices)
    device_cards: list[str] = []
    for index, device in enumerate(snapshot_devices):
        if not isinstance(device, dict):
            continue
        color_key = shared._device_color_key(device, fallback_index=index)
        device_id = str(device.get("id", ""))
        voltage_value = shared._format_number(device.get("voltage"), digits=2, suffix="V")
        voltage_text = html.escape(voltage_value)
        temperature_text = html.escape(
            shared._format_number(device.get("temperature"), digits=1, suffix="°C")
        )
        device_name_text = html.escape(str(device.get("name", device_id)))
        reading_text = f"Temperature {temperature_text}"
        badge_stack_markup = shared._device_badge_stack_markup(
            device,
            badge_class="battery-tile-icon battery-card-badge",
        )
        vehicle_text = html.escape(shared._vehicle_summary(device))
        battery_summary = shared._battery_metadata_summary(device)
        battery_meta_html = (
            ""
            if battery_summary == "Battery details not set"
            else f"<div class='meta battery-card-meta-extra'>{html.escape(battery_summary)}</div>"
        )
        circle_status = shared._battery_card_status_markup(device, inline=True)
        gauge_value = html.escape(shared._format_number(device.get("soc"), digits=0, suffix="%"))
        gauge_inner = (
            f'<div class="battery-card-gauge-value">{gauge_value}</div>'
            f"{circle_status}"
            f'<div class="battery-card-gauge-label">{voltage_text}</div>'
        )
        gauge_markup = shared._soc_gauge_markup(
            soc_value=device.get("soc"),
            compact=True,
            inner_html=gauge_inner,
        )
        device_cards.append(
            tone_card(
                (
                    "<div class='battery-card-top'>"
                    "<div class='device-card-copy battery-card-copy'>"
                    f"<div class='meta meta-name'>{device_name_text}</div>"
                    f"<div class='meta meta-context'>{vehicle_text}</div>"
                    f"<div class='meta battery-card-reading'>{reading_text}</div>"
                    f"{battery_meta_html}"
                    "</div>"
                    f"{badge_stack_markup}"
                    "</div>"
                    "<div class='battery-tile-hero'>"
                    f"{gauge_markup}"
                    "</div>"
                    "<div class='footer-row'>"
                    f'<a class="secondary-button" href="/device?device_id={quote(device_id)}">'
                    "Device Details</a>"
                    "</div>"
                ),
                tone=color_key,
                extra_class="battery-overview-card",
                style=shared._tone_card_style(color_key),
            )
        )
    overview_pages = shared._chunk_overview_cards(
        device_cards,
        device_slots=visible_device_limit,
        add_card="",
    )
    overview_track_id = "battery-overview-track"
    is_paginated = len(overview_pages) > 1
    overview_pages_html = "".join(
        (
            f'<div class="{_overview_page_class(page, is_paginated=is_paginated)}" '
            f'style="{_overview_page_style(page)}">' + "".join(page) + "</div>"
        )
        for page in overview_pages
    )
    overview_controls = ""
    if is_paginated:
        overview_controls = (
            '<div class="battery-overview-controls">'
            f'<button type="button" class="ghost-button battery-overview-arrow" '
            f'data-overview-target="{overview_track_id}" data-direction="previous" '
            'aria-label="Show previous battery cards">Prev</button>'
            f'<button type="button" class="ghost-button battery-overview-arrow" '
            f'data-overview-target="{overview_track_id}" data-direction="next" '
            'aria-label="Show next battery cards">Next</button>'
            "</div>"
        )
    overview_scroller = (
        overview_controls
        + f'<div id="{overview_track_id}" class="battery-overview-scroller'
        + ("" if is_paginated else " is-single-page")
        + f'">{overview_pages_html}</div>'
    )
    chart_id = "battery-overview-chart"
    body = (
        top_header(
            title="BMGateway Battery",
            subtitle=(
                "Live battery overview with BM300-style card hierarchy, "
                "direct device entry points, and a calmer cross-device chart."
            ),
            eyebrow="Battery",
        )
        + section_card(
            title="Battery Overview",
            subtitle=(
                "The default landing page mirrors the mobile app journey: "
                "check live state first, then dive into device detail or history."
            ),
            body=overview_scroller,
        )
        + banner_strip(
            "Bluetooth device status is shown directly on each card. Classic-only "
            "or unavailable BLE adapters remain visible as controlled warnings.",
            kind="warning",
            trailing=(
                '<a class="primary-button icon-button" href="/devices/new">'
                '<span class="button-icon" aria-hidden="true">+</span>'
                "<span>Add Device</span></a>"
            ),
        )
        + chart_card(
            chart_id=chart_id,
            title="Fleet Trend",
            subtitle=(
                "Historical fleet chart with multi-device overlays, calmer "
                "axis rhythm, and the same metric switching model used "
                "throughout the app."
            ),
            points=chart_points,
            range_options=(
                ("raw", "Recent raw"),
                ("1", "1 day"),
                ("7", "7 days"),
                ("30", "30 days"),
                ("90", "90 days"),
                ("365", "1 year"),
                ("730", "2 years"),
                ("all", "All"),
            ),
            default_range=default_chart_range,
            default_metric=default_chart_metric,
            legend=legend or [("No devices", "#95a3b8")],
            show_markers=show_chart_markers,
        )
    )
    return app_document(
        title="BMGateway Battery",
        body=body,
        active_nav="battery",
        primary_device_id=primary_device_id,
        version_label=version_label,
        theme_preference=appearance,
        script=chart_script(chart_id) + shared._battery_overview_script(overview_track_id),
    )


def _overview_page_style(page: list[str]) -> str:
    columns, rows = shared._overview_layout_dimensions(len(page))
    return f"--overview-columns: {columns}; --overview-rows: {rows};"


def _overview_page_class(page: list[str], *, is_paginated: bool) -> str:
    return shared._overview_page_class(len(page), is_single_page=not is_paginated)
