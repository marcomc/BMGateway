"""Page rendering and UI composition for the BMGateway web interface."""

from __future__ import annotations

import html
from pathlib import Path
from typing import cast
from urllib.parse import quote

from . import __build_timestamp__, __version__, display_version
from .config import AppConfig
from .device_registry import (
    BATTERY_FAMILIES,
    COLOR_CATALOG,
    CUSTOM_SOC_MODES,
    LEAD_ACID_PROFILES,
    LITHIUM_PROFILES,
    VEHICLE_TYPES,
    Device,
    battery_family_label,
    battery_profile_label,
    default_battery_family,
    default_battery_profile,
    default_icon_key,
    icon_label,
    vehicle_type_label,
)
from .state_store import (
    fetch_daily_history,
    fetch_recent_history,
)
from .web_support import default_curve_pairs
from .web_ui import (
    button,
    device_icon,
    section_card,
    status_badge,
)

PROTOCOL_STATE_CODES: dict[str, int] = {
    "critical": 0,
    "low": 1,
    "normal": 2,
    "charging": 4,
    "floating": 8,
}

PROTOCOL_STATUS_SCALE: tuple[tuple[str, str, str, str], ...] = (
    ("critical", "Critical", "Battery is in a critically low or alarm condition.", "error"),
    ("low", "Low", "Battery charge is low and should be recharged soon.", "warning"),
    ("normal", "Normal", "Battery condition is stable and ready for normal use.", "ok"),
    ("charging", "Charging", "The monitor sees the battery under active charge.", "info"),
    (
        "floating",
        "Floating",
        "Battery is full and is being maintained at float charge.",
        "purple",
    ),
)

DEVICE_COLOR_HEX: dict[str, str] = {
    "green": "#17c45a",
    "blue": "#4f8df7",
    "purple": "#9a57f5",
    "orange": "#f4a340",
    "teal": "#16b8b0",
    "rose": "#ec5c86",
    "indigo": "#6677ff",
    "amber": "#f0b429",
}

VISIBLE_CHART_RANGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("1", "1 day"),
    ("3", "3 days"),
    ("5", "5 days"),
    ("7", "7 days"),
    ("30", "30 days"),
    ("90", "90 days"),
    ("365", "1 year"),
    ("730", "2 years"),
    ("all", "All"),
)

RECENT_CHART_HISTORY_LIMIT = 6000


def _device_color_key(device: dict[str, object], *, fallback_index: int = 0) -> str:
    color_key = str(device.get("color_key", "")).strip()
    if color_key in COLOR_CATALOG:
        return color_key
    palette = tuple(COLOR_CATALOG)
    return palette[fallback_index % len(palette)]


def _device_accent_color(device: dict[str, object], *, fallback_index: int = 0) -> str:
    return DEVICE_COLOR_HEX[_device_color_key(device, fallback_index=fallback_index)]


def _tone_card_style(color_key: str) -> str:
    accent = DEVICE_COLOR_HEX[color_key]
    return (
        f"--card-accent: {accent};"
        f"--card-accent-soft: color-mix(in srgb, {accent} 16%, var(--bg-surface));"
        f"--card-accent-soft-strong: color-mix(in srgb, {accent} 26%, var(--bg-surface));"
        f"--card-accent-glow: color-mix(in srgb, {accent} 24%, transparent);"
    )


def _visible_chart_range_options() -> tuple[tuple[str, str], ...]:
    return VISIBLE_CHART_RANGE_OPTIONS


def _sanitize_default_chart_range(range_value: str) -> str:
    allowed = {value for value, _label in VISIBLE_CHART_RANGE_OPTIONS}
    return range_value if range_value in allowed else "7"


