"""Device registry page rendering for the BMGateway web interface."""

from __future__ import annotations

import html
from typing import cast
from urllib.parse import quote

from . import display_version
from . import web_pages as shared
from .device_registry import default_battery_family, default_battery_profile
from .web_ui import (
    app_document,
    banner_strip,
    button,
    metric_tile,
    section_card,
    status_badge,
    top_header,
)


def render_devices_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    message: str = "",
    theme_preference: str = "system",
) -> str:
    version_label = display_version()
    primary_device_id = shared._primary_device_id(snapshot, devices)
    snapshot_devices = {
        str(device.get("id", "")): device
        for device in cast(list[object], snapshot.get("devices", []))
        if isinstance(device, dict)
    }
    cards: list[str] = []
    for index, device in enumerate(devices):
        device_id = str(device.get("id", ""))
        runtime = snapshot_devices.get(device_id, {})
        runtime_error_code = cast(str | None, runtime.get("error_code"))
        connected = bool(runtime.get("connected", False))
        tone = shared._device_color_key(device, fallback_index=index)
        status_value, status_subvalue = shared._device_runtime_summary(runtime)
        state_tile = metric_tile(
            label="Status",
            value=status_value,
            tone=tone,
            subvalue=status_subvalue,
        )
        signal_grade, _signal_percent, _bars, _signal_rssi_text = shared._signal_quality(
            rssi=runtime.get("rssi"),
            connected=connected,
            error_code=runtime_error_code,
        )
        signal_tile = metric_tile(
            label="Signal Quality",
            value=signal_grade,
            tone="blue",
            detail_html=shared._signal_quality_detail_html(
                rssi=runtime.get("rssi"),
                connected=connected,
                error_code=runtime_error_code,
            ),
        )
        family_label, profile_label = shared._battery_summary(device)
        battery_type = html.escape(profile_label)
        enabled_badge = status_badge(
            "Enabled" if bool(device.get("enabled", False)) else "Disabled",
            kind="ok" if bool(device.get("enabled", False)) else "offline",
        )
        device_name_text = html.escape(str(device.get("name", device_id)))
        device_mac_text = html.escape(str(device.get("mac", "")))
        vehicle_text = html.escape(shared._vehicle_summary(device))
        battery_summary = shared._battery_metadata_summary(device)
        battery_text = html.escape(
            battery_summary if battery_summary != "Battery details not set" else family_label
        )
        device_id_text = html.escape(device_id)
        family_badge_html = (
            ""
            if family_label == profile_label
            else f"<span class='pill-chip'>{html.escape(family_label)}</span>"
        )
        device_icon_markup = shared._device_badge_stack_markup(
            device,
            badge_class="device-list-icon",
            stack_class="compact",
        )
        cards.append(
            section_card(
                body=(
                    "<div class='device-list-card'>"
                    "<div class='device-list-card-head'>"
                    f"{device_icon_markup}"
                    "<div class='device-list-card-copy'>"
                    f"<div class='meta device-list-card-context'>{vehicle_text}</div>"
                    f"<div class='device-list-card-name'>{device_name_text}</div>"
                    f"<div class='meta device-list-card-summary'>{battery_text}</div>"
                    f"<div class='meta device-list-card-id'>ID: {device_id_text}</div>"
                    f"<div class='meta device-list-card-id'>Serial / MAC: {device_mac_text}</div>"
                    "</div>"
                    "</div>"
                    "<div class='device-list-card-badges'>"
                    f"<span class='pill-chip'>{battery_type}</span>"
                    f"{family_badge_html}"
                    f"{enabled_badge}"
                    "</div>"
                    "<div class='two-column-grid compact-device-metrics'>"
                    f"{state_tile}"
                    f"{signal_tile}"
                    "</div>"
                    "<div class='footer-row device-list-card-actions'>"
                    f"<a class='ghost-button' href='/devices/edit?device_id={quote(device_id)}'>"
                    "Edit device settings</a>"
                    "</div>"
                    "</div>"
                ),
                classes=f"tone-card {tone}",
            )
        )
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    body = (
        top_header(
            title="Devices",
            subtitle=(
                "Gateway-ready device registry with BM300-inspired list cards "
                "and a direct path to add or edit hardware."
            ),
            eyebrow="Devices",
            right=(
                '<div class="hero-actions">'
                '<a class="primary-button" href="/devices/new">Add Device</a>'
                "</div>"
            ),
        )
        + banner
        + section_card(
            title="Configured Devices",
            subtitle="Gateway-ready device registry",
            body=(
                (
                    '<div class="device-grid devices-grid'
                    + (" single-card-grid" if len(cards) == 1 else "")
                    + f'">{"".join(cards)}</div>'
                )
                if cards
                else "<div class='muted-note'>No devices configured yet.</div>"
            ),
        )
    )
    return app_document(
        title="BMGateway Devices",
        body=body,
        active_nav="devices",
        primary_device_id=primary_device_id,
        version_label=version_label,
        theme_preference=theme_preference,
    )


