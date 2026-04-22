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
    section_card,
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
    rows: list[str] = []
    for index, device in enumerate(devices):
        device_id = str(device.get("id", ""))
        tone = shared._device_color_key(device, fallback_index=index)
        family_label, _profile_label = shared._battery_summary(device)
        device_name_text = html.escape(str(device.get("name", device_id)))
        device_mac_text = html.escape(str(device.get("mac", "")))
        vehicle_text = html.escape(shared._vehicle_summary(device))
        battery_summary = shared._battery_metadata_summary(device)
        battery_text = html.escape(
            battery_summary if battery_summary != "Battery details not set" else family_label
        )
        device_icon_markup = shared._device_badge_stack_markup(
            device,
            badge_class="battery-tile-icon device-list-badge",
            stack_class="compact",
        )
        rows.append(
            f"<div class='device-list-row tone-card {tone}' "
            f"style='{shared._tone_card_style(tone)}'>"
            "<div class='device-list-row-main'>"
            f"{device_icon_markup}"
            "<div class='device-list-row-copy'>"
            f"<div class='meta device-list-row-name'>{device_name_text}</div>"
            f"<div class='meta device-list-row-context'>{vehicle_text}</div>"
            f"<div class='meta device-list-row-summary'>{battery_text}</div>"
            f"<div class='meta device-list-row-id'>Serial / MAC: {device_mac_text}</div>"
            "</div>"
            "</div>"
            "<div class='device-list-row-actions'>"
            f"<a class='ghost-button' href='/devices/edit?device_id={quote(device_id)}'>"
            "Edit device</a>"
            "</div>"
            "</div>"
        )
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    body = (
        top_header(
            title="Devices",
            subtitle=(
                "Configured gateway devices shown as a compact list with "
                "battery identity, badges, and a direct edit action."
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
            subtitle="Configured devices with their assigned overview colors.",
            body=(
                f'<div class="device-list-rows">{"".join(rows)}</div>'
                if rows
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