def _read_sysfs_value(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _discover_bluetooth_adapters(
    sysfs_root: Path = Path("/sys/class/bluetooth"),
) -> list[dict[str, str]]:
    if not sysfs_root.exists():
        return []
    adapters: list[dict[str, str]] = []
    for entry in sorted(sysfs_root.iterdir()):
        if not entry.is_dir() or not entry.name.startswith("hci"):
            continue
        adapters.append(
            {
                "name": entry.name,
                "address": _read_sysfs_value(entry / "address"),
                "alias": _read_sysfs_value(entry / "name") or entry.name,
            }
        )
    return adapters


def _snapshot_with_version(snapshot: dict[str, object]) -> dict[str, object]:
    payload = dict(snapshot)
    payload["version"] = __version__
    payload["build"] = __build_timestamp__.isoformat(timespec="seconds")
    payload["display_version"] = display_version()
    return payload


def _device_label(device: dict[str, object]) -> str:
    name = str(device.get("name", "")).strip()
    device_id = str(device.get("id", "")).strip()
    if name and device_id and name != device_id:
        return f"{name} ({device_id})"
    return name or device_id or "Unknown device"


def _history_device_selector_html(
    *,
    configured_devices: list[dict[str, object]],
    selected_device_id: str,
) -> str:
    if not configured_devices:
        return section_card(
            title="No Devices Configured",
            body=(
                "<div class='inline-actions'>"
                '<a class="primary-button" href="/devices/new">Add Device</a>'
                '<a class="secondary-button" href="/devices">Configured Devices</a>'
                "</div>"
            ),
        )

    device_cards: list[str] = []
    for index, device in enumerate(configured_devices):
        device_id = str(device.get("id", ""))
        is_selected = device_id == selected_device_id
        color_key = _device_color_key(device, fallback_index=index)
        identity_summary = _history_device_identity_summary(device)
        current_text = "Current History View" if is_selected else "Open Device History"
        aria_current = ' aria-current="page"' if is_selected else ""
        device_name = html.escape(str(device.get("name") or device_id))
        identity_summary_html = html.escape(identity_summary)
        current_text_html = html.escape(current_text)
        badge_markup = _device_badge_stack_markup(
            device,
            badge_class="history-device-badge",
            stack_class="compact",
        )
        device_cards.append(
            f'<a class="history-device-card tone-card {color_key}'
            f'{" selected" if is_selected else ""}" href="/history?device_id={quote(device_id)}"'
            f"{aria_current}>"
            "<div class='history-device-head'>"
            f"{badge_markup}"
            "<div class='device-card-copy history-device-copy'>"
            f"<div class='meta meta-name'>{device_name}</div>"
            f"<div class='meta meta-context history-device-summary'>{identity_summary_html}</div>"
            f"<div class='meta history-device-current'>{current_text_html}</div>"
            "</div>"
            "</div>"
            "</a>"
        )
    return section_card(
        title="History Device",
        body=f'<div class="device-grid history-device-grid">{"".join(device_cards)}</div>',
    )


def _history_device_identity_summary(device: dict[str, object]) -> str:
    battery = device.get("battery")
    if isinstance(battery, dict):
        parts: list[str] = []
        brand = str(battery.get("brand", "")).strip()
        model = str(battery.get("model", "")).strip()
        family = str(battery.get("family", "")).strip()
        profile = str(battery.get("profile", "")).strip()
        if brand:
            parts.append(brand)
        if model:
            parts.append(model)
        if profile:
            parts.append(
                battery_profile_label(
                    family=family or default_battery_family(str(device.get("type", "bm200"))),
                    profile=profile,
                )
            )
        elif family:
            parts.append(battery_family_label(family))
        if parts:
            return " · ".join(parts)
        if family:
            return battery_family_label(family)
        if profile:
            return battery_profile_label(
                family=family or default_battery_family(str(device.get("type", "bm200"))),
                profile=profile,
            )
    return _vehicle_summary(device)


def _soc_gauge_markup(
    *,
    soc_value: object,
    compact: bool = False,
    inner_html: str | None = None,
    accent_css: str = "var(--accent-green)",
) -> str:
    soc_percent = min(max(_coerce_float(soc_value, 0.0), 0.0), 100.0)
    gauge_degrees = soc_percent * 3.6
    soc_text = html.escape(_format_number(soc_percent, digits=0, suffix="%"))
    gauge_class = "battery-card-gauge" if compact else "soc-gauge"
    content_class = "battery-card-gauge-content" if compact else "soc-gauge-content"
    label_class = "battery-card-gauge-label" if compact else "soc-gauge-label"
    value_class = "battery-card-gauge-value" if compact else "soc-gauge-value"
    label_text = "Charge" if compact else "SoC"
    gauge_inner = (
        inner_html
        if inner_html is not None
        else (
            f'<div class="{label_class}">{label_text}</div>'
            f'<div class="{value_class}">{soc_text}</div>'
        )
    )
    return (
        f'<div class="{gauge_class}" style="background: conic-gradient({accent_css} '
        f"0deg {gauge_degrees}deg, rgba(191, 207, 198, 0.55) "
        f'{gauge_degrees}deg 360deg);">'
        f'<div class="{content_class}">{gauge_inner}</div>'
        "</div>"
    )


def _overview_layout_dimensions(card_count: int) -> tuple[int, int]:
    if card_count <= 2:
        return 2, 1
    if card_count <= 4:
        return 2, 2
    if card_count <= 6:
        return 3, 2
    return 4, 2


def _chunk_overview_cards(
    device_cards: list[str],
    *,
    device_slots: int,
    add_card: str,
) -> list[list[str]]:
    if not device_cards:
        return [[]]
    pages: list[list[str]] = []
    for index in range(0, len(device_cards), device_slots):
        page_cards = [*device_cards[index : index + device_slots]]
        if add_card:
            page_cards.append(add_card)
        pages.append(page_cards)
    return pages


def _overview_page_class(card_count: int, *, is_single_page: bool) -> str:
    classes = ["home-overview-page"]
    if is_single_page:
        classes.append("is-single-page")
    if card_count <= 1:
        classes.append("page-one-card")
    elif card_count == 2:
        classes.append("page-two-cards")
    else:
        classes.append("page-multi-cards")
    return " ".join(classes)


def _home_overview_script(track_id: str) -> str:
    previous_selector = f'[data-overview-target="{track_id}"][data-direction="previous"]'
    next_selector = f'[data-overview-target="{track_id}"][data-direction="next"]'
    return f"""
<script>
(() => {{
  const track = document.getElementById("{track_id}");
  if (!track) {{
    return;
  }}
  const previousButton = document.querySelector('{previous_selector}');
  const nextButton = document.querySelector('{next_selector}');
  const pages = Array.from(track.querySelectorAll(".home-overview-page"));
  if (pages.length <= 1) {{
    if (previousButton) previousButton.hidden = true;
    if (nextButton) nextButton.hidden = true;
    return;
  }}
  let currentPage = 0;
  function syncButtons() {{
    if (previousButton) previousButton.disabled = currentPage <= 0;
    if (nextButton) nextButton.disabled = currentPage >= pages.length - 1;
  }}
  function scrollToPage(index) {{
    currentPage = Math.max(0, Math.min(index, pages.length - 1));
    pages[currentPage].scrollIntoView({{ behavior: "smooth", inline: "start", block: "nearest" }});
    syncButtons();
  }}
  if (previousButton) {{
    previousButton.addEventListener("click", () => scrollToPage(currentPage - 1));
  }}
  if (nextButton) {{
    nextButton.addEventListener("click", () => scrollToPage(currentPage + 1));
  }}
  track.addEventListener("scroll", () => {{
    const trackLeft = track.getBoundingClientRect().left;
    let bestIndex = 0;
    let bestDistance = Infinity;
    pages.forEach((page, index) => {{
      const distance = Math.abs(page.getBoundingClientRect().left - trackLeft);
      if (distance < bestDistance) {{
        bestDistance = distance;
        bestIndex = index;
      }}
    }});
    currentPage = bestIndex;
    syncButtons();
  }}, {{ passive: true }});
  syncButtons();
}})();
</script>
"""


def render_snapshot_html(snapshot: dict[str, object]) -> str:
    from .web_pages_snapshot import render_snapshot_html as _render_snapshot_html

    return _render_snapshot_html(snapshot)


def _management_links(snapshot: dict[str, object]) -> str:
    devices = snapshot.get("devices", [])
    items: list[str] = []
    for device in devices if isinstance(devices, list) else []:
        if isinstance(device, dict) and isinstance(device.get("id"), str):
            device_id = device["id"]
            items.append(
                f'<li><a href="/history?device_id={quote(device_id)}">'
                f"{html.escape(device_id)} history</a></li>"
            )
    return "\n".join(items) or "<li>No devices available</li>"


def _device_dashboard_cards(snapshot: dict[str, object]) -> str:
    devices = snapshot.get("devices", [])
    cards: list[str] = []
    for device in devices if isinstance(devices, list) else []:
        if not isinstance(device, dict):
            continue
        device_id = str(device.get("id", ""))
        cards.append(
            "<article class='device-card'>"
            f"<h3>{html.escape(str(device.get('name', device_id)))}</h3>"
            f"<p><strong>ID:</strong> {html.escape(device_id)}</p>"
            f"<p><strong>State:</strong> {html.escape(str(device.get('state', 'unknown')))}</p>"
            f"<p><strong>Voltage:</strong> {html.escape(str(device.get('voltage', '-')))}</p>"
            f"<p><strong>SoC:</strong> {html.escape(str(device.get('soc', '-')))}</p>"
            f"<p><a href='/device?device_id={quote(device_id)}'>Open device page</a></p>"
            "</article>"
        )
    return "\n".join(cards) or "<p>No active device cards yet.</p>"


def _device_table_rows(devices: list[dict[str, object]]) -> str:
    rows: list[str] = []
    for device in devices:
        family_label, profile_label = _battery_summary(device)
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(device.get('id', '')))}</td>"
            f"<td>{html.escape(str(device.get('type', '')))}</td>"
            f"<td>{html.escape(str(device.get('name', '')))}</td>"
            f"<td>{html.escape(str(device.get('mac', '')))}</td>"
            f"<td>{html.escape(profile_label)}</td>"
            f"<td>{html.escape(family_label)}</td>"
            f"<td>{html.escape(str(device.get('enabled', '')))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='7'>No configured devices</td></tr>"


def _escape_cell(value: object) -> str:
    return html.escape(str(value))


def _battery_summary(device: dict[str, object]) -> tuple[str, str]:
    battery = device.get("battery")
    if isinstance(battery, dict):
        family = str(battery.get("family", "lead_acid"))
        device_type = str(device.get("type", "bm200"))
        profile = str(
            battery.get(
                "profile",
                default_battery_profile(device_type, family),
            )
        )
        return battery_family_label(family), battery_profile_label(
            family=family,
            profile=profile,
        )
    family = default_battery_family(str(device.get("type", "bm200")))
    profile = default_battery_profile(str(device.get("type", "bm200")), family)
    return battery_family_label(family), battery_profile_label(family=family, profile=profile)


