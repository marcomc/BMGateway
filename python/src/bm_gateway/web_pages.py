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
    api_chip,
    app_document,
    banner_strip,
    button,
    chart_card,
    chart_script,
    device_icon,
    metric_tile,
    section_card,
    settings_control_row,
    settings_row,
    status_badge,
    summary_card,
    tone_card,
    top_header,
)

PROTOCOL_STATE_CODES: dict[str, int] = {
    "critical": 0,
    "low": 1,
    "normal": 2,
    "charging": 4,
    "floating": 8,
}

PROTOCOL_STATUS_SCALE: tuple[tuple[str, str, str, str], ...] = (
    ("critical", "Critical", "Critical reserve or alarm condition.", "error"),
    ("low", "Low", "Low reserve reported by the monitor.", "warning"),
    ("normal", "Normal", "Stable battery condition reported by the monitor.", "ok"),
    ("charging", "Charging", "Active charging reported by the monitor.", "info"),
    ("floating", "Floating", "Maintenance / float charge reported by the monitor.", "purple"),
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
            subtitle="Add a battery monitor before using the history dashboard.",
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
        subtitle="Switch the history surface between configured batteries.",
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
        f'<div class="{gauge_class}" style="background: conic-gradient(var(--accent-green) '
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
    return 3, 2


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
    classes = ["battery-overview-page"]
    if is_single_page:
        classes.append("is-single-page")
    if card_count <= 1:
        classes.append("page-one-card")
    elif card_count == 2:
        classes.append("page-two-cards")
    else:
        classes.append("page-multi-cards")
    return " ".join(classes)


def _battery_overview_script(track_id: str) -> str:
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
  const pages = Array.from(track.querySelectorAll(".battery-overview-page"));
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
    snapshot = _snapshot_with_version(snapshot)
    devices = snapshot.get("devices", [])
    device_items = []
    for device in devices if isinstance(devices, list) else []:
        if not isinstance(device, dict):
            continue
        device_items.append(
            "<tr>"
            f"<td>{html.escape(str(device.get('name')))}</td>"
            f"<td>{html.escape(str(device.get('type')))}</td>"
            f"<td>{html.escape(str(device.get('voltage')))}</td>"
            f"<td>{html.escape(str(device.get('soc')))}</td>"
            f"<td>{html.escape(str(device.get('connected')))}</td>"
            f"<td>{html.escape(str(device.get('rssi')))}</td>"
            "</tr>"
        )

    rows = "\n".join(device_items) or "<tr><td colspan='6'>No devices</td></tr>"
    gateway_name = html.escape(str(snapshot.get("gateway_name", "unknown")))
    adapter = html.escape(str(snapshot.get("active_adapter", "unknown")))
    devices_online = html.escape(str(snapshot.get("devices_online", 0)))
    devices_total = html.escape(str(snapshot.get("devices_total", 0)))
    mqtt_connected = html.escape(str(snapshot.get("mqtt_connected", False)))
    generated_at = html.escape(str(snapshot.get("generated_at", "unknown")))
    version_label = html.escape(str(snapshot.get("display_version", __version__)))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>BMGateway Status</title>
    <style>
      body {{ font-family: sans-serif; margin: 2rem; background: #f6f7f9; color: #111; }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1rem;
        margin-bottom: 2rem;
      }}
      .card {{
        background: white;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      }}
      table {{ width: 100%; border-collapse: collapse; background: white; }}
      th, td {{ padding: 0.75rem; border-bottom: 1px solid #ddd; text-align: left; }}
      code {{ background: #eef1f5; padding: 0.125rem 0.375rem; border-radius: 6px; }}
    </style>
  </head>
  <body>
    <h1>BMGateway</h1>
    <p>Generated at <code>{generated_at}</code></p>
    <p>Version <code>{version_label}</code></p>
    <div class="grid">
      <div class="card"><strong>Gateway</strong><br>{gateway_name}</div>
      <div class="card"><strong>Adapter</strong><br>{adapter}</div>
      <div class="card"><strong>Devices</strong><br>{devices_online} / {devices_total}</div>
      <div class="card"><strong>MQTT</strong><br>{mqtt_connected}</div>
    </div>
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Voltage</th>
          <th>SoC</th>
          <th>Connected</th>
          <th>RSSI</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </body>
</html>
"""


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
    capacity = battery_table.get("capacity_ah")
    year = battery_table.get("production_year")
    if capacity not in (None, ""):
        parts.append(f"{capacity} Ah")
    if year not in (None, ""):
        parts.append(str(year))
    summary = " · ".join(part for part in parts if part)
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
    return "Bench / stationary battery"


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
    kind = _status_kind(
        state,
        cast(str | None, device.get("error_code")),
        bool(device.get("connected", True)),
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
    snapshot_devices = snapshot.get("devices", [])
    if isinstance(snapshot_devices, list):
        for runtime in snapshot_devices:
            if not isinstance(runtime, dict):
                continue
            device_id = str(runtime.get("id", ""))
            registry = registry_by_id.get(device_id, {})
            merged.append({**registry, **runtime})
    if merged:
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


def _storage_rows(summary: dict[str, object]) -> str:
    rows: list[str] = []
    devices = cast(list[object], summary.get("devices", []))
    for device in devices:
        if not isinstance(device, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(device.get('device_id', '')))}</td>"
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
    if not connected or error_code == "device_not_found" or normalized == "offline":
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
    fill_html = ""
    marker_html = ""
    if active_index is not None:
        marker_percent = ((active_index + 0.5) / len(PROTOCOL_STATUS_SCALE)) * 100.0
        fill_width = f"{marker_percent:.1f}%"
        fill_html = (
            '<div class="status-scale-fill '
            f'tone-{html.escape(tone)}" style="width:{fill_width}"></div>'
        )
        marker_html = (
            f'<div class="status-scale-marker tone-{html.escape(tone)}" '
            f'style="left:{marker_percent:.1f}%"></div>'
        )
    divider_html_parts: list[str] = []
    for index in range(len(PROTOCOL_STATUS_SCALE) - 1):
        divider_percent = ((index + 1) / len(PROTOCOL_STATUS_SCALE)) * 100.0
        divider_html_parts.append(
            f'<div class="status-scale-divider" style="left:{divider_percent:.1f}%"></div>'
        )
    divider_html = "".join(divider_html_parts)
    scale_order = ", ".join(item[1] for item in PROTOCOL_STATUS_SCALE)
    return (
        '<div class="status-scale" role="img" '
        f'aria-label="BM200/BM6 protocol state order: {html.escape(scale_order)}. '
        f'Current state: {html.escape(state_label)}.">'
        '<div class="status-scale-track">'
        f"{fill_html}"
        f"{divider_html}"
        f"{marker_html}"
        "</div>"
        "</div>"
    )


def _device_status_explainer(summary: dict[str, object]) -> str:
    state = str(summary.get("state", "unknown"))
    connected = bool(summary.get("connected", False))
    error_code = cast(str | None, summary.get("error_code"))
    error_detail = str(summary.get("error_detail", "") or "").strip()
    label = _status_label(state, connected=connected, error_code=error_code)
    kind = _status_kind(state, error_code=error_code, connected=connected)
    normalized = state.lower().strip()
    protocol_code = PROTOCOL_STATE_CODES.get(normalized)
    protocol_item = next((item for item in PROTOCOL_STATUS_SCALE if item[0] == normalized), None)
    voltage = _format_number(summary.get("voltage"), digits=2, suffix=" V")
    soc = _format_number(summary.get("soc"), digits=0, suffix="%")
    temperature = _format_number(summary.get("temperature"), digits=1, suffix=" C")
    protocol_note = (
        "This state comes directly from the BM200/BM6 monitor protocol. "
        "BMGateway does not derive it from voltage, SoC, temperature, or a combined threshold."
    )
    runtime_note = "This state is produced by the gateway runtime instead of the monitor itself."
    note = protocol_note if protocol_code is not None else runtime_note
    scale_html = ""
    description = "Gateway runtime state."
    if protocol_item is not None:
        description = protocol_item[2]
        scale_html = _status_scale_markup(
            current_state=normalized,
            connected=connected,
            error_code=error_code,
        )
    elif error_detail:
        description = error_detail
    chips: list[str] = []
    latest_sample = _display_timestamp(summary.get("last_seen", "unknown"))
    chips.append(f"<span class='pill-chip'>Latest sample {latest_sample}</span>")
    if protocol_code is not None:
        chips.append(f"<span class='pill-chip'>Protocol code {protocol_code}</span>")
    chips.append(f"<span class='pill-chip'>Voltage {html.escape(voltage)}</span>")
    chips.append(f"<span class='pill-chip'>SoC {html.escape(soc)}</span>")
    if temperature != "-":
        chips.append(f"<span class='pill-chip'>Temperature {html.escape(temperature)}</span>")
    chips_html = "".join(chips)
    return (
        '<div class="status-explainer">'
        '<div class="status-explainer-summary">'
        "<div>"
        "<div class='settings-label'>Reported Status</div>"
        "</div>"
        f"{status_badge(label, kind=kind)}"
        "</div>"
        '<div class="status-explainer-body">'
        "<p class='status-explainer-copy'><strong>What it means:</strong> "
        f"{html.escape(description)}</p>"
        f"<p class='status-explainer-copy'>{html.escape(note)}</p>"
        f"<div class='chip-grid status-chip-grid'>{chips_html}</div>"
        f"{scale_html}"
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
        points.append(
            {
                "ts": f"{row.get('day', '')}T12:00:00",
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
                fetch_recent_history(database_path, device_id=device_id, limit=576),
                fetch_daily_history(database_path, device_id=device_id, limit=730),
                series=device_name,
                series_color=color,
            )
        )
    return points, legend


def _history_summary(raw_history: list[dict[str, object]]) -> dict[str, str]:
    valid_rows = [row for row in raw_history if row.get("error_code") is None]
    error_rows = [row for row in raw_history if row.get("error_code") is not None]
    valid_count = len(valid_rows)
    error_count = len(error_rows)
    avg_voltage = (
        sum(float(cast(float | int, row["voltage"])) for row in valid_rows) / valid_count
        if valid_count
        else None
    )
    avg_soc = (
        sum(float(cast(float | int, row["soc"])) for row in valid_rows) / valid_count
        if valid_count
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
) -> str:
    return render_settings_html(
        config=config,
        snapshot=snapshot,
        devices=devices,
        edit_mode=True,
        message=message,
        storage_summary=storage_summary,
        config_text=config_text,
        devices_text=devices_text,
        contract=contract,
        theme_preference=theme_preference,
    )


def render_battery_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    chart_points: list[dict[str, object]],
    legend: list[tuple[str, str]],
    show_chart_markers: bool = False,
    visible_device_limit: int = 5,
    appearance: str = "system",
) -> str:
    version_label = display_version()
    primary_device_id = _primary_device_id(snapshot, devices)
    snapshot_devices = _merge_snapshot_devices(snapshot, devices)
    device_cards: list[str] = []
    for index, device in enumerate(snapshot_devices):
        if not isinstance(device, dict):
            continue
        color_key = _device_color_key(device, fallback_index=index)
        device_id = str(device.get("id", ""))
        voltage_text = html.escape(_format_number(device.get("voltage"), digits=2, suffix="V"))
        temperature_text = html.escape(
            _format_number(device.get("temperature"), digits=1, suffix="°C")
        )
        device_name_text = html.escape(str(device.get("name", device_id)))
        reading_text = f"Temperature {temperature_text}"
        badge_stack_markup = _device_badge_stack_markup(
            device,
            badge_class="battery-tile-icon battery-card-badge",
        )
        vehicle_text = html.escape(_vehicle_summary(device))
        battery_summary = _battery_metadata_summary(device)
        battery_meta_html = (
            ""
            if battery_summary == "Battery details not set"
            else f"<div class='meta battery-card-meta-extra'>{html.escape(battery_summary)}</div>"
        )
        circle_status = _battery_card_status_markup(device, inline=True)
        gauge_value = html.escape(_format_number(device.get("soc"), digits=0, suffix="%"))
        gauge_inner = (
            f'<div class="battery-card-gauge-value">{gauge_value}</div>'
            f"{circle_status}"
            f'<div class="battery-card-gauge-label">{voltage_text}</div>'
        )
        gauge_markup = _soc_gauge_markup(
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
                style=_tone_card_style(color_key),
            )
        )
    overview_pages = _chunk_overview_cards(
        device_cards,
        device_slots=visible_device_limit,
        add_card="",
    )
    overview_track_id = "battery-overview-track"
    is_paginated = len(overview_pages) > 1
    overview_pages_html = "".join(
        (
            f'<div class="{_overview_page_class(len(page), is_single_page=not is_paginated)}" '
            f'style="--overview-columns: {_overview_layout_dimensions(len(page))[0]}; '
            f'--overview-rows: {_overview_layout_dimensions(len(page))[1]};">'
            + "".join(page)
            + "</div>"
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
            default_range="30",
            default_metric="soc",
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
        script=chart_script(chart_id) + _battery_overview_script(overview_track_id),
    )


def render_devices_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    message: str = "",
    theme_preference: str = "system",
) -> str:
    version_label = display_version()
    primary_device_id = _primary_device_id(snapshot, devices)
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
        tone = _device_color_key(device, fallback_index=index)
        status_value, status_subvalue = _device_runtime_summary(runtime)
        state_tile = metric_tile(
            label="Status",
            value=status_value,
            tone=tone,
            subvalue=status_subvalue,
        )
        signal_grade, _signal_percent, _bars, signal_rssi_text = _signal_quality(
            rssi=runtime.get("rssi"),
            connected=connected,
            error_code=runtime_error_code,
        )
        signal_tile = metric_tile(
            label="Signal Quality",
            value=signal_grade,
            tone="blue",
            detail_html=_signal_quality_detail_html(
                rssi=runtime.get("rssi"),
                connected=connected,
                error_code=runtime_error_code,
            ),
        )
        family_label, profile_label = _battery_summary(device)
        battery_type = html.escape(profile_label)
        enabled_badge = status_badge(
            "Enabled" if bool(device.get("enabled", False)) else "Disabled",
            kind="ok" if bool(device.get("enabled", False)) else "offline",
        )
        device_name_text = html.escape(str(device.get("name", device_id)))
        device_mac_text = html.escape(str(device.get("mac", "")))
        vehicle_text = html.escape(_vehicle_summary(device))
        battery_summary = _battery_metadata_summary(device)
        battery_text = html.escape(
            battery_summary if battery_summary != "Battery details not set" else family_label
        )
        device_id_text = html.escape(device_id)
        family_badge_html = (
            ""
            if family_label == profile_label
            else f"<span class='pill-chip'>{html.escape(family_label)}</span>"
        )
        device_icon_markup = _device_badge_stack_markup(
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
            body=_add_device_form_html(
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
        script=_battery_form_script(),
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
            int(_coerce_float(cast(dict[str, object], row).get("percent", 0))),
            _coerce_float(cast(dict[str, object], row).get("voltage", 0.0)),
        )
        for row in cast(list[object], custom_curve)
        if isinstance(row, dict)
    ]
    color_key = _device_color_key(device)
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
        f'<option value="bm200"{_selected_attr(device_type == "bm200")}>bm200</option>'
        f'<option value="bm300pro"{_selected_attr(device_type == "bm300pro")}>bm300pro</option>'
    )
    family_options = _battery_family_options(selected_family=family)
    profile_options = _battery_profile_options(selected_profile=profile)
    custom_mode_options = _custom_mode_options(selected_mode=custom_soc_mode)
    vehicle_type_options = _vehicle_type_options(selected_vehicle_type=vehicle_type)
    color_control_html = _color_key_control_html(
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
                f'<label class="settings-value" style="{TOGGLE_LABEL_STYLE}">'
                f'<input id="edit-installed-in-vehicle-input" type="checkbox" '
                f'name="installed_in_vehicle"{_checked_attr(installed_in_vehicle)}>'
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
                f'<div class="curve-grid">{_curve_rows_html(tuple(curve_pairs))}</div>'
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
        script=_battery_form_script(),
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
    theme_preference: str = "system",
) -> str:
    version_label = display_version()
    primary_device_id = _primary_device_id(snapshot, devices)
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    storage_summary = storage_summary or {
        "counts": {
            "gateway_snapshots": 0,
            "device_readings": 0,
            "device_daily_rollups": 0,
        },
        "devices": [],
    }
    contract = contract or {}
    detected_bluetooth_adapters = (
        _discover_bluetooth_adapters()
        if detected_bluetooth_adapters is None
        else detected_bluetooth_adapters
    )
    device_tabs = (
        "".join(
            (
                f"<span class='pill-chip'>"
                f"{html.escape(str(device.get('name', device.get('id', 'Device'))))}"
                "</span>"
            )
            for device in devices
        )
        or "<span class='pill-chip'>No devices configured</span>"
    )
    web_enabled = f"{config.web.host}:{config.web.port}" if config.web.enabled else "disabled"
    daily_retention = (
        "unlimited"
        if config.retention.daily_retention_days == 0
        else f"{config.retention.daily_retention_days} days"
    )
    counts = cast(dict[str, object], storage_summary.get("counts", {}))
    gateway_contract = cast(dict[str, object], contract.get("gateway", {}))
    contract_devices = cast(list[object], contract.get("devices", []))
    gateway_state_topic = html.escape(str(gateway_contract.get("state_topic", "")))
    gateway_discovery_topic = html.escape(str(gateway_contract.get("discovery_topic", "")))
    device_contract_count = len(contract_devices) if isinstance(contract_devices, list) else 0
    detected_adapter_names = [
        str(adapter.get("name", ""))
        for adapter in detected_bluetooth_adapters
        if str(adapter.get("name", ""))
    ]
    configured_adapter_present = (
        config.bluetooth.adapter == "auto" or config.bluetooth.adapter in detected_adapter_names
    )
    adapter_status = (
        "No Bluetooth adapters detected"
        if not detected_adapter_names
        else (
            f"Configured adapter {config.bluetooth.adapter} is missing"
            if not configured_adapter_present
            else "Adapter detected"
        )
    )
    detected_adapter_summary = ", ".join(detected_adapter_names) or "No adapters detected"
    api_chips = "".join(
        api_chip(endpoint)
        for endpoint in (
            "/api/status",
            "/api/config",
            "/api/devices",
            "/api/ha/contract",
            "/api/ha/discovery",
            "/api/storage",
            "/api/analytics?device_id=<id>",
            "/api/history?device_id=<id>&kind=daily",
        )
    )
    overview_cards = (
        '<div class="metrics-grid compact-overview-grid">'
        + summary_card(
            "Latest snapshot",
            _display_timestamp(snapshot.get("generated_at", "missing")),
            subvalue=f"Gateway: {html.escape(str(snapshot.get('gateway_name', 'BMGateway')))}",
            classes="compact-summary timestamp-summary",
        )
        + summary_card(
            "Gateway snapshots",
            str(counts.get("gateway_snapshots", 0)),
            subvalue=(
                f"Devices online: {snapshot.get('devices_online', 0)} / "
                f"{snapshot.get('devices_total', 0)}"
            ),
            classes="compact-summary",
        )
        + summary_card(
            "Raw / rollups",
            f"{counts.get('device_readings', 0)} / {counts.get('device_daily_rollups', 0)}",
            subvalue=f"MQTT connected: {snapshot.get('mqtt_connected', False)}",
            classes="compact-summary",
        )
        + "</div>"
    )
    actions_body = (
        '<div class="inline-actions">'
        '<form method="post" action="/actions/run-once">'
        f"{button('Run One Collection Cycle', kind='primary')}"
        "</form>"
        '<form method="post" action="/actions/recover-bluetooth">'
        f"{button('Recover Bluetooth Adapter', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/prune-history">'
        f"{button('Prune History Using Retention Settings', kind='secondary')}"
        "</form>"
        "</div>"
        '<div style="margin-top:1rem" class="chip-grid">'
        f"{api_chips}"
        "</div>"
    )
    web_section_body = (
        settings_row("Web interface", web_enabled)
        + settings_row("Configured host", config.web.host)
        + settings_row("Configured port", str(config.web.port))
    )
    display_section_body = (
        settings_row(
            "Chart point markers",
            "Enabled" if config.web.show_chart_markers else "Disabled",
        )
        + settings_row("Visible overview cards", str(config.web.visible_device_limit))
        + settings_row(
            "Appearance",
            {
                "light": "Light",
                "dark": "Dark",
                "system": "System",
            }.get(config.web.appearance, config.web.appearance),
        )
    )
    bluetooth_section_body = (
        settings_row("Adapter", config.bluetooth.adapter)
        + settings_row("Detected adapters", detected_adapter_summary)
        + settings_row("Adapter status", adapter_status)
        + settings_row("Scan timeout", f"{config.bluetooth.scan_timeout_seconds} seconds")
        + settings_row("Connect timeout", f"{config.bluetooth.connect_timeout_seconds} seconds")
    )
    gateway_section_body = (
        f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
        + settings_row("Gateway name", config.gateway.name)
        + settings_row("Timezone", config.gateway.timezone)
        + settings_row("Live polling", config.gateway.reader_mode)
        + settings_row("Poll interval", f"{config.gateway.poll_interval_seconds} seconds")
        + settings_row("MQTT", "Enabled" if config.mqtt.enabled else "Disabled")
        + settings_row(
            "Home Assistant",
            "Enabled" if config.home_assistant.enabled else "Disabled",
        )
        + settings_row("Raw retention", f"{config.retention.raw_retention_days} days")
        + settings_row("Daily rollup retention", daily_retention)
    )
    if edit_mode:
        gateway_section_body = (
            '<form method="post" action="/settings/gateway">'
            + f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
            + settings_control_row(
                "Gateway name",
                (
                    f'<input id="gateway-name-input" type="text" name="gateway_name" '
                    f'value="{html.escape(config.gateway.name)}" autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Timezone",
                (
                    f'<input id="timezone-input" type="text" name="timezone" '
                    f'value="{html.escape(config.gateway.timezone)}" autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Live polling",
                (
                    '<select id="reader-mode-input" name="reader_mode" autocomplete="off">'
                    f'<option value="fake"{_selected_attr(config.gateway.reader_mode == "fake")}>'
                    "fake</option>"
                    f'<option value="live"{_selected_attr(config.gateway.reader_mode == "live")}>'
                    "live</option>"
                    "</select>"
                ),
            )
            + settings_control_row(
                "Poll interval",
                (
                    f'<input id="poll-interval-input" type="text" name="poll_interval_seconds" '
                    f'value="{config.gateway.poll_interval_seconds}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + settings_control_row(
                "MQTT",
                (
                    f'<label class="settings-value" style="{TOGGLE_LABEL_STYLE}">'
                    f'<input type="checkbox" name="mqtt_enabled"'
                    f"{_checked_attr(config.mqtt.enabled)}>"
                    "<span>Enable MQTT publishing</span></label>"
                ),
            )
            + settings_control_row(
                "Home Assistant",
                (
                    f'<label class="settings-value" style="{TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="home_assistant_enabled"'
                    f"{_checked_attr(config.home_assistant.enabled)}>"
                    "<span>Enable Home Assistant contract</span></label>"
                ),
            )
            + settings_control_row(
                "Raw retention",
                (
                    f'<input id="raw-retention-input" type="text" name="raw_retention_days" '
                    f'value="{config.retention.raw_retention_days}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Daily rollup retention",
                (
                    f'<input id="daily-retention-input" type="text" name="daily_retention_days" '
                    f'value="{config.retention.daily_retention_days}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save gateway settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        web_section_body = (
            '<form method="post" action="/settings/web">'
            '<input type="hidden" name="settings_section" value="web">'
            + settings_control_row(
                "Web interface",
                (
                    f'<label class="settings-value" style="{TOGGLE_LABEL_STYLE}">'
                    f'<input type="checkbox" name="web_enabled"{_checked_attr(config.web.enabled)}>'
                    "<span>Enable web interface</span></label>"
                ),
            )
            + settings_control_row(
                "Host",
                (
                    f'<input id="web-host-input" type="text" name="web_host" '
                    f'value="{html.escape(config.web.host)}" autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Port",
                (
                    f'<input id="web-port-input" type="text" name="web_port" '
                    f'value="{config.web.port}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save web service settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        display_section_body = (
            '<form method="post" action="/settings/web">'
            '<input type="hidden" name="settings_section" value="display">'
            + settings_control_row(
                "Chart point markers",
                (
                    f'<label class="settings-value" style="{TOGGLE_LABEL_STYLE}">'
                    f'<input id="show-chart-markers-input" type="checkbox" '
                    f'name="show_chart_markers"{_checked_attr(config.web.show_chart_markers)}>'
                    "<span>Show chart point markers</span></label>"
                ),
                help_text=(
                    "Turn point markers back on if you prefer exact sample dots "
                    "over the cleaner default BM-style lines."
                ),
            )
            + settings_control_row(
                "Visible overview cards",
                (
                    '<select id="visible-device-limit-input" name="visible_device_limit" '
                    'autocomplete="off">'
                    f'<option value="1"{_selected_attr(config.web.visible_device_limit == 1)}>'
                    "1</option>"
                    f'<option value="3"{_selected_attr(config.web.visible_device_limit == 3)}>'
                    "3</option>"
                    f'<option value="5"{_selected_attr(config.web.visible_device_limit == 5)}>'
                    "5</option>"
                    "</select>"
                ),
                help_text=(
                    "Choose how many monitored batteries stay visible before the "
                    "overview pages horizontally on larger fleets."
                ),
            )
            + settings_control_row(
                "Appearance",
                (
                    '<select id="appearance-input" name="appearance" autocomplete="off">'
                    f'<option value="light"{_selected_attr(config.web.appearance == "light")}>'
                    "Light</option>"
                    f'<option value="dark"{_selected_attr(config.web.appearance == "dark")}>'
                    "Dark</option>"
                    f'<option value="system"{_selected_attr(config.web.appearance == "system")}>'
                    "System</option>"
                    "</select>"
                ),
                help_text=(
                    "Pick whether the web UI follows the system theme or stays locked to "
                    "light or dark styling."
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save display settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        bluetooth_section_body = (
            '<form method="post" action="/settings/bluetooth">'
            + settings_control_row(
                "Adapter",
                (
                    '<select id="bluetooth-adapter-input" name="bluetooth_adapter" '
                    'autocomplete="off">'
                    f'<option value="auto"{_selected_attr(config.bluetooth.adapter == "auto")}>'
                    "Auto</option>"
                    + "".join(
                        (
                            f'<option value="{html.escape(name)}"'
                            f"{_selected_attr(config.bluetooth.adapter == name)}>"
                            f"{html.escape(name)}</option>"
                        )
                        for name in detected_adapter_names
                    )
                    + (
                        ""
                        if config.bluetooth.adapter == "auto" or configured_adapter_present
                        else (
                            f'<option value="{html.escape(config.bluetooth.adapter)}" selected>'
                            f"{html.escape(config.bluetooth.adapter)} (missing)</option>"
                        )
                    )
                    + "</select>"
                ),
                help_text=(
                    "No Bluetooth adapters detected on this host."
                    if not detected_adapter_names
                    else (
                        f"Configured adapter {config.bluetooth.adapter} is not currently present."
                        if not configured_adapter_present
                        else f"Detected adapters: {detected_adapter_summary}."
                    )
                ),
            )
            + settings_control_row(
                "Scan timeout",
                (
                    f'<input id="scan-timeout-input" type="text" name="scan_timeout_seconds" '
                    f'value="{config.bluetooth.scan_timeout_seconds}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Connect timeout",
                (
                    f'<input id="connect-timeout-input" type="text" '
                    f'name="connect_timeout_seconds" '
                    f'value="{config.bluetooth.connect_timeout_seconds}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save bluetooth settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
    body = (
        top_header(
            title="Settings",
            subtitle=(
                "Read the current gateway configuration first, then unlock the "
                "same page when you want to edit it."
            ),
            eyebrow="Settings",
            right=(
                '<div class="hero-actions">'
                + (
                    '<a class="secondary-button" href="/settings">Done</a>'
                    if edit_mode
                    else '<a class="primary-button" href="/settings?edit=1">Edit settings</a>'
                )
                + "</div>"
            ),
        )
        + banner
        + (
            ""
            if edit_mode
            else section_card(
                title="Gateway Overview",
                subtitle="Operational Surfaces",
                body=overview_cards,
            )
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Actions",
                subtitle=(
                    "Run the collector, prune retained history, and inspect the live JSON APIs."
                ),
                body=actions_body,
            )
        )
        + section_card(
            title="Gateway Settings",
            subtitle="Current runtime and integration summary",
            body=gateway_section_body,
        )
        + section_card(
            title="Web Service",
            subtitle="Current management UI binding",
            body=web_section_body,
        )
        + section_card(
            title="Display Settings",
            subtitle="Current chart rendering preferences",
            body=display_section_body,
        )
        + section_card(
            title="Bluetooth",
            subtitle="Adapter selection and BLE timeout tuning.",
            body=bluetooth_section_body,
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Home Assistant Contract",
                subtitle=(
                    "Keep the MQTT surface easy to scan without losing the exact "
                    "state and discovery topics."
                ),
                body=(
                    settings_row("Gateway state topic", gateway_state_topic)
                    + settings_row("Gateway discovery topic", gateway_discovery_topic)
                    + settings_row("Device discovery payloads", str(device_contract_count))
                ),
            )
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Storage Summary",
                subtitle=(
                    "Recent raw samples and long-term rollups stay available, but "
                    "the page emphasizes storage posture first."
                ),
                body=(
                    '<div class="table-shell"><table><thead><tr><th>Device</th><th>Raw samples</th>'
                    "<th>Raw first</th><th>Raw last</th>"
                    "<th>Daily days</th><th>Daily first</th><th>Daily last</th></tr></thead>"
                    f"<tbody>{_storage_rows(storage_summary)}</tbody></table></div>"
                ),
            )
        )
    )
    if not edit_mode:
        body += section_card(
            title="Configuration Files",
            subtitle="Reference paths and raw configuration snapshots.",
            body=(
                settings_row("Config path", str(config.source_path))
                + settings_row("Device registry path", str(config.device_registry_path))
                + '<div class="config-grid">'
                + (
                    '<div><label class="settings-label" '
                    'for="config-toml-readonly">config.toml</label>'
                )
                + '<textarea id="config-toml-readonly" readonly spellcheck="false">'
                + f"{html.escape(config_text or '')}</textarea></div>"
                + (
                    '<div><label class="settings-label" '
                    'for="devices-toml-readonly">devices.toml</label>'
                )
                + '<textarea id="devices-toml-readonly" readonly spellcheck="false">'
                + f"{html.escape(devices_text or '')}</textarea></div>"
                + "</div>"
            ),
        )
    return app_document(
        title="BMGateway Settings",
        body=body,
        active_nav="settings",
        primary_device_id=primary_device_id,
        version_label=version_label,
        theme_preference=theme_preference,
    )


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
) -> str:
    version_label = display_version()
    summary = _device_summary_from_history(
        device_id=device_id,
        raw_history=raw_history,
        daily_history=daily_history,
        device_summary=device_summary,
    )
    trend_rows = "\n".join(
        (
            "<tr>"
            f"<td>{window['days']}</td>"
            f"<td>{window['current_avg_voltage']}</td>"
            f"<td>{window['previous_avg_voltage']}</td>"
            f"<td>{window['delta_avg_voltage']}</td>"
            f"<td>{window['current_avg_soc']}</td>"
            f"<td>{window['previous_avg_soc']}</td>"
            f"<td>{window['delta_avg_soc']}</td>"
            "</tr>"
        )
        for window in cast(list[dict[str, object]], analytics.get("windows", []))
    )
    yearly_rows = "\n".join(
        (
            "<tr>"
            f"<td>{row['year']}</td><td>{row['samples']}</td>"
            f"<td>{row['avg_voltage']}</td><td>{row['avg_soc']}</td>"
            f"<td>{row['error_count']}</td>"
            "</tr>"
        )
        for row in yearly_history
    )
    trend_rows_html = trend_rows or "<tr><td colspan='7'>No comparison windows</td></tr>"
    yearly_rows_html = yearly_rows or "<tr><td colspan='5'>No yearly data</td></tr>"
    history_sections = _render_history_sections(
        raw_history=raw_history,
        daily_history=daily_history,
        monthly_history=monthly_history,
    )
    voltage = _format_number(summary.get("voltage"), digits=2, suffix=" V")
    temperature = _format_number(summary.get("temperature"), digits=1, suffix=" C")
    rssi = summary.get("rssi")
    signal_grade, signal_percent, _signal_bars, signal_rssi_text = _signal_quality(
        rssi=rssi,
        connected=bool(summary.get("connected", False)),
        error_code=cast(str | None, summary.get("error_code")),
    )
    vehicle_text = html.escape(_vehicle_summary(summary))
    battery_meta_text = html.escape(_battery_metadata_summary(summary))
    chart_id = f"device-chart-{quote(device_id)}".replace("%", "")
    device_name = str(summary.get("name", device_id))
    device_color = _device_accent_color(summary)
    body = (
        top_header(
            title=f"{summary.get('name', device_id)}",
            subtitle=(
                f"Device detail for {device_id}. {vehicle_text}. Real history, "
                "live runtime status, and gateway-focused health signals."
            ),
            eyebrow="Battery Detail",
            right=(
                '<div class="hero-actions">'
                f'<a class="secondary-button" href="/devices/edit?device_id={quote(device_id)}">'
                "Edit device</a></div>"
            ),
        )
        + section_card(
            title="Battery Status",
            subtitle=(
                "BM200/BM6 monitors can report protocol states like Critical, Low, "
                "Normal, Charging, and Floating. Gateway-only states such as Offline, "
                "Error, Disabled, or Unsupported are also surfaced when the runtime "
                "cannot use a direct monitor state."
            ),
            body=_device_status_explainer(summary),
        )
        + '<div class="hero-shell">'
        + section_card(
            title="State of Charge",
            subtitle=(
                "SoC remains the dominant focal metric, with vehicle-only "
                "BM300 actions replaced by gateway health signals."
            ),
            body=(
                '<div class="soc-gauge-card">'
                f"{_soc_gauge_markup(soc_value=summary.get('soc'))}"
                "</div>"
            ),
            classes="hero-shell-primary",
        )
        + '<div class="hero-aside">'
        + metric_tile(
            label="Voltage",
            value=voltage,
            tone="blue",
            subvalue="Latest live/device sample",
        )
        + metric_tile(
            label="Temperature",
            value=temperature,
            tone="green",
            subvalue="Recent raw sample",
        )
        + metric_tile(
            label="Signal Quality",
            value=signal_grade,
            tone="orange",
            detail_html=_signal_quality_detail_html(
                rssi=rssi,
                connected=bool(summary.get("connected", False)),
                error_code=cast(str | None, summary.get("error_code")),
            ),
        )
        + metric_tile(
            label="Battery Health",
            value="Stable" if summary.get("error_code") is None else "Needs attention",
            tone="purple",
            subvalue="Gateway-adapted replacement for vehicle-only tests",
        )
        + "</div></div>"
        + section_card(
            title="Runtime Status",
            subtitle=(
                "These cards replace BM300 vehicle actions with gateway-relevant operational state."
            ),
            body=(
                '<div class="metrics-grid">'
                + summary_card(
                    "Last Seen",
                    _display_timestamp(summary.get("last_seen", "unknown")),
                    classes="timestamp-summary",
                )
                + summary_card("Vehicle", vehicle_text)
                + summary_card("Battery Metadata", battery_meta_text)
                + summary_card(
                    "Error Code",
                    html.escape(str(summary.get("error_code", "None"))),
                    subvalue=html.escape(
                        str(summary.get("error_detail", "No current driver/runtime error"))
                    ),
                )
                + summary_card("Connection", "Connected" if summary.get("connected") else "Offline")
                + "</div>"
            ),
        )
        + chart_card(
            chart_id=chart_id,
            title="Historical Chart",
            subtitle=(
                "Switch between voltage, SoC, and temperature without leaving "
                "the page. Longer ranges prioritize rollups, recent ranges "
                "keep raw samples visible."
            ),
            points=_chart_points(
                raw_history,
                daily_history,
                series=device_name,
                series_color=device_color,
            ),
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
            default_range="30",
            default_metric="voltage",
            legend=[(device_name, device_color)],
            show_markers=show_chart_markers,
        )
        + section_card(
            title="Trend Windows",
            subtitle=(
                "Rolling comparison windows stay visible, but as compact "
                "product-grade insight cards instead of a dominant debug table."
            ),
            body=(
                '<div class="table-shell"><table><thead><tr><th>Days</th><th>Current Avg V</th>'
                "<th>Previous Avg V</th><th>Delta V</th>"
                "<th>Current Avg SoC</th><th>Previous Avg SoC</th><th>Delta SoC</th></tr></thead>"
                f"<tbody>{trend_rows_html}</tbody></table></div>"
            ),
        )
        + section_card(
            title="Yearly Summary",
            subtitle=(
                "Long-term rollups remain directly visible for degradation "
                "tracking across seasons and years."
            ),
            body=(
                '<div class="table-shell"><table><thead><tr><th>Year</th><th>Samples</th>'
                "<th>Avg V</th><th>Avg SoC</th><th>Error Count</th></tr></thead>"
                f"<tbody>{yearly_rows_html}</tbody></table></div>"
            ),
        )
        + history_sections
    )
    return app_document(
        title=f"{device_id} Device",
        body=body,
        active_nav="battery",
        version_label=version_label,
        theme_preference=theme_preference,
        script=chart_script(chart_id),
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
) -> str:
    version_label = display_version()
    sections = _render_history_sections(
        raw_history=raw_history,
        daily_history=daily_history,
        monthly_history=monthly_history,
    )
    escaped_device_id = html.escape(device_id)
    summary = _history_summary(raw_history)
    chart_id = f"history-chart-{quote(device_id)}".replace("%", "")
    selected_device = cast(
        dict[str, object],
        next(
            (device for device in configured_devices if str(device.get("id", "")) == device_id),
            {"id": device_id},
        ),
    )
    history_color = _device_accent_color(selected_device)
    history_series = str(selected_device.get("name") or device_id)
    body = (
        top_header(
            title="History",
            subtitle=("Chart-first history dashboard with calmer hierarchy."),
            eyebrow="History",
        )
        + _history_device_selector_html(
            configured_devices=configured_devices,
            selected_device_id=device_id,
        )
        + section_card(
            title="Summary",
            subtitle=(
                "Valid samples, error pressure, and average device health are "
                "surfaced before the raw rows."
            ),
            body=(
                '<div class="metrics-grid">'
                + summary_card("Valid samples", summary["valid_samples"])
                + summary_card("Error count", summary["error_count"])
                + summary_card("Average voltage", summary["avg_voltage"])
                + summary_card("Average SoC", summary["avg_soc"])
                + "</div>"
            ),
        )
        + chart_card(
            chart_id=chart_id,
            title="History Chart",
            subtitle=(
                "Use the segmented control to switch between Voltage, SoC, and "
                "Temperature. Range controls rebalance recent raw readings "
                "against daily rollups."
            ),
            points=_chart_points(
                raw_history,
                daily_history,
                series=history_series,
                series_color=history_color,
            ),
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
            default_range="30",
            default_metric="soc",
            legend=[(history_series, history_color)],
            show_markers=show_chart_markers,
        )
        + sections
    )
    return app_document(
        title=f"{escaped_device_id} History",
        body=body,
        active_nav="history",
        version_label=version_label,
        theme_preference=theme_preference,
        script=chart_script(chart_id),
    )


def _parse_history_limit(values: list[str], *, default: int) -> int:
    raw_limit = values[0] if values else str(default)
    limit = int(raw_limit)
    if limit <= 0:
        raise ValueError("limit must be positive")
    return limit


def _render_history_sections(
    *,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
) -> str:
    raw_rows = "\n".join(
        "<tr>"
        f"<td>{_escape_cell(row['ts'])}</td>"
        f"<td>{_escape_cell(row['voltage'])}</td>"
        f"<td>{_escape_cell(row['soc'])}</td>"
        f"<td>{_escape_cell(row.get('temperature', '-'))}</td>"
        f"<td>{_escape_cell(row['state'])}</td>"
        f"<td>{_escape_cell(row['error_code']) if row['error_code'] is not None else '-'}</td>"
        "</tr>"
        for row in raw_history
    )
    daily_rows = "\n".join(
        "<tr>"
        f"<td>{_escape_cell(row['day'])}</td>"
        f"<td>{_escape_cell(row['samples'])}</td>"
        f"<td>{_escape_cell(row['min_voltage'])}</td>"
        f"<td>{_escape_cell(row['max_voltage'])}</td>"
        f"<td>{_escape_cell(row['avg_voltage'])}</td>"
        f"<td>{_escape_cell(row['avg_soc'])}</td>"
        f"<td>{_escape_cell(row.get('avg_temperature', '-'))}</td>"
        f"<td>{_escape_cell(row['error_count'])}</td>"
        "</tr>"
        for row in daily_history
    )
    monthly_rows = "\n".join(
        "<tr>"
        f"<td>{_escape_cell(row['month'])}</td>"
        f"<td>{_escape_cell(row['samples'])}</td>"
        f"<td>{_escape_cell(row['min_voltage'])}</td>"
        f"<td>{_escape_cell(row['max_voltage'])}</td>"
        f"<td>{_escape_cell(row['avg_voltage'])}</td>"
        f"<td>{_escape_cell(row['avg_soc'])}</td>"
        f"<td>{_escape_cell(row.get('avg_temperature', '-'))}</td>"
        f"<td>{_escape_cell(row['error_count'])}</td>"
        "</tr>"
        for row in monthly_history
    )
    raw_rows_html = raw_rows or "<tr><td colspan='6'>No data</td></tr>"
    daily_rows_html = daily_rows or "<tr><td colspan='8'>No data</td></tr>"
    monthly_rows_html = monthly_rows or "<tr><td colspan='8'>No data</td></tr>"
    return (
        section_card(
            title="Recent Raw Readings",
            subtitle=(
                "Raw rows stay available, but tucked behind a lower-priority "
                "operational panel so chart insight leads the page."
            ),
            body=(
                '<div class="raw-table-shell"><details open><summary class="settings-label">'
                "Raw readings table</summary>"
                '<div class="table-shell"><table><thead><tr><th>Timestamp</th><th>Voltage</th>'
                "<th>SoC</th><th>Temperature</th><th>State</th><th>Error</th></tr></thead>"
                f"<tbody>{raw_rows_html}</tbody></table></div></details></div>"
            ),
        )
        + section_card(
            title="Daily Rollups",
            subtitle=(
                "Aggregated daily summaries for longer-range trend "
                "interpretation and cleaner degradation analysis."
            ),
            body=(
                '<div class="table-shell"><table><thead><tr><th>Day</th><th>Samples</th>'
                "<th>Min V</th><th>Max V</th>"
                "<th>Avg V</th><th>Avg SoC</th><th>Avg Temp</th><th>Error count</th></tr></thead>"
                f"<tbody>{daily_rows_html}</tbody></table></div>"
            ),
        )
        + section_card(
            title="Monthly Summaries",
            subtitle=(
                "Lower-frequency summaries remain accessible for long "
                "retention windows without letting the raw error rows "
                "dominate the page."
            ),
            body=(
                '<div class="table-shell"><table><thead><tr><th>Month</th><th>Samples</th>'
                "<th>Min V</th><th>Max V</th>"
                "<th>Avg V</th><th>Avg SoC</th><th>Avg Temp</th><th>Error count</th></tr></thead>"
                f"<tbody>{monthly_rows_html}</tbody></table></div>"
            ),
        )
    )