def render_add_device_html(
    *,
    message: str = "",
    theme_preference: str = "system",
    selected_color_key: str = "green",
    reserved_color_keys: set[str] | None = None,
) -> str:
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    body = (
        top_header(
            title="Add Device",
            subtitle=(
                "Register a new BM device without the configured-device list getting in the way."
            ),
            eyebrow="Devices",
            right=(
                '<div class="hero-actions">'
                '<a class="secondary-button" href="/devices">Back to devices</a>'
                "</div>"
            ),
        )
        + banner
        + section_card(
            title="New Device",
            subtitle="Register new BM devices directly from the device registry.",
            body=shared._add_device_form_html(
                selected_color_key=selected_color_key,
                reserved_color_keys=reserved_color_keys,
            ),
        )
    )
    return app_document(
        title="BMGateway Add Device",
        body=body,
        active_nav="devices",
        primary_device_id="",
        version_label=display_version(),
        theme_preference=theme_preference,
        script=shared._battery_form_script(),
    )


def render_edit_device_html(
    *,
    device: dict[str, object],
    message: str = "",
    theme_preference: str = "system",
    reserved_color_keys: set[str] | None = None,
) -> str:
    device_id = str(device.get("id", ""))
    battery = device.get("battery")
    battery_table = battery if isinstance(battery, dict) else {}
    family = str(
        battery_table.get("family", default_battery_family(str(device.get("type", "bm200"))))
    )
    profile = str(
        battery_table.get(
            "profile",
            default_battery_profile(str(device.get("type", "bm200")), family),
        )
    )
    custom_soc_mode = str(battery_table.get("custom_soc_mode", "intelligent_algorithm"))
    custom_curve = battery_table.get("custom_voltage_curve", [])
    curve_pairs = [
        (
            int(shared._coerce_float(cast(dict[str, object], row).get("percent", 0))),
            shared._coerce_float(cast(dict[str, object], row).get("voltage", 0.0)),
        )
        for row in cast(list[object], custom_curve)
        if isinstance(row, dict)
    ]
    color_key = shared._device_color_key(device)
    installed_in_vehicle = bool(device.get("installed_in_vehicle", False))
    vehicle_table = device.get("vehicle")
    vehicle_type = ""
    if isinstance(vehicle_table, dict):
        vehicle_type = str(vehicle_table.get("type", ""))
    if not vehicle_type:
        vehicle_type = str(device.get("vehicle_type", ""))
    battery_brand = html.escape(str(battery_table.get("brand", "")))
    battery_model = html.escape(str(battery_table.get("model", "")))
    battery_capacity_ah = battery_table.get("capacity_ah")
    battery_production_year = battery_table.get("production_year")
    battery_capacity_text = (
        "" if battery_capacity_ah in (None, "") else html.escape(str(battery_capacity_ah))
    )
    battery_year_text = (
        "" if battery_production_year in (None, "") else html.escape(str(battery_production_year))
    )
    device_name = html.escape(str(device.get("name", "")))
    device_mac = html.escape(str(device.get("mac", "")))
    device_type = str(device.get("type", "bm200"))
    device_type_options = (
        f'<option value="bm200"{shared._selected_attr(device_type == "bm200")}>'
        "bm200</option>"
        f'<option value="bm300pro"{shared._selected_attr(device_type == "bm300pro")}>'
        "bm300pro</option>"
    )
    family_options = shared._battery_family_options(selected_family=family)
    profile_options = shared._battery_profile_options(selected_profile=profile)
    custom_mode_options = shared._custom_mode_options(selected_mode=custom_soc_mode)
    vehicle_type_options = shared._vehicle_type_options(selected_vehicle_type=vehicle_type)
    color_control_html = shared._color_key_control_html(
        selected_color_key=color_key,
        reserved_color_keys=reserved_color_keys,
        control_id="edit-device-color-input",
    )
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    body = (
        top_header(
            title="Edit Device",
            subtitle=(
                "Update the registry metadata, battery profile, and "
                "installation context for this monitor."
            ),
            eyebrow="Devices",
        )
        + banner
        + section_card(
            title=str(device.get("name", device_id)),
            subtitle="Update the registry metadata and battery profile for this monitor.",
            body=(
                '<form method="post" action="/devices/update" class="two-column-grid" '
                'data-battery-config-form="true">'
                f'<input type="hidden" name="device_id" value="{html.escape(device_id)}">'
                '<div><label class="settings-label" for="edit-device-name-input">Name</label>'
                f'<input id="edit-device-name-input" type="text" '
                f'name="device_name" value="{device_name}" '
                'autocomplete="off" required></div>'
                '<div><label class="settings-label" for="edit-device-type-input">Type</label>'
                '<select id="edit-device-type-input" name="device_type" autocomplete="off">'
                f"{device_type_options}"
                "</select></div>"
                '<div><label class="settings-label" '
                'for="edit-device-mac-input">MAC or serial</label>'
                f'<input id="edit-device-mac-input" type="text" '
                f'name="device_mac" value="{device_mac}" '
                'autocomplete="off" spellcheck="false" required></div>'
                '<div><label class="settings-label" '
                'for="edit-installed-in-vehicle-input">Vehicle install</label>'
                f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                f'<input id="edit-installed-in-vehicle-input" type="checkbox" '
                f'name="installed_in_vehicle"{shared._checked_attr(installed_in_vehicle)}>'
                "<span>Installed in a vehicle</span></label></div>"
                '<div data-vehicle-section><label class="settings-label" '
                'for="edit-vehicle-type-input">Vehicle type</label>'
                f'<select id="edit-vehicle-type-input" name="vehicle_type">'
                f"{vehicle_type_options}</select>"
                "</div>"
                '<div class="battery-form-section" style="grid-column:1 / -1">'
                "<div><div class='settings-label'>Battery Support</div>"
                "<div class='inline-field-help'>"
                "Edit the same battery taxonomy exposed by the official app, "
                "including custom curves. Battery and vehicle badges are assigned automatically."
                "</div></div>"
                "<div class='battery-form-grid'>"
                "<div><label class='settings-label' "
                "for='edit-device-color-input'>Overview color</label>"
                f"{color_control_html}"
                "</div>"
                "<div><label class='settings-label' "
                "for='edit-battery-family-input'>Battery family</label>"
                f"<select id='edit-battery-family-input' "
                f"name='battery_family'>{family_options}</select></div>"
                "<div><label class='settings-label' "
                "for='edit-battery-profile-input'>Battery profile</label>"
                f"<select id='edit-battery-profile-input' "
                f"name='battery_profile'>{profile_options}</select></div>"
                "<div data-custom-mode-section><label class='settings-label' "
                "for='edit-custom-soc-mode-input'>Custom battery mode</label>"
                f"<select id='edit-custom-soc-mode-input' "
                f"name='custom_soc_mode'>{custom_mode_options}</select></div>"
                "</div>"
                '<div class="battery-form-grid">'
                '<div><label class="settings-label" '
                'for="edit-battery-brand-input">Battery brand</label>'
                f'<input id="edit-battery-brand-input" type="text" '
                f'name="battery_brand" value="{battery_brand}" '
                'autocomplete="off"></div>'
                '<div><label class="settings-label" '
                'for="edit-battery-model-input">Battery model</label>'
                f'<input id="edit-battery-model-input" type="text" '
                f'name="battery_model" value="{battery_model}" '
                'autocomplete="off"></div>'
                '<div><label class="settings-label" '
                'for="edit-battery-capacity-input">Capacity (Ah)</label>'
                f'<input id="edit-battery-capacity-input" type="number" step="0.1" '
                f'min="0" name="battery_capacity_ah" inputmode="decimal" '
                f'value="{battery_capacity_text}"></div>'
                '<div><label class="settings-label" '
                'for="edit-battery-year-input">Production year</label>'
                f'<input id="edit-battery-year-input" type="number" min="1950" max="2100" '
                f'name="battery_production_year" inputmode="numeric" '
                f'value="{battery_year_text}"></div>'
                "</div>"
                "<div data-custom-curve-section>"
                '<div class="settings-label">Voltage corresponding to power</div>'
                f'<div class="curve-grid">{shared._curve_rows_html(tuple(curve_pairs))}</div>'
                "</div>"
                "</div>"
                f'<div style="grid-column:1 / -1">{button("Save Device", kind="primary")}</div>'
                "</form>"
            ),
        )
    )
    return app_document(
        title=f"Edit Device {device_id}",
        body=body,
        active_nav="devices",
        primary_device_id=device_id,
        version_label=display_version(),
        theme_preference=theme_preference,
        script=shared._battery_form_script(),
    )