def _battery_metadata_summary(device: dict[str, object]) -> str:
    battery = device.get("battery")
    battery_table = battery if isinstance(battery, dict) else {}
    parts = [
        str(battery_table.get("brand", "")).strip(),
        str(battery_table.get("model", "")).strip(),
    ]
    nominal_voltage = battery_table.get("nominal_voltage")
    capacity = battery_table.get("capacity_ah")
    year = battery_table.get("production_year")
    if nominal_voltage not in (None, ""):
        parts.append(f"{nominal_voltage} V")
    if capacity not in (None, ""):
        parts.append(f"{capacity} Ah")
    if year not in (None, ""):
        parts.append(str(year))
    summary = " · ".join(part for part in parts if part)
    return summary or "Battery details not set"


def _battery_home_metadata_summary(device: dict[str, object]) -> str:
    battery = device.get("battery")
    battery_table = battery if isinstance(battery, dict) else {}
    parts = [
        str(battery_table.get("brand", "")).strip(),
        str(battery_table.get("model", "")).strip(),
    ]
    nominal_voltage = battery_table.get("nominal_voltage")
    capacity = battery_table.get("capacity_ah")
    if nominal_voltage not in (None, ""):
        parts.append(f"{nominal_voltage} V")
    if capacity not in (None, ""):
        parts.append(f"{capacity} Ah")
    summary = " ".join(part for part in parts if part)
    return summary or "Battery details not set"


def _vehicle_summary(device: dict[str, object]) -> str:
    vehicle = device.get("vehicle")
    if isinstance(vehicle, dict):
        vehicle_type = str(vehicle.get("type", "")).strip()
        if vehicle_type:
            return vehicle_type_label(vehicle_type)
    if bool(device.get("installed_in_vehicle", False)):
        vehicle_type = str(device.get("vehicle_type", "")).strip()
        if vehicle_type:
            return vehicle_type_label(vehicle_type)
        return "Installed in a vehicle"
    return "Bench"


def _device_icon_key(device: dict[str, object]) -> str:
    icon_key = device.get("icon_key")
    battery_icon_keys = {
        "battery_monitor",
        "lead_acid_battery",
        "agm_battery",
        "efb_battery",
        "gel_battery",
        "lithium_battery",
        "custom_battery",
    }
    if isinstance(icon_key, str) and icon_key in battery_icon_keys:
        return icon_key
    battery = device.get("battery")
    if isinstance(battery, dict):
        family = str(
            battery.get(
                "family",
                default_battery_family(str(device.get("type", "bm200"))),
            )
        )
        profile = str(
            battery.get(
                "profile",
                default_battery_profile(str(device.get("type", "bm200")), family),
            )
        )
    else:
        family = default_battery_family(str(device.get("type", "bm200")))
        profile = default_battery_profile(str(device.get("type", "bm200")), family)
    return default_icon_key(battery_family=family, battery_profile=profile)


def _vehicle_icon_key(device: dict[str, object]) -> str | None:
    vehicle = device.get("vehicle")
    vehicle_type = ""
    if isinstance(vehicle, dict):
        vehicle_type = str(vehicle.get("type", "")).strip()
    if not vehicle_type:
        vehicle_type = str(device.get("vehicle_type", "")).strip()
    if not vehicle_type:
        return None
    vehicle_icons = {
        "car": "vehicle_car",
        "motorcycle": "vehicle_motorcycle",
        "scooter": "vehicle_scooter",
        "electric_bike": "vehicle_electric_bike",
        "van": "vehicle_van",
        "camper": "vehicle_camper",
        "truck": "vehicle_truck",
        "bus": "vehicle_bus",
        "boat": "vehicle_boat",
        "tractor": "vehicle_tractor",
        "atv": "vehicle_atv",
        "machinery": "vehicle_machinery",
        "other_vehicle": "vehicle_other",
    }
    return vehicle_icons.get(vehicle_type, "vehicle_other")


def _device_badge_stack_markup(
    device: dict[str, object],
    *,
    badge_class: str,
    stack_class: str = "",
) -> str:
    badges = [
        device_icon(
            _device_icon_key(device),
            label=icon_label(_device_icon_key(device)),
            frame_class=badge_class,
        )
    ]
    vehicle_icon_key = _vehicle_icon_key(device)
    if bool(device.get("installed_in_vehicle", False)) and vehicle_icon_key:
        badges.append(
            device_icon(
                vehicle_icon_key,
                label=icon_label(vehicle_icon_key),
                frame_class=badge_class,
            )
        )
    else:
        badges.append(
            '<div class="device-icon-frame '
            f'{html.escape(badge_class)} badge-placeholder" aria-hidden="true"></div>'
        )
    classes = "device-badge-stack"
    if stack_class:
        classes += f" {stack_class}"
    return f'<div class="{classes}">{"".join(badges)}</div>'


def _battery_card_status_markup(device: dict[str, object], *, inline: bool = False) -> str:
    state = str(device.get("state", "unknown"))
    error_code = str(device.get("error_code") or "").strip() or None
    connected = bool(device.get("connected", True))
    kind = _status_kind(
        state,
        error_code,
        connected,
    )
    normalized = state.lower().strip()
    if normalized == "charging":
        label = "Charging"
        status_class = "charging"
        icon = (
            '<svg class="battery-card-status-icon" viewBox="0 0 20 20" fill="none" '
            'xmlns="http://www.w3.org/2000/svg" aria-label="Charging" role="img">'
            "<path d='M10 1.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 0 0 0-16.4Z' "
            "stroke='currentColor' stroke-width='1.8'/>"
            "<path d='M10.9 4.9 7.5 10h2.1l-.5 5 3.4-5.1h-2l.4-5Z' "
            "fill='currentColor'/>"
            "</svg>"
        )
    elif error_code == "device_not_found" or (normalized == "offline" and not connected):
        label = "Unable to connect"
        status_class = "error"
        icon = (
            '<svg class="battery-card-status-icon" viewBox="0 0 20 20" fill="none" '
            'xmlns="http://www.w3.org/2000/svg" aria-label="Unable to connect" role="img">'
            "<circle cx='10' cy='10' r='8.2' stroke='currentColor' stroke-width='1.8'/>"
            "<path d='M10 5.7v5.2' stroke='currentColor' stroke-width='2.1' "
            "stroke-linecap='round'/>"
            "<circle cx='10' cy='13.8' r='1.1' fill='currentColor'/>"
            "</svg>"
        )
    elif kind == "ok":
        label = "Battery OK"
        status_class = "ok"
        icon = (
            '<svg class="battery-card-status-icon" viewBox="0 0 20 20" fill="none" '
            'xmlns="http://www.w3.org/2000/svg" aria-label="Battery OK" role="img">'
            "<path d='M10 1.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 0 0 0-16.4Z' "
            "stroke='currentColor' stroke-width='1.8'/>"
            "<path d='m6.4 10.4 2.2 2.2 5-5' stroke='currentColor' stroke-width='2.1' "
            "stroke-linecap='round' stroke-linejoin='round'/>"
            "</svg>"
        )
    elif kind == "offline":
        label = "No recent sample"
        status_class = "offline"
        icon = (
            '<svg class="battery-card-status-icon" viewBox="0 0 20 20" fill="none" '
            'xmlns="http://www.w3.org/2000/svg" aria-label="No recent sample" role="img">'
            "<circle cx='10' cy='10' r='8.2' stroke='currentColor' stroke-width='1.8'/>"
            "<path d='M6.4 13.6 13.6 6.4' stroke='currentColor' stroke-width='2.1' "
            "stroke-linecap='round'/>"
            "</svg>"
        )
    else:
        label = state.replace("_", " ").title()
        status_class = kind
        icon = (
            '<svg class="battery-card-status-icon" viewBox="0 0 20 20" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg" aria-label="{html.escape(label)}" role="img">'
            "<circle cx='10' cy='10' r='8.2' stroke='currentColor' stroke-width='1.8'/>"
            "<path d='M10 5.7v5.2' stroke='currentColor' stroke-width='2.1' "
            "stroke-linecap='round'/>"
            "<circle cx='10' cy='13.8' r='1.1' fill='currentColor'/>"
            "</svg>"
        )
    classes = "battery-card-status"
    if inline:
        classes += " battery-card-status-inline"
    classes += f" {html.escape(status_class)}"
    return f'<div class="{classes}">{icon}<span>{html.escape(label)}</span></div>'


def _device_lookup_by_id(
    devices: list[dict[str, object]] | list[Device],
) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {}
    for device in devices:
        payload = device.to_dict() if isinstance(device, Device) else device
        if not isinstance(payload, dict):
            continue
        device_id = payload.get("id")
        if isinstance(device_id, str) and device_id:
            lookup[device_id] = payload
    return lookup


def _merge_snapshot_devices(
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
) -> list[dict[str, object]]:
    registry_by_id = _device_lookup_by_id(devices)
    merged: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    snapshot_devices = snapshot.get("devices", [])
    if isinstance(snapshot_devices, list):
        for runtime in snapshot_devices:
            if not isinstance(runtime, dict):
                continue
            device_id = str(runtime.get("id", ""))
            registry = registry_by_id.get(device_id, {})
            merged.append({**runtime, **registry})
            if device_id:
                seen_ids.add(device_id)
    if merged:
        for device in devices:
            device_id = str(device.get("id", ""))
            if device_id and device_id not in seen_ids:
                merged.append(device)
        return merged
    return devices


def _selected_attr(value: bool) -> str:
    return " selected" if value else ""


def _checked_attr(value: bool) -> str:
    return " checked" if value else ""


def _bool_from_form(form: dict[str, list[str]], key: str) -> bool:
    return form.get(key, [""])[0].lower() in {"1", "true", "on", "yes"}


def _string_from_form(form: dict[str, list[str]], key: str) -> str:
    return form.get(key, [""])[0].strip()


def _optional_float_from_form(form: dict[str, list[str]], key: str) -> float | None:
    raw = _string_from_form(form, key)
    if raw == "":
        return None
    return float(raw)


def _optional_int_from_form(form: dict[str, list[str]], key: str) -> int | None:
    raw = _string_from_form(form, key)
    if raw == "":
        return None
    return int(raw)


def _curve_field_name(percent: int) -> str:
    return f"custom_curve_{percent}"


def _curve_rows_html(
    curve_pairs: list[tuple[int, float]] | tuple[tuple[int, float], ...] | None = None,
) -> str:
    curve_map = dict(curve_pairs or default_curve_pairs())
    rows: list[str] = []
    for percent, default_voltage in default_curve_pairs():
        voltage = float(curve_map.get(percent, default_voltage))
        rows.append(
            "<div class='curve-grid-row'>"
            f"<label class='settings-label' for='{_curve_field_name(percent)}'>{percent}%</label>"
            f"<input id='{_curve_field_name(percent)}' type='number' step='0.01' min='0' "
            f"name='{_curve_field_name(percent)}' value='{voltage:.2f}'></div>"
        )
    return "".join(rows)


def _add_device_form_html(
    *,
    selected_color_key: str = "green",
    reserved_color_keys: set[str] | None = None,
) -> str:
    color_control_html = _color_key_control_html(
        selected_color_key=selected_color_key,
        reserved_color_keys=reserved_color_keys,
        control_id="device-color-input",
    )
    return (
        '<form id="add-device" method="post" action="/devices/add" class="two-column-grid" '
        'data-battery-config-form="true">'
        '<div><label class="settings-label" for="device-name-input">Name</label>'
        '<input id="device-name-input" type="text" name="device_name" '
        'autocomplete="off" placeholder="House Battery…" required></div>'
        '<div><label class="settings-label" for="device-type-input">Type</label>'
        '<select id="device-type-input" name="device_type" autocomplete="off">'
        '<option value="bm200">bm200</option>'
        '<option value="bm300pro">bm300pro</option></select></div>'
        '<div><label class="settings-label" '
        'for="installed-in-vehicle-input">Vehicle install</label>'
        f'<label class="settings-value" style="{TOGGLE_LABEL_STYLE}">'
        '<input id="installed-in-vehicle-input" type="checkbox" name="installed_in_vehicle">'
        "<span>Installed in a vehicle</span></label></div>"
        '<div data-vehicle-section><label class="settings-label" '
        'for="vehicle-type-input">Vehicle type</label>'
        f'<select id="vehicle-type-input" name="vehicle_type">{_vehicle_type_options()}</select>'
        "</div>"
        '<div><label class="settings-label" for="device-mac-input">MAC or serial</label>'
        '<input id="device-mac-input" type="text" name="device_mac" '
        'autocomplete="off" spellcheck="false" aria-describedby="device-mac-help" '
        'placeholder="A1B2C3D4E5F6…" required></div>'
        '<div id="device-mac-help" style="grid-column:1 / -1" class="muted-note">'
        "You can paste a compact 12-hex serial such as "
        "<code>A1B2C3D4E5F6</code>; the UI normalizes it to Bluetooth MAC format."
        "</div>"
        '<div class="battery-form-section" style="grid-column:1 / -1">'
        '<div><div class="settings-label">Battery Support</div>'
        "<div class='inline-field-help'>"
        "BM200, BM200 Pro, BM300, and BM300 Pro app families all expose "
        "lead-acid and lithium setup paths. Lead-acid supports regular, AGM, "
        "EFB, GEL, and custom. Lithium supports lithium and custom. Custom "
        "profiles can use the intelligent algorithm or a voltage-to-SoC curve. "
        "The gateway now generates the device ID automatically and assigns the "
        "visual badges from the battery and vehicle metadata you choose below."
        "</div></div>"
        '<div class="battery-form-grid">'
        "<div><label class='settings-label' for='device-color-input'>Overview color</label>"
        f"{color_control_html}"
        "</div>"
        "<div><label class='settings-label' for='battery-family-input'>Battery family</label>"
        f"<select id='battery-family-input' name='battery_family'>"
        f"{_battery_family_options()}</select></div>"
        "<div><label class='settings-label' for='battery-profile-input'>Battery profile</label>"
        f"<select id='battery-profile-input' name='battery_profile'>"
        f"{_battery_profile_options()}</select></div>"
        "<div data-custom-mode-section><label class='settings-label' "
        "for='custom-soc-mode-input'>Custom battery mode</label>"
        f"<select id='custom-soc-mode-input' name='custom_soc_mode'>"
        f"{_custom_mode_options()}</select></div>"
        "</div>"
        '<div class="battery-form-grid">'
        '<div><label class="settings-label" for="battery-brand-input">Battery brand</label>'
        '<input id="battery-brand-input" type="text" name="battery_brand" '
        'autocomplete="off" placeholder="Varta, Bosch, Yuasa…"></div>'
        '<div><label class="settings-label" for="battery-model-input">Battery model</label>'
        '<input id="battery-model-input" type="text" name="battery_model" '
        'autocomplete="off" placeholder="Blue Dynamic E44…"></div>'
        '<div><label class="settings-label" for="battery-voltage-input">Battery voltage</label>'
        '<select id="battery-voltage-input" name="battery_nominal_voltage">'
        f"{_battery_nominal_voltage_options()}</select></div>"
        '<div><label class="settings-label" for="battery-capacity-input">Capacity (Ah)</label>'
        '<input id="battery-capacity-input" type="number" step="0.1" min="0" '
        'name="battery_capacity_ah" inputmode="decimal" placeholder="95"></div>'
        '<div><label class="settings-label" for="battery-year-input">Production year</label>'
        '<input id="battery-year-input" type="number" min="1950" max="2100" '
        'name="battery_production_year" inputmode="numeric" placeholder="2025"></div>'
        "</div>"
        "<div data-custom-curve-section>"
        '<div class="settings-label">Voltage corresponding to power</div>'
        "<div class='inline-field-help'>"
        "This mirrors the official-app custom battery flow. Edit the per-10% "
        "thresholds if you want a manual SoC curve instead of the intelligent "
        "algorithm.</div>"
        f'<div class="curve-grid">{_curve_rows_html()}</div>'
        "</div>"
        "</div>"
        '<div style="grid-column:1 / -1">'
        f"{button('Add Device and Enable Live Polling', kind='primary')}"
        "</div>"
        "</form>"
    )


def _battery_family_options(*, selected_family: str = "lead_acid") -> str:
    return "".join(
        f"<option value='{html.escape(value)}'"
        f"{_selected_attr(value == selected_family)}>"
        f"{html.escape(label)}</option>"
        for value, label in BATTERY_FAMILIES.items()
    )


def _battery_profile_options(*, selected_profile: str = "regular_lead_acid") -> str:
    entries = [("lead_acid", value, label) for value, label in LEAD_ACID_PROFILES.items()] + [
        ("lithium", value, label) for value, label in LITHIUM_PROFILES.items()
    ]
    return "".join(
        f"<option value='{html.escape(value)}' data-family='{html.escape(family)}'"
        f"{_selected_attr(value == selected_profile)}>"
        f"{html.escape(label)}</option>"
        for family, value, label in entries
    )


def _vehicle_type_options(*, selected_vehicle_type: str = "") -> str:
    options = [
        "<option value=''>Select vehicle type</option>",
        *(
            f"<option value='{html.escape(value)}'{_selected_attr(value == selected_vehicle_type)}>"
            f"{html.escape(label)}</option>"
            for value, label in VEHICLE_TYPES.items()
        ),
    ]
    return "".join(options)


def _custom_mode_options(*, selected_mode: str = "intelligent_algorithm") -> str:
    return "".join(
        f"<option value='{html.escape(value)}'"
        f"{_selected_attr(value == selected_mode)}>"
        f"{html.escape(label)}</option>"
        for value, label in CUSTOM_SOC_MODES.items()
    )


def _color_key_options(
    *,
    selected_color_key: str,
    reserved_color_keys: set[str] | None = None,
) -> str:
    reserved = reserved_color_keys or set()
    return "".join(
        (
            f"<option value='{html.escape(value)}'"
            f"{_selected_attr(value == selected_color_key)}"
            + ("" if value == selected_color_key or value not in reserved else " disabled")
            + f">{html.escape(label)}</option>"
        )
        for value, label in COLOR_CATALOG.items()
    )


def _color_key_control_html(
    *,
    selected_color_key: str,
    reserved_color_keys: set[str] | None,
    control_id: str,
) -> str:
    resolved_color_key = selected_color_key if selected_color_key in COLOR_CATALOG else "green"
    safe_color_key = html.escape(resolved_color_key)
    return (
        '<div class="select-with-preview">'
        f'<span class="color-preview-dot {safe_color_key}" aria-hidden="true"></span>'
        f"<select id='{html.escape(control_id)}' name='color_key' data-color-preview-source='true'>"
        + _color_key_options(
            selected_color_key=selected_color_key,
            reserved_color_keys=reserved_color_keys,
        )
        + "</select></div>"
    )


def _battery_nominal_voltage_options(*, selected_voltage: int | None = None) -> str:
    options = ["<option value=''>Select nominal voltage</option>"]
    for value in (6, 12, 24, 48):
        options.append(
            f"<option value='{value}'{_selected_attr(value == selected_voltage)}>{value} V</option>"
        )
    return "".join(options)


TOGGLE_LABEL_STYLE = "display:flex;justify-content:flex-start;gap:0.55rem;align-items:center"


def _battery_form_script() -> str:
    return """
<script>
(() => {
  function normalizeMacLikeValue(value) {
    const raw = value.replace(/[^0-9a-f]/gi, "").toUpperCase();
    if (raw.length === 12) {
      return raw.match(/.{1,2}/g).join(":");
    }
    return value.trim().toUpperCase();
  }

  const forms = document.querySelectorAll("[data-battery-config-form='true']");
  for (const form of forms) {
    const familySelect = form.querySelector("[name='battery_family']");
    const profileSelect = form.querySelector("[name='battery_profile']");
    const modeSelect = form.querySelector("[name='custom_soc_mode']");
    const installedInVehicle = form.querySelector("[name='installed_in_vehicle']");
    const macInput = form.querySelector("[name='device_mac']");
    const vehicleSection = form.querySelector("[data-vehicle-section]");
    const modeSection = form.querySelector("[data-custom-mode-section]");
    const curveSection = form.querySelector("[data-custom-curve-section]");
    const colorSelect = form.querySelector("[data-color-preview-source='true']");
    const colorPreview = form.querySelector(".color-preview-dot");
    if (!familySelect || !profileSelect || !modeSelect || !modeSection || !curveSection) {
      continue;
    }

    function syncProfileOptions() {
      const family = familySelect.value;
      let selectedVisible = false;
      for (const option of profileSelect.options) {
        const visible = option.dataset.family === family;
        option.hidden = !visible;
        option.disabled = !visible;
        if (visible && option.value === profileSelect.value) {
          selectedVisible = true;
        }
      }
      if (!selectedVisible) {
        const fallback = Array.from(profileSelect.options).find((option) => !option.hidden);
        if (fallback) {
          profileSelect.value = fallback.value;
        }
      }
    }

    function syncCustomSections() {
      const isCustom = profileSelect.value === "custom";
      modeSection.hidden = !isCustom;
      const showCurve = isCustom && modeSelect.value === "voltage_corresponding_power";
      curveSection.hidden = !showCurve;
    }

    function syncVehicleSection() {
      if (!vehicleSection || !installedInVehicle) {
        return;
      }
      vehicleSection.hidden = !installedInVehicle.checked;
    }

    function syncColorPreview() {
      if (!colorSelect || !colorPreview) {
        return;
      }
      colorPreview.className = "color-preview-dot " + colorSelect.value;
    }

    function syncAll() {
      syncProfileOptions();
      syncCustomSections();
      syncVehicleSection();
      syncColorPreview();
    }

    familySelect.addEventListener("change", syncAll);
    profileSelect.addEventListener("change", syncCustomSections);
    modeSelect.addEventListener("change", syncCustomSections);
    if (installedInVehicle) {
      installedInVehicle.addEventListener("change", syncVehicleSection);
    }
    if (colorSelect) {
      colorSelect.addEventListener("change", syncColorPreview);
    }
    if (macInput) {
      macInput.addEventListener("blur", () => {
        macInput.value = normalizeMacLikeValue(macInput.value);
      });
      form.addEventListener("submit", () => {
        macInput.value = normalizeMacLikeValue(macInput.value);
      });
    }
    syncAll();
  }
})();
</script>
"""


def _parse_custom_curve_from_form(form: dict[str, list[str]]) -> tuple[tuple[int, float], ...]:
    rows: list[tuple[int, float]] = []
    for percent, default_voltage in default_curve_pairs():
        raw_value = form.get(_curve_field_name(percent), [f"{default_voltage:.2f}"])[0]
        value = float(raw_value)
        rows.append((percent, value))
    return tuple(rows)


def _storage_rows(summary: dict[str, object], *, device_ids: set[str] | None = None) -> str:
    rows: list[str] = []
    devices = cast(list[object], summary.get("devices", []))
    for device in devices:
        if not isinstance(device, dict):
            continue
        device_id = str(device.get("device_id", ""))
        if device_ids is not None and device_id not in device_ids:
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(device_id)}</td>"
            f"<td>{html.escape(str(device.get('raw_samples', 0)))}</td>"
            f"<td>{html.escape(str(device.get('raw_first_ts', '-')))}</td>"
            f"<td>{html.escape(str(device.get('raw_last_ts', '-')))}</td>"
            f"<td>{html.escape(str(device.get('daily_days', 0)))}</td>"
            f"<td>{html.escape(str(device.get('daily_first_day', '-')))}</td>"
            f"<td>{html.escape(str(device.get('daily_last_day', '-')))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='7'>No persisted history</td></tr>"


def _status_kind(state: str, error_code: str | None = None, connected: bool = True) -> str:
    normalized = state.lower()
    if not connected or error_code == "device_not_found" or normalized == "offline":
        return "offline"
    if error_code is not None or normalized in {"error", "critical"}:
        return "error"
    if normalized in {"warning", "degraded", "timeout"}:
        return "warning"
    return "ok"


def _status_label(state: str, *, connected: bool, error_code: str | None) -> str:
    normalized = state.lower().strip()
    if error_code == "device_not_found":
        return "Unable to connect"
    if not connected or normalized == "offline":
        return "Offline"
    if normalized == "charging":
        return "Charging"
    if normalized == "floating":
        return "Floating"
    if normalized == "critical":
        return "Critical"
    if normalized == "low":
        return "Low"
    if normalized == "normal":
        return "Normal"
    if normalized == "unsupported":
        return "Unsupported"
    if normalized == "disabled":
        return "Disabled"
    if normalized == "error" or error_code is not None:
        return "Error"
    return normalized.replace("_", " ").title() or "Unknown"


def _status_visual_tone(state: str, *, connected: bool, error_code: str | None) -> str:
    normalized = state.lower().strip()
    if normalized == "charging":
        return "info"
    if normalized == "floating":
        return "purple"
    return _status_kind(normalized, error_code=error_code, connected=connected)


def _status_scale_markup(
    *,
    current_state: str,
    connected: bool,
    error_code: str | None,
) -> str:
    normalized = current_state.lower().strip()
    labels = [item[0] for item in PROTOCOL_STATUS_SCALE]
    active_index: int | None
    try:
        active_index = labels.index(normalized)
    except ValueError:
        active_index = None
    tone = _status_visual_tone(normalized, connected=connected, error_code=error_code)
    state_label = _status_label(normalized, connected=connected, error_code=error_code)
    active_segment_html = ""
    if active_index is not None:
        segment_width = 100.0 / len(PROTOCOL_STATUS_SCALE)
        segment_left = active_index * segment_width
        active_segment_html = (
            '<div class="status-scale-active-segment '
            f'tone-{html.escape(tone)}" style="left:{segment_left:.1f}%;'
            f'width:{segment_width:.1f}%"></div>'
        )
    divider_html_parts: list[str] = []
    region_html_parts: list[str] = []
    region_width = 100.0 / len(PROTOCOL_STATUS_SCALE)
    for index, (_key, label, description, segment_tone) in enumerate(PROTOCOL_STATUS_SCALE):
        region_left = index * region_width
        active_class = " active" if active_index == index else ""
        region_html_parts.append(
            '<div class="status-scale-region '
            f'tone-{html.escape(segment_tone)}{active_class}" tabindex="0" '
            f'style="left:{region_left:.1f}%;width:{region_width:.1f}%;" '
            f'data-label="{html.escape(label)}" '
            f'aria-label="Status range: {html.escape(label)}. {html.escape(description)}">'
            f'<span class="status-scale-label">{html.escape(label)}</span>'
            "</div>"
        )
    for index in range(len(PROTOCOL_STATUS_SCALE) - 1):
        divider_percent = ((index + 1) / len(PROTOCOL_STATUS_SCALE)) * 100.0
        divider_html_parts.append(
            f'<div class="status-scale-divider" style="left:{divider_percent:.1f}%"></div>'
        )
    divider_html = "".join(divider_html_parts)
    region_html = "".join(region_html_parts)
    scale_order = ", ".join(item[1] for item in PROTOCOL_STATUS_SCALE)
    return (
        '<div class="status-scale" role="img" '
        f'aria-label="BM200/BM6 protocol state order: {html.escape(scale_order)}. '
        f'Current state: {html.escape(state_label)}.">'
        '<div class="status-scale-track">'
        f"{active_segment_html}"
        f"{region_html}"
        f"{divider_html}"
        "</div>"
        "</div>"
    )


def _soc_progress_markup(*, soc_value: object, accent_css: str) -> str:
    soc_percent = min(max(_coerce_float(soc_value, 0.0), 0.0), 100.0)
    soc_text = html.escape(_format_number(soc_percent, digits=0, suffix="%"))
    return (
        '<div class="soc-progress">'
        '<div class="soc-progress-header">'
        '<span class="settings-label">State of Charge</span>'
        f'<span class="soc-progress-value">{soc_text}</span>'
        "</div>"
        '<div class="soc-progress-track">'
        f'<div class="soc-progress-fill" style="width:{soc_percent:.1f}%; '
        f'background:{html.escape(accent_css)}"></div>'
        "</div>"
        "</div>"
    )


def _device_status_explainer(
    summary: dict[str, object], *, accent_css: str = "var(--accent-green)"
) -> str:
    state = str(summary.get("state", "unknown"))
    connected = bool(summary.get("connected", False))
    error_code = cast(str | None, summary.get("error_code"))
    error_detail = str(summary.get("error_detail", "") or "").strip()
    normalized = state.lower().strip()
    protocol_item = next((item for item in PROTOCOL_STATUS_SCALE if item[0] == normalized), None)
    label = _status_label(state, connected=connected, error_code=error_code)
    kind = _status_kind(state, error_code=error_code, connected=connected)
    voltage = _format_number(summary.get("voltage"), digits=2, suffix=" V")
    temperature = _format_number(summary.get("temperature"), digits=1, suffix=" C")
    scale_html = ""
    description = "Gateway runtime state."
    summary_badge_html = ""
    if protocol_item is not None:
        description = protocol_item[2]
        scale_html = _status_scale_markup(
            current_state=normalized,
            connected=connected,
            error_code=error_code,
        )
    elif error_detail:
        description = error_detail
        summary_badge_html = status_badge(label, kind=kind)
    else:
        summary_badge_html = status_badge(label, kind=kind)
    chips: list[str] = []
    latest_sample = _display_timestamp(summary.get("last_seen", "unknown"))
    chips.append(f"<span class='pill-chip'>Latest sample {latest_sample}</span>")
    chips.append(f"<span class='pill-chip'>Voltage {html.escape(voltage)}</span>")
    if temperature != "-":
        chips.append(f"<span class='pill-chip'>Temperature {html.escape(temperature)}</span>")
    chips_html = "".join(chips)
    soc_progress_html = _soc_progress_markup(soc_value=summary.get("soc"), accent_css=accent_css)
    return (
        '<div class="status-explainer">'
        '<div class="status-explainer-summary">'
        "<div>"
        "<div class='settings-label'>Reported Status</div>"
        "</div>"
        f"{summary_badge_html}"
        "</div>"
        '<div class="status-explainer-body">'
        f"{scale_html}"
        "<p class='status-explainer-copy'><strong>What it means:</strong> "
        f"{html.escape(description)}</p>"
        f"{soc_progress_html}"
        f"<div class='chip-grid status-chip-grid'>{chips_html}</div>"
        "</div>"
        "</div>"
    )


def _format_number(value: object, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        formatted = f"{float(value):.{digits}f}" if digits > 0 else f"{int(round(float(value)))}"
        return f"{formatted}{suffix}"
    return f"{value}{suffix}"


def _signal_quality(
    *,
    rssi: object,
    connected: bool,
    error_code: str | None,
) -> tuple[str, int, int, str]:
    if not connected or error_code == "device_not_found" or rssi is None:
        return (
            "No recent sample",
            0,
            0,
            "The adapter did not see this monitor in the latest scan.",
        )
    rssi_value = int(_coerce_float(rssi))
    percent = round(((rssi_value + 100) / 50) * 100)
    percent = max(0, min(100, percent))
    if percent >= 85:
        grade = "Excellent"
    elif percent >= 55:
        grade = "Good"
    elif percent >= 35:
        grade = "Fair"
    else:
        grade = "Weak"
    bars = max(1, min(4, (percent + 24) // 25))
    return (grade, percent, bars, f"RSSI {rssi_value} dBm")


def _signal_quality_detail_html(
    *,
    rssi: object,
    connected: bool,
    error_code: str | None,
) -> str:
    grade, percent, bars, rssi_text = _signal_quality(
        rssi=rssi,
        connected=connected,
        error_code=error_code,
    )
    bars_markup = "".join(
        "<span class='active'></span>" if index < bars else "<span></span>" for index in range(4)
    )
    return (
        '<div class="metric-detail-stack">'
        '<div class="signal-quality-row">'
        f"<span>{percent}%</span>"
        f"<span class='signal-bars' aria-label='{html.escape(grade)} {percent}% signal strength'>"
        f"{bars_markup}</span>"
        "</div>"
        f"<div class='subvalue'>{html.escape(rssi_text)}</div>"
        "</div>"
    )


def _device_runtime_summary(runtime: dict[str, object]) -> tuple[str, str]:
    error_code = str(runtime.get("error_code") or "")
    if error_code == "device_not_found":
        return "Offline", "No BLE advertisement seen during the latest scan window."
    if error_code == "timeout":
        return "Timeout", "The device was visible but did not return a reading in time."
    if error_code == "protocol_error":
        return "Protocol", str(runtime.get("error_detail") or "Protocol mismatch")
    if error_code:
        return "Error", str(runtime.get("error_detail") or error_code.replace("_", " "))

    state = str(runtime.get("state", "configured")).replace("_", " ").title()
    if bool(runtime.get("connected")):
        last_seen = runtime.get("last_seen")
        if last_seen:
            return state, f"Last seen {last_seen}"
        return state, "Latest runtime sample"
    return state, "Waiting for runtime data"


def _chart_points(
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    *,
    series: str = "Series",
    series_color: str = "#4f8df7",
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for row in sorted(daily_history, key=lambda item: str(item.get("day", ""))):
        samples = row.get("samples")
        avg_voltage = row.get("avg_voltage")
        avg_soc = row.get("avg_soc")
        if not isinstance(samples, (int, float)) or float(samples) <= 0:
            continue
        if not isinstance(avg_voltage, (int, float)) or float(avg_voltage) <= 0:
            continue
        last_seen = str(row.get("last_seen") or "").strip()
        point_ts = last_seen or f"{row.get('day', '')}T12:00:00"
        points.append(
            {
                "ts": point_ts,
                "label": str(row.get("day", ""))[5:],
                "kind": "daily",
                "voltage": avg_voltage,
                "soc": avg_soc,
                "temperature": row.get("avg_temperature"),
                "series": series,
                "series_color": series_color,
            }
        )
    for row in sorted(raw_history, key=lambda item: str(item.get("ts", ""))):
        if row.get("error_code") is not None:
            continue
        voltage = row.get("voltage")
        soc = row.get("soc")
        temperature = row.get("temperature")
        has_metric = (
            isinstance(voltage, (int, float))
            and float(voltage) > 0
            or isinstance(soc, (int, float))
            or isinstance(temperature, (int, float))
        )
        if not has_metric:
            continue
        points.append(
            {
                "ts": row.get("ts"),
                "label": str(row.get("ts", ""))[11:16],
                "kind": "raw",
                "voltage": voltage,
                "soc": soc,
                "temperature": temperature,
                "series": series,
                "series_color": series_color,
            }
        )
    return points


def _fleet_chart_points(
    *,
    database_path: Path,
    devices: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[tuple[str, str]]]:
    points: list[dict[str, object]] = []
    legend: list[tuple[str, str]] = []
    for index, device in enumerate(devices):
        device_id = str(device.get("id", ""))
        if not device_id:
            continue
        device_name = str(device.get("name", device_id))
        color = _device_accent_color(device, fallback_index=index)
        legend.append((device_name, color))
        points.extend(
            _chart_points(
                fetch_recent_history(
                    database_path,
                    device_id=device_id,
                    limit=RECENT_CHART_HISTORY_LIMIT,
                ),
                fetch_daily_history(database_path, device_id=device_id, limit=730),
                series=device_name,
                series_color=color,
            )
        )
    return points, legend


def _history_summary(raw_history: list[dict[str, object]]) -> dict[str, str]:
    valid_rows = [
        row
        for row in raw_history
        if row.get("error_code") is None and isinstance(row.get("voltage"), (int, float))
    ]
    error_rows = [row for row in raw_history if row.get("error_code") is not None]
    soc_rows = [row for row in valid_rows if isinstance(row.get("soc"), (int, float))]
    valid_count = len(valid_rows)
    error_count = len(error_rows)
    avg_voltage = (
        sum(float(cast(float | int, row["voltage"])) for row in valid_rows) / valid_count
        if valid_count
        else None
    )
    avg_soc = (
        sum(float(cast(float | int, row["soc"])) for row in soc_rows) / len(soc_rows)
        if soc_rows
        else None
    )
    return {
        "valid_samples": str(valid_count),
        "error_count": str(error_count),
        "avg_voltage": _format_number(avg_voltage, digits=2, suffix=" V"),
        "avg_soc": _format_number(avg_soc, digits=0, suffix="%"),
    }


def _device_summary_from_history(
    *,
    device_id: str,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    device_summary: dict[str, object] | None,
) -> dict[str, object]:
    if device_summary is not None:
        return device_summary
    latest_raw = raw_history[0] if raw_history else {}
    latest_daily = daily_history[0] if daily_history else {}
    return {
        "name": device_id,
        "soc": latest_raw.get("soc", latest_daily.get("avg_soc", 0)),
        "voltage": latest_raw.get("voltage", latest_daily.get("avg_voltage", 0.0)),
        "temperature": latest_raw.get("temperature"),
        "rssi": None,
        "state": latest_raw.get("state", "unknown"),
        "error_code": latest_raw.get("error_code"),
        "last_seen": latest_raw.get("ts", latest_daily.get("last_seen", "unknown")),
        "connected": latest_raw.get("error_code") is None,
    }


def _primary_device_id(
    snapshot: dict[str, object],
    devices: list[Device] | list[dict[str, object]],
) -> str:
    snapshot_devices = snapshot.get("devices", [])
    if isinstance(snapshot_devices, list):
        for device in snapshot_devices:
            if isinstance(device, dict) and isinstance(device.get("id"), str):
                return cast(str, device["id"])
    for device in devices:
        if isinstance(device, Device):
            return device.id
        if isinstance(device, dict) and isinstance(device.get("id"), str):
            return cast(str, device["id"])
    return ""


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _display_timestamp(value: object) -> str:
    raw = str(value) if value is not None else "unknown"
    return raw.replace("T", " ").rsplit("+", maxsplit=1)[0]


def render_management_html(
    *,
    snapshot: dict[str, object],
    config: AppConfig,
    storage_summary: dict[str, object],
    devices: list[dict[str, object]],
    config_text: str,
    devices_text: str,
    contract: dict[str, object],
    message: str = "",
    theme_preference: str = "system",
    language: str | None = None,
) -> str:
    from .web_pages_settings import render_management_html as _render_management_html

    return _render_management_html(
        snapshot=snapshot,
        config=config,
        storage_summary=storage_summary,
        devices=devices,
        config_text=config_text,
        devices_text=devices_text,
        contract=contract,
        message=message,
        theme_preference=theme_preference,
        language=language,
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
    from .web_pages_home import render_home_html as _render_home_html

    return _render_home_html(
        snapshot=snapshot,
        devices=devices,
        chart_points=chart_points,
        legend=legend,
        show_chart_markers=show_chart_markers,
        visible_device_limit=visible_device_limit,
        appearance=appearance,
        default_chart_range=default_chart_range,
        default_chart_metric=default_chart_metric,
        language=language,
    )


def render_diagnostics_html(
    *,
    theme_preference: str = "system",
    fleet_trend_metrics: tuple[str, ...] = ("soc",),
    language: str = "en",
) -> str:
    from .web_pages_frame import render_diagnostics_html as _render_diagnostics_html

    return _render_diagnostics_html(
        theme_preference=theme_preference,
        fleet_trend_metrics=fleet_trend_metrics,
        language=language,
    )


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
    from .web_pages_frame import render_frame_fleet_trend_html as _render_frame_fleet_trend_html

    return _render_frame_fleet_trend_html(
        chart_points=chart_points,
        legend=legend,
        show_chart_markers=show_chart_markers,
        appearance=appearance,
        default_chart_range=default_chart_range,
        default_chart_metric=default_chart_metric,
        width=width,
        height=height,
        language=language,
    )


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
    from .web_pages_frame import (
        render_frame_battery_overview_html as _render_frame_battery_overview_html,
    )

    return _render_frame_battery_overview_html(
        snapshot=snapshot,
        devices=devices,
        page=page,
        devices_per_page=devices_per_page,
        appearance=appearance,
        width=width,
        height=height,
        language=language,
    )


def render_devices_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    message: str = "",
    theme_preference: str = "system",
    language: str = "en",
) -> str:
    from .web_pages_devices import render_devices_html as _render_devices_html

    return _render_devices_html(
        snapshot=snapshot,
        devices=devices,
        message=message,
        theme_preference=theme_preference,
        language=language,
    )


def render_add_device_html(
    *,
    message: str = "",
    theme_preference: str = "system",
    selected_color_key: str = "green",
    reserved_color_keys: set[str] | None = None,
    language: str = "en",
) -> str:
    from .web_pages_devices import render_add_device_html as _render_add_device_html

    return _render_add_device_html(
        message=message,
        theme_preference=theme_preference,
        selected_color_key=selected_color_key,
        reserved_color_keys=reserved_color_keys,
        language=language,
    )


def render_edit_device_html(
    *,
    device: dict[str, object],
    message: str = "",
    theme_preference: str = "system",
    reserved_color_keys: set[str] | None = None,
    original_device_id: str | None = None,
    language: str = "en",
) -> str:
    from .web_pages_devices import render_edit_device_html as _render_edit_device_html

    return _render_edit_device_html(
        device=device,
        message=message,
        theme_preference=theme_preference,
        reserved_color_keys=reserved_color_keys,
        original_device_id=original_device_id,
        language=language,
    )


def render_settings_html(
    *,
    config: AppConfig,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    edit_mode: bool = False,
    message: str = "",
    storage_summary: dict[str, object] | None = None,
    config_text: str | None = None,
    devices_text: str | None = None,
    contract: dict[str, object] | None = None,
    detected_bluetooth_adapters: list[dict[str, str]] | None = None,
    usb_otg_device_controller_detected: bool | None = None,
    usb_otg_boot_mode_prepared: bool | None = None,
    usb_otg_support_installed: bool | None = None,
    theme_preference: str = "system",
    language: str | None = None,
) -> str:
    from .web_pages_settings import render_settings_html as _render_settings_html

    return _render_settings_html(
        config=config,
        snapshot=snapshot,
        devices=devices,
        edit_mode=edit_mode,
        message=message,
        storage_summary=storage_summary,
        config_text=config_text,
        devices_text=devices_text,
        contract=contract,
        detected_bluetooth_adapters=detected_bluetooth_adapters,
        usb_otg_device_controller_detected=usb_otg_device_controller_detected,
        usb_otg_boot_mode_prepared=usb_otg_boot_mode_prepared,
        usb_otg_support_installed=usb_otg_support_installed,
        theme_preference=theme_preference,
        language=language,
    )


def render_reboot_pending_html(*, theme_preference: str = "system", language: str = "en") -> str:
    from .web_pages_settings import render_reboot_pending_html as _render_reboot_pending_html

    return _render_reboot_pending_html(theme_preference=theme_preference, language=language)


def render_usb_otg_export_pending_html(
    *, theme_preference: str = "system", language: str = "en"
) -> str:
    from .web_pages_settings import (
        render_usb_otg_export_pending_html as _render_usb_otg_export_pending_html,
    )

    return _render_usb_otg_export_pending_html(
        theme_preference=theme_preference,
        language=language,
    )


def render_shutdown_pending_html(*, theme_preference: str = "system", language: str = "en") -> str:
    from .web_pages_settings import render_shutdown_pending_html as _render_shutdown_pending_html

    return _render_shutdown_pending_html(theme_preference=theme_preference, language=language)


def render_device_html(
    *,
    device_id: str,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
    yearly_history: list[dict[str, object]],
    analytics: dict[str, object],
    device_summary: dict[str, object] | None = None,
    show_chart_markers: bool = False,
    theme_preference: str = "system",
    default_chart_range: str = "7",
    default_chart_metric: str = "soc",
    language: str = "en",
) -> str:
    from .web_pages_history import render_device_html as _render_device_html

    return _render_device_html(
        device_id=device_id,
        raw_history=raw_history,
        daily_history=daily_history,
        monthly_history=monthly_history,
        yearly_history=yearly_history,
        analytics=analytics,
        device_summary=device_summary,
        show_chart_markers=show_chart_markers,
        theme_preference=theme_preference,
        default_chart_range=default_chart_range,
        default_chart_metric=default_chart_metric,
        language=language,
    )


def render_history_html(
    *,
    device_id: str,
    configured_devices: list[dict[str, object]],
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
    show_chart_markers: bool = False,
    theme_preference: str = "system",
    default_chart_range: str = "7",
    default_chart_metric: str = "soc",
    language: str = "en",
) -> str:
    from .web_pages_history import render_history_html as _render_history_html

    return _render_history_html(
        device_id=device_id,
        configured_devices=configured_devices,
        raw_history=raw_history,
        daily_history=daily_history,
        monthly_history=monthly_history,
        show_chart_markers=show_chart_markers,
        theme_preference=theme_preference,
        default_chart_range=default_chart_range,
        default_chart_metric=default_chart_metric,
        language=language,
    )


def _parse_history_limit(values: list[str], *, default: int) -> int:
    raw_limit = values[0] if values else str(default)
    limit = int(raw_limit)
    if limit <= 0:
        raise ValueError("limit must be positive")
    return limit
