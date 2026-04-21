"""Web interfaces for BMGateway."""

from __future__ import annotations

import html
import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, quote, urlencode, urlparse

from . import __build_timestamp__, __version__, display_version
from .config import AppConfig, load_config, write_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import (
    BATTERY_FAMILIES,
    CUSTOM_SOC_MODES,
    ICON_CATALOG,
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
    load_device_registry,
    normalize_mac_address,
    validate_devices,
    vehicle_type_label,
    write_device_registry,
)
from .runtime import database_file_path, recover_adapter, state_file_path
from .state_store import (
    fetch_daily_history,
    fetch_degradation_report,
    fetch_monthly_history,
    fetch_recent_history,
    fetch_storage_summary,
    fetch_yearly_history,
    load_snapshot,
    prune_history,
)
from .web_ui import (
    api_chip,
    app_document,
    banner_strip,
    button,
    chart_card,
    chart_script,
    device_icon,
    icon_picker_option,
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

    tones = ("green", "purple", "blue", "orange")
    device_cards: list[str] = []
    for index, device in enumerate(configured_devices):
        device_id = str(device.get("id", ""))
        is_selected = device_id == selected_device_id
        icon_key = _device_icon_key(device)
        current_text = "Current History View" if is_selected else "Open Device History"
        aria_current = ' aria-current="page"' if is_selected else ""
        device_cards.append(
            f'<a class="history-device-card tone-card {tones[index % len(tones)]}'
            f'{" selected" if is_selected else ""}" href="/history?device_id={quote(device_id)}"'
            f"{aria_current}>"
            "<div class='device-card-head battery-card-head'>"
            f"{device_icon(icon_key, label=icon_label(icon_key), frame_class='hero-device-icon')}"
            "<div class='device-card-copy battery-card-copy'>"
            f"<div class='meta meta-name'>{html.escape(str(device.get('name') or device_id))}</div>"
            f"<div class='meta meta-context'>{html.escape(device_id)}</div>"
            f"<div class='meta history-device-current'>{html.escape(current_text)}</div>"
            "</div>"
            "</div>"
            "</a>"
        )
    return section_card(
        title="History Device",
        subtitle="Switch the history surface between configured batteries.",
        body=f'<div class="device-grid history-device-grid">{"".join(device_cards)}</div>',
    )


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
        return [[add_card]]
    pages: list[list[str]] = []
    for index in range(0, len(device_cards), device_slots):
        pages.append([*device_cards[index : index + device_slots], add_card])
    return pages


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


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


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
    if isinstance(icon_key, str) and icon_key in ICON_CATALOG:
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


def _device_icon_markup(device: dict[str, object]) -> str:
    icon_key = _device_icon_key(device)
    return device_icon(icon_key, label=icon_label(icon_key))


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


def _default_curve_pairs() -> list[tuple[int, float]]:
    return [
        (100, 12.90),
        (90, 12.80),
        (80, 12.70),
        (70, 12.60),
        (60, 12.50),
        (50, 12.40),
        (40, 12.30),
        (30, 12.20),
        (20, 12.10),
        (10, 12.00),
        (0, 11.90),
    ]


def _curve_rows_html(
    curve_pairs: list[tuple[int, float]] | tuple[tuple[int, float], ...] | None = None,
) -> str:
    curve_map = dict(curve_pairs or _default_curve_pairs())
    rows: list[str] = []
    for percent, default_voltage in _default_curve_pairs():
        voltage = float(curve_map.get(percent, default_voltage))
        rows.append(
            "<div class='curve-grid-row'>"
            f"<label class='settings-label' for='{_curve_field_name(percent)}'>{percent}%</label>"
            f"<input id='{_curve_field_name(percent)}' type='number' step='0.01' min='0' "
            f"name='{_curve_field_name(percent)}' value='{voltage:.2f}'></div>"
        )
    return "".join(rows)


def _add_device_form_html() -> str:
    return (
        '<form id="add-device" method="post" action="/devices/add" class="two-column-grid" '
        'data-battery-config-form="true">'
        '<div><label class="settings-label" for="device-id-input">Device ID</label>'
        '<input id="device-id-input" type="text" name="device_id" '
        'autocomplete="off" spellcheck="false" placeholder="bm200_house…" required></div>'
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
        "profiles can use the intelligent algorithm or a voltage-to-SoC curve."
        "</div></div>"
        "<div><div class='settings-label'>Choose a built-in icon</div>"
        "<div class='inline-field-help'>"
        "This icon is used on the Battery Overview and device cards. Pick the "
        "closest visual identity for the battery or monitor."
        "</div>"
        "<div class='icon-picker-grid'>"
        f"{_icon_picker_options(selected_key='battery_monitor')}"
        "</div>"
        "</div>"
        '<div class="battery-form-grid">'
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


def _icon_picker_options(*, selected_key: str = "battery_monitor") -> str:
    return "".join(
        icon_picker_option(value, label=label, checked=value == selected_key)
        for value, label in ICON_CATALOG.items()
    )


TOGGLE_LABEL_STYLE = "display:flex;justify-content:flex-start;gap:0.55rem;align-items:center"


def _battery_form_script() -> str:
    return """
<script>
(() => {
  const forms = document.querySelectorAll("[data-battery-config-form='true']");
  for (const form of forms) {
    const familySelect = form.querySelector("[name='battery_family']");
    const profileSelect = form.querySelector("[name='battery_profile']");
    const modeSelect = form.querySelector("[name='custom_soc_mode']");
    const installedInVehicle = form.querySelector("[name='installed_in_vehicle']");
    const vehicleSection = form.querySelector("[data-vehicle-section]");
    const modeSection = form.querySelector("[data-custom-mode-section]");
    const curveSection = form.querySelector("[data-custom-curve-section]");
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

    function syncAll() {
      syncProfileOptions();
      syncCustomSections();
      syncVehicleSection();
    }

    familySelect.addEventListener("change", syncAll);
    profileSelect.addEventListener("change", syncCustomSections);
    modeSelect.addEventListener("change", syncCustomSections);
    if (installedInVehicle) {
      installedInVehicle.addEventListener("change", syncVehicleSection);
    }
    syncAll();
  }
})();
</script>
"""


def _parse_custom_curve_from_form(form: dict[str, list[str]]) -> tuple[tuple[int, float], ...]:
    rows: list[tuple[int, float]] = []
    for percent, default_voltage in _default_curve_pairs():
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


def _device_tone(index: int, state: str = "") -> str:
    if state in {"error", "critical", "offline"}:
        return "orange"
    tones = ("green", "purple", "blue", "orange")
    return tones[index % len(tones)]


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
    try:
        active_index = labels.index(normalized)
    except ValueError:
        active_index = 0
    marker_percent = ((active_index + 0.5) / len(PROTOCOL_STATUS_SCALE)) * 100.0
    tone = _status_visual_tone(normalized, connected=connected, error_code=error_code)
    fill_width = f"{marker_percent:.1f}%"
    state_label = _status_label(normalized, connected=connected, error_code=error_code)
    fill_html = (
        f'<div class="status-scale-fill tone-{html.escape(tone)}" style="width:{fill_width}"></div>'
    )
    marker_html = (
        f'<div class="status-scale-marker tone-{html.escape(tone)}" '
        f'style="left:{marker_percent:.1f}%"></div>'
    )
    segments_html = "".join(
        (
            "<div class='status-scale-segment"
            f" tone-{css_tone}"
            f"{' active' if key == normalized else ''}"
            f"{' reached' if index <= active_index else ''}"
            "'>"
            f"<span>{html.escape(label)}</span>"
            "</div>"
        )
        for index, (key, label, _description, css_tone) in enumerate(PROTOCOL_STATUS_SCALE)
    )
    return (
        '<div class="status-scale" role="img" '
        f'aria-label="BM200/BM6 status scale showing {html.escape(state_label)}">'
        '<div class="status-scale-track">'
        f"{fill_html}"
        f"{marker_html}"
        "</div>"
        f'<div class="status-scale-labels">{segments_html}</div>'
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
        "This monitor reports the battery state directly over BM200/BM6. "
        "BMGateway does not invent this label from a hidden threshold."
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
    if protocol_code is not None:
        chips.append(f"<span class='pill-chip'>Protocol code {protocol_code}</span>")
    chips.append(f"<span class='pill-chip'>Voltage {html.escape(voltage)}</span>")
    chips.append(f"<span class='pill-chip'>SoC {html.escape(soc)}</span>")
    if temperature != "-":
        chips.append(f"<span class='pill-chip'>Temperature {html.escape(temperature)}</span>")
    chips_html = "".join(chips)
    return (
        '<details class="status-explainer">'
        '<summary class="status-explainer-summary">'
        "<div>"
        "<div class='settings-label'>Reported Status</div>"
        f"<div class='status-explainer-value'>{html.escape(label)}</div>"
        "</div>"
        f"{status_badge(label, kind=kind)}"
        "</summary>"
        '<div class="status-explainer-body">'
        f"<p class='status-explainer-copy'>{html.escape(note)}</p>"
        f"<p class='status-explainer-copy'>{html.escape(description)}</p>"
        f"<div class='chip-grid status-chip-grid'>{chips_html}</div>"
        f"{scale_html}"
        "</div>"
        "</details>"
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
    colors = ("#17c45a", "#9a57f5", "#4f8df7", "#f4a340")
    points: list[dict[str, object]] = []
    legend: list[tuple[str, str]] = []
    for index, device in enumerate(devices):
        device_id = str(device.get("id", ""))
        if not device_id:
            continue
        device_name = str(device.get("name", device_id))
        color = colors[index % len(colors)]
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
    )


def render_battery_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    chart_points: list[dict[str, object]],
    legend: list[tuple[str, str]],
    show_chart_markers: bool = False,
    visible_device_limit: int = 5,
) -> str:
    version_label = display_version()
    primary_device_id = _primary_device_id(snapshot, devices)
    snapshot_devices = _merge_snapshot_devices(snapshot, devices)
    device_cards: list[str] = []
    tones = ("green", "purple", "blue", "orange")
    for index, device in enumerate(snapshot_devices):
        if not isinstance(device, dict):
            continue
        tone = tones[index % len(tones)]
        device_id = str(device.get("id", ""))
        voltage_text = html.escape(_format_number(device.get("voltage"), digits=2, suffix="V"))
        temperature_text = html.escape(
            _format_number(device.get("temperature"), digits=1, suffix="°C")
        )
        icon_key = _device_icon_key(device)
        device_name_text = html.escape(str(device.get("name", device_id)))
        reading_text = f"Temperature {temperature_text}"
        hero_icon_markup = device_icon(
            icon_key,
            label=icon_label(icon_key),
            frame_class="battery-tile-icon",
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
            f"{hero_icon_markup}"
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
                    "<div class='battery-tile-hero'>"
                    f"{gauge_markup}"
                    "</div>"
                    "<div class='device-card-copy battery-card-copy'>"
                    f"<div class='meta meta-name'>{device_name_text}</div>"
                    f"<div class='meta meta-context'>{vehicle_text}</div>"
                    f"<div class='meta battery-card-reading'>{reading_text}</div>"
                    f"{battery_meta_html}"
                    "<div class='footer-row'>"
                    f'<a class="secondary-button" href="/device?device_id={quote(device_id)}">'
                    "Device Details</a>"
                    "</div>"
                    "</div>"
                ),
                tone=tone,
                extra_class="battery-overview-card",
            )
        )
    add_button_html = (
        '<div class="footer-row"><a class="primary-button" href="/devices/new">Add Device</a></div>'
    )
    add_card = tone_card(
        (
            "<div class='battery-overview-add-tile'>"
            "<div class='battery-overview-add-glyph'>+</div>"
            "<div class='meta battery-overview-add-copy'>Add Device</div>"
            "<div class='meta battery-overview-add-note'>Register another BM monitor</div>"
            f"{add_button_html}"
            "</div>"
        ),
        tone="orange",
        extra_class="battery-overview-add-card",
    )
    overview_pages = _chunk_overview_cards(
        device_cards,
        device_slots=visible_device_limit,
        add_card=add_card,
    )
    overview_track_id = "battery-overview-track"
    is_paginated = len(overview_pages) > 1
    overview_pages_html = "".join(
        (
            f'<div class="battery-overview-page{" is-single-page" if not is_paginated else ""}" '
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
            right=(
                '<div class="hero-actions">'
                '<a class="secondary-button" href="/settings">Settings</a>'
                "</div>"
            ),
        )
        + banner_strip(
            "Bluetooth device status is shown directly on each card. Classic-only "
            "or unavailable BLE adapters remain visible as controlled warnings.",
            kind="warning",
            trailing="<a class='secondary-button' href='/devices/new'>Add Device</a>",
        )
        + section_card(
            title="Battery Overview",
            subtitle=(
                "The default landing page mirrors the mobile app journey: "
                "check live state first, then dive into device detail or history."
            ),
            body=overview_scroller,
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
        script=chart_script(chart_id) + _battery_overview_script(overview_track_id),
    )


def render_devices_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    message: str = "",
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
        runtime_state = str(runtime.get("state", ""))
        runtime_error_code = cast(str | None, runtime.get("error_code"))
        connected = bool(runtime.get("connected", False))
        tone = _device_tone(index, runtime_state)
        icon_key = _device_icon_key(device)
        status_value, status_subvalue = _device_runtime_summary(runtime)
        state_tile = metric_tile(
            label="Status",
            value=status_value,
            tone=tone,
            subvalue=status_subvalue,
        )
        signal_grade, signal_percent, _bars, signal_rssi_text = _signal_quality(
            rssi=runtime.get("rssi"),
            connected=connected,
            error_code=runtime_error_code,
        )
        signal_tile = metric_tile(
            label="Signal Quality",
            value=signal_grade,
            tone="blue",
            subvalue=signal_rssi_text,
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
        battery_text = html.escape(_battery_metadata_summary(device))
        cards.append(
            section_card(
                body=(
                    "<div class='settings-row' style='padding-top:0;"
                    "padding-bottom:0.8rem;border-bottom:0'>"
                    "<div class='device-card-head'>"
                    f"{device_icon(icon_key, label=icon_label(icon_key))}"
                    "<div class='device-card-copy'>"
                    f"<div class='settings-label'>{vehicle_text}</div>"
                    f"<div class='section-title'>{device_name_text}</div>"
                    f"<div class='muted-note'>Serial / MAC: {device_mac_text}</div>"
                    f"<div class='muted-note'>{battery_text}</div>"
                    "</div>"
                    "</div>"
                    "<a class='ghost-button' "
                    f"href='/devices/edit?device_id={quote(device_id)}'>Edit</a>"
                    "</div>"
                    "<div class='two-column-grid'>"
                    f"{state_tile}"
                    f"{signal_tile}"
                    "</div>"
                    "<div class='settings-row' style='padding-bottom:0;border-bottom:0'>"
                    f"<div class='pill-chip'>{battery_type}</div>"
                    f"<div class='muted-note'>{html.escape(family_label)}</div>"
                    f"{enabled_badge}"
                    "</div>"
                    f"<div class='footer-row' style='margin-top:1rem'>"
                    f"<span class='muted-note'>{signal_percent}%</span>"
                    f"<a href='/devices/edit?device_id={quote(device_id)}'>Edit device settings</a>"
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
            body="".join(cards) or "<div class='muted-note'>No devices configured yet.</div>",
        )
    )
    return app_document(
        title="BMGateway Devices",
        body=body,
        active_nav="devices",
        primary_device_id=primary_device_id,
        version_label=version_label,
    )


def render_add_device_html(*, message: str = "") -> str:
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
            body=_add_device_form_html(),
        )
    )
    return app_document(
        title="BMGateway Add Device",
        body=body,
        active_nav="devices",
        primary_device_id="",
        version_label=display_version(),
        script=_battery_form_script(),
    )


def render_edit_device_html(*, device: dict[str, object], message: str = "") -> str:
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
    icon_key = str(device.get("icon_key", _device_icon_key(device)))
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
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    body = (
        top_header(
            title="Edit Device",
            subtitle=(
                "Update the registry metadata, battery profile, icon, and "
                "installation context for this monitor."
            ),
            eyebrow="Devices",
            right=(
                '<div class="hero-actions">'
                '<a class="secondary-button" href="/devices">Devices</a>'
                '<a class="secondary-button" href="/settings">Settings</a>'
                "</div>"
            ),
        )
        + banner
        + section_card(
            title=str(device.get("name", device_id)),
            subtitle=f"Registry ID: {device_id}",
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
                "including custom curves."
                "</div></div>"
                "<div><div class='settings-label'>Choose a built-in icon</div>"
                "<div class='icon-picker-grid'>"
                f"{_icon_picker_options(selected_key=icon_key)}"
                "</div></div>"
                "<div class='battery-form-grid'>"
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
        '<div class="metrics-grid">'
        + summary_card(
            "Latest snapshot",
            _display_timestamp(snapshot.get("generated_at", "missing")),
            subvalue=f"Gateway: {html.escape(str(snapshot.get('gateway_name', 'BMGateway')))}",
        )
        + summary_card(
            "Gateway snapshots",
            str(counts.get("gateway_snapshots", 0)),
            subvalue=(
                f"Devices online: {snapshot.get('devices_online', 0)} / "
                f"{snapshot.get('devices_total', 0)}"
            ),
        )
        + summary_card(
            "Raw / rollups",
            f"{counts.get('device_readings', 0)} / {counts.get('device_daily_rollups', 0)}",
            subvalue=f"MQTT connected: {snapshot.get('mqtt_connected', False)}",
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
    display_section_body = settings_row(
        "Chart point markers",
        "Enabled" if config.web.show_chart_markers else "Disabled",
    ) + settings_row("Visible overview cards", str(config.web.visible_device_limit))
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
                    "overview pages horizontally. The Add Device tile is always shown after them."
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
    status = status_badge(
        str(summary.get("state", "unknown")).replace("_", " ").title(),
        kind=_status_kind(
            str(summary.get("state", "")),
            cast(str | None, summary.get("error_code")),
            bool(summary.get("connected", True)),
        ),
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
    body = (
        top_header(
            title=f"{summary.get('name', device_id)}",
            subtitle=(
                f"Device detail for {device_id}. {vehicle_text}. Real history, "
                "live runtime status, and gateway-focused health signals."
            ),
            eyebrow="Battery Detail",
            right=(
                '<div class="hero-actions"><a class="secondary-button" href="/">Battery</a>'
                f'<a class="secondary-button" href="/history?device_id={quote(device_id)}">'
                "History Tables</a></div>"
            ),
        )
        + banner_strip(
            f"<strong>{html.escape(str(summary.get('last_seen', 'unknown')))}</strong>"
            " is the latest sample this device page is built from.",
            kind="warning" if summary.get("error_code") else "info",
            trailing=status,
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
            subvalue=signal_rssi_text,
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
                _device_status_explainer(summary)
                + '<div class="metrics-grid">'
                + summary_card("Last Seen", _display_timestamp(summary.get("last_seen", "unknown")))
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
                series=str(summary.get("name", device_id)),
                series_color="#17c45a",
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
            legend=[(str(summary.get("name", device_id)), "#17c45a")],
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
                series=device_id,
                series_color="#4f8df7",
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
            legend=[(device_id, "#4f8df7")],
            show_markers=show_chart_markers,
        )
        + sections
    )
    return app_document(
        title=f"{escaped_device_id} History",
        body=body,
        active_nav="history",
        version_label=version_label,
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


def _config_and_registry_texts(config_path: Path) -> tuple[str, str]:
    config_text = _read_text(config_path)
    try:
        config = load_config(config_path)
        devices_text = _read_text(config.device_registry_path)
    except Exception:
        devices_text = ""
    return config_text, devices_text


def update_config_from_text(*, config_path: Path, config_toml: str, devices_toml: str) -> list[str]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        temp_config_path = temp_dir / config_path.name
        temp_config_path.write_text(config_toml, encoding="utf-8")
        config = load_config(temp_config_path)
        temp_registry_path = config.device_registry_path
        temp_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_registry_path.write_text(devices_toml, encoding="utf-8")
        devices = load_device_registry(temp_registry_path)

        from .config import validate_config

        config_errors = validate_config(config)
        device_errors = validate_devices(devices)
        errors = [*config_errors, *device_errors]
        if errors:
            return errors

        declared_registry_path = Path(config.gateway.device_registry)
        target_registry_path = (
            declared_registry_path
            if declared_registry_path.is_absolute()
            else (config_path.parent / declared_registry_path).resolve()
        )
        write_config(
            config_path,
            replace(
                config,
                source_path=config_path.resolve(),
                device_registry_path=target_registry_path,
            ),
        )
        write_device_registry(target_registry_path, devices)
        return []


def add_device_from_form(
    *,
    config_path: Path,
    device_id: str,
    device_type: str,
    device_name: str,
    device_mac: str,
    battery_family: str | None = None,
    battery_profile: str | None = None,
    custom_soc_mode: str = "intelligent_algorithm",
    custom_voltage_curve: tuple[tuple[int, float], ...] | None = None,
    icon_key: str | None = None,
    installed_in_vehicle: bool = False,
    vehicle_type: str = "",
    battery_brand: str = "",
    battery_model: str = "",
    battery_capacity_ah: float | None = None,
    battery_production_year: int | None = None,
) -> list[str]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    resolved_family = battery_family or default_battery_family(device_type.strip())
    resolved_profile = battery_profile or default_battery_profile(
        device_type.strip(),
        resolved_family,
    )
    devices.append(
        Device(
            id=device_id.strip(),
            type=device_type.strip(),
            name=device_name.strip(),
            mac=normalize_mac_address(device_mac),
            enabled=True,
            battery_family=resolved_family.strip(),
            battery_profile=resolved_profile.strip(),
            custom_soc_mode=custom_soc_mode.strip(),
            custom_voltage_curve=custom_voltage_curve or tuple(_default_curve_pairs()),
            icon_key=(
                icon_key
                or default_icon_key(
                    battery_family=resolved_family.strip(),
                    battery_profile=resolved_profile.strip(),
                )
            ).strip(),
            installed_in_vehicle=installed_in_vehicle,
            vehicle_type=vehicle_type.strip() if installed_in_vehicle else "",
            battery_brand=battery_brand.strip(),
            battery_model=battery_model.strip(),
            battery_capacity_ah=battery_capacity_ah,
            battery_production_year=battery_production_year,
        )
    )
    errors = validate_devices(devices)
    if errors:
        return errors

    write_device_registry(config.device_registry_path, devices)
    if config.gateway.reader_mode != "live":
        write_config(
            config_path,
            replace(
                config,
                gateway=replace(config.gateway, reader_mode="live"),
            ),
        )
    return []


def update_device_from_form(
    *,
    config_path: Path,
    device_id: str,
    device_type: str,
    device_name: str,
    device_mac: str,
    battery_family: str,
    battery_profile: str,
    custom_soc_mode: str,
    custom_voltage_curve: tuple[tuple[int, float], ...],
    icon_key: str,
    installed_in_vehicle: bool,
    vehicle_type: str,
    battery_brand: str,
    battery_model: str,
    battery_capacity_ah: float | None,
    battery_production_year: int | None,
) -> list[str]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    updated_devices: list[Device] = []
    found = False
    for device in devices:
        if device.id == device_id:
            updated_devices.append(
                replace(
                    device,
                    type=device_type.strip(),
                    name=device_name.strip(),
                    mac=normalize_mac_address(device_mac),
                    battery_family=battery_family.strip(),
                    battery_profile=battery_profile.strip(),
                    custom_soc_mode=custom_soc_mode.strip(),
                    custom_voltage_curve=custom_voltage_curve,
                    icon_key=icon_key.strip(),
                    installed_in_vehicle=installed_in_vehicle,
                    vehicle_type=vehicle_type.strip() if installed_in_vehicle else "",
                    battery_brand=battery_brand.strip(),
                    battery_model=battery_model.strip(),
                    battery_capacity_ah=battery_capacity_ah,
                    battery_production_year=battery_production_year,
                )
            )
            found = True
        else:
            updated_devices.append(device)
    if not found:
        return [f"device {device_id} was not found"]
    errors = validate_devices(updated_devices)
    if errors:
        return errors
    write_device_registry(config.device_registry_path, updated_devices)
    return []


def update_device_icon(*, config_path: Path, device_id: str, icon_key: str) -> list[str]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    target = next((device for device in devices if device.id == device_id), None)
    if target is None:
        return [f"device {device_id} was not found"]
    return update_device_from_form(
        config_path=config_path,
        device_id=device_id,
        device_type=target.type,
        device_name=target.name,
        device_mac=target.mac,
        battery_family=target.battery_family,
        battery_profile=target.battery_profile,
        custom_soc_mode=target.custom_soc_mode,
        custom_voltage_curve=target.custom_voltage_curve,
        icon_key=icon_key,
        installed_in_vehicle=target.installed_in_vehicle,
        vehicle_type=target.vehicle_type,
        battery_brand=target.battery_brand,
        battery_model=target.battery_model,
        battery_capacity_ah=target.battery_capacity_ah,
        battery_production_year=target.battery_production_year,
    )


def update_web_preferences(
    *,
    config_path: Path,
    web_enabled: bool | None,
    web_host: str | None,
    web_port: int | None,
    show_chart_markers: bool | None,
    visible_device_limit: int | None,
) -> list[str]:
    config = load_config(config_path)
    resolved_enabled = config.web.enabled if web_enabled is None else web_enabled
    resolved_host = config.web.host if web_host is None else web_host
    resolved_port = config.web.port if web_port is None else web_port
    resolved_show_chart_markers = (
        config.web.show_chart_markers if show_chart_markers is None else show_chart_markers
    )
    resolved_visible_device_limit = (
        config.web.visible_device_limit if visible_device_limit is None else visible_device_limit
    )
    updated = replace(
        config,
        web=replace(
            config.web,
            enabled=resolved_enabled,
            host=resolved_host,
            port=resolved_port,
            show_chart_markers=resolved_show_chart_markers,
            visible_device_limit=resolved_visible_device_limit,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        return errors
    write_config(config_path, updated)
    return []


def update_gateway_preferences(
    *,
    config_path: Path,
    gateway_name: str,
    timezone: str,
    reader_mode: str,
    poll_interval_seconds: int,
    mqtt_enabled: bool,
    home_assistant_enabled: bool,
    raw_retention_days: int,
    daily_retention_days: int,
) -> list[str]:
    config = load_config(config_path)
    updated = replace(
        config,
        gateway=replace(
            config.gateway,
            name=gateway_name,
            timezone=timezone,
            reader_mode=reader_mode,
            poll_interval_seconds=poll_interval_seconds,
        ),
        mqtt=replace(
            config.mqtt,
            enabled=mqtt_enabled,
        ),
        home_assistant=replace(
            config.home_assistant,
            enabled=home_assistant_enabled,
        ),
        retention=replace(
            config.retention,
            raw_retention_days=raw_retention_days,
            daily_retention_days=daily_retention_days,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        return errors
    write_config(config_path, updated)
    return []


def update_bluetooth_preferences(
    *,
    config_path: Path,
    adapter: str,
    scan_timeout_seconds: int,
    connect_timeout_seconds: int,
) -> list[str]:
    config = load_config(config_path)
    updated = replace(
        config,
        bluetooth=replace(
            config.bluetooth,
            adapter=adapter,
            scan_timeout_seconds=scan_timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        return errors
    write_config(config_path, updated)
    return []


def build_run_once_command(config_path: Path, *, state_dir: Path | None = None) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "bm_gateway",
        "--config",
        str(config_path),
        "run",
        "--once",
    ]
    if state_dir is not None:
        command.extend(["--state-dir", str(state_dir)])
    return command


def run_once_via_cli(
    config_path: Path, *, state_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        build_run_once_command(config_path, state_dir=state_dir),
        check=False,
        capture_output=True,
        text=True,
    )


def serve_snapshot(*, host: str, port: int, snapshot_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            snapshot = load_snapshot(snapshot_path)
            if self.path == "/api/status":
                payload = json.dumps(
                    _snapshot_with_version(snapshot), indent=2, sort_keys=True
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            html = render_snapshot_html(snapshot).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def serve_management(
    *,
    host: str,
    port: int,
    config_path: Path,
    state_dir: Path | None = None,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send_html(self, html: str, status: int = 200) -> None:
            payload = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload_obj: object, status: int = 200) -> None:
            payload = json.dumps(payload_obj, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _load_current(self) -> tuple[AppConfig, dict[str, object], Path]:
            config = load_config(config_path)
            snapshot_path = state_file_path(config, state_dir=state_dir)
            snapshot = load_snapshot(snapshot_path) if snapshot_path.exists() else {"devices": []}
            database_path = database_file_path(config, state_dir=state_dir)
            return config, snapshot, database_path

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            config, snapshot, database_path = self._load_current()
            devices = load_device_registry(config.device_registry_path)
            serialized_devices = [device.to_dict() for device in devices]
            contract = build_contract(config, devices)

            if parsed.path == "/api/config":
                config_text, devices_text = _config_and_registry_texts(config_path)
                self._send_json({"config_toml": config_text, "devices_toml": devices_text})
                return

            if parsed.path == "/api/status":
                self._send_json(_snapshot_with_version(snapshot))
                return
            if parsed.path == "/api/devices":
                self._send_json({"devices": serialized_devices})
                return
            if parsed.path == "/api/ha/contract":
                self._send_json(contract)
                return
            if parsed.path == "/api/ha/discovery":
                self._send_json(build_discovery_payloads(config, devices))
                return
            if parsed.path == "/api/storage":
                self._send_json(fetch_storage_summary(database_path))
                return
            if parsed.path == "/api/analytics":
                params = parse_qs(parsed.query)
                device_id = params.get("device_id", [""])[0]
                self._send_json(fetch_degradation_report(database_path, device_id=device_id))
                return

            if parsed.path == "/api/history":
                params = parse_qs(parsed.query)
                device_id = params.get("device_id", [""])[0]
                kind = params.get("kind", ["daily"])[0]
                try:
                    limit = _parse_history_limit(params.get("limit", []), default=365)
                except ValueError as error:
                    self._send_json({"error": str(error)}, status=400)
                    return
                if kind == "raw":
                    self._send_json(
                        fetch_recent_history(database_path, device_id=device_id, limit=limit)
                    )
                elif kind == "monthly":
                    self._send_json(
                        fetch_monthly_history(database_path, device_id=device_id, limit=limit)
                    )
                elif kind == "yearly":
                    self._send_json(
                        fetch_yearly_history(database_path, device_id=device_id, limit=limit)
                    )
                else:
                    self._send_json(
                        fetch_daily_history(database_path, device_id=device_id, limit=limit)
                    )
                return

            if parsed.path == "/device":
                params = parse_qs(parsed.query)
                device_id = params.get("device_id", [""])[0]
                snapshot_devices = snapshot.get("devices", [])
                snapshot_device: dict[str, object] | None = None
                if isinstance(snapshot_devices, list):
                    for device in snapshot_devices:
                        if isinstance(device, dict) and str(device.get("id", "")) == device_id:
                            snapshot_device = device
                            break
                html = render_device_html(
                    device_id=device_id,
                    raw_history=fetch_recent_history(database_path, device_id=device_id, limit=576),
                    daily_history=fetch_daily_history(
                        database_path,
                        device_id=device_id,
                        limit=730,
                    ),
                    monthly_history=fetch_monthly_history(
                        database_path,
                        device_id=device_id,
                        limit=24,
                    ),
                    yearly_history=fetch_yearly_history(
                        database_path,
                        device_id=device_id,
                        limit=10,
                    ),
                    analytics=fetch_degradation_report(database_path, device_id=device_id),
                    device_summary=snapshot_device,
                    show_chart_markers=config.web.show_chart_markers,
                )
                self._send_html(html)
                return

            if parsed.path == "/history":
                params = parse_qs(parsed.query)
                requested_device_id = params.get("device_id", [""])[0]
                available_device_ids = [
                    str(item.get("id", ""))
                    for item in serialized_devices
                    if str(item.get("id", "")).strip()
                ]
                device_id = requested_device_id
                if not device_id and available_device_ids:
                    device_id = available_device_ids[0]
                elif device_id and device_id not in available_device_ids and available_device_ids:
                    device_id = available_device_ids[0]
                html = render_history_html(
                    device_id=device_id,
                    configured_devices=serialized_devices,
                    raw_history=(
                        fetch_recent_history(database_path, device_id=device_id, limit=576)
                        if device_id
                        else []
                    ),
                    daily_history=(
                        fetch_daily_history(
                            database_path,
                            device_id=device_id,
                            limit=730,
                        )
                        if device_id
                        else []
                    ),
                    monthly_history=(
                        fetch_monthly_history(
                            database_path,
                            device_id=device_id,
                            limit=24,
                        )
                        if device_id
                        else []
                    ),
                    show_chart_markers=config.web.show_chart_markers,
                )
                self._send_html(html)
                return

            if parsed.path == "/devices":
                message = parse_qs(parsed.query).get("message", [""])[0]
                html = render_devices_html(
                    snapshot=snapshot,
                    devices=serialized_devices,
                    message=message,
                )
                self._send_html(html)
                return

            if parsed.path == "/devices/new":
                message = parse_qs(parsed.query).get("message", [""])[0]
                self._send_html(render_add_device_html(message=message))
                return

            if parsed.path == "/devices/edit":
                params = parse_qs(parsed.query)
                device_id = params.get("device_id", [""])[0]
                device = next(
                    (item for item in serialized_devices if str(item.get("id", "")) == device_id),
                    None,
                )
                if device is None:
                    self._send_html(
                        render_devices_html(snapshot=snapshot, devices=serialized_devices),
                        status=404,
                    )
                    return
                message = parse_qs(parsed.query).get("message", [""])[0]
                self._send_html(render_edit_device_html(device=device, message=message))
                return

            if parsed.path == "/settings":
                params = parse_qs(parsed.query)
                html = render_settings_html(
                    config=config,
                    snapshot=snapshot,
                    devices=serialized_devices,
                    edit_mode=params.get("edit", ["0"])[0] == "1",
                    message=params.get("message", [""])[0],
                    storage_summary=fetch_storage_summary(database_path),
                    config_text=_read_text(config_path),
                    devices_text=_read_text(config.device_registry_path),
                    contract=contract,
                )
                self._send_html(html)
                return

            if parsed.path in {"/management", "/gateway"}:
                message = parse_qs(parsed.query).get("message", [""])[0]
                html = render_settings_html(
                    snapshot=snapshot,
                    config=config,
                    devices=serialized_devices,
                    edit_mode=True,
                    message=message,
                    storage_summary=fetch_storage_summary(database_path),
                    config_text=_read_text(config_path),
                    devices_text=_read_text(config.device_registry_path),
                    contract=contract,
                )
                self._send_html(html)
                return

            battery_chart_points, battery_legend = _fleet_chart_points(
                database_path=database_path,
                devices=serialized_devices,
            )
            html = render_battery_html(
                snapshot=snapshot,
                devices=serialized_devices,
                chart_points=battery_chart_points,
                legend=battery_legend,
                show_chart_markers=config.web.show_chart_markers,
                visible_device_limit=config.web.visible_device_limit,
            )
            self._send_html(html)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length).decode("utf-8")
            form = parse_qs(body, keep_blank_values=True)

            if parsed.path == "/config":
                config_toml = form.get("config_toml", [""])[0]
                devices_toml = form.get("devices_toml", [""])[0]
                errors = update_config_from_text(
                    config_path=config_path,
                    config_toml=config_toml,
                    devices_toml=devices_toml,
                )
                if errors:
                    html = render_management_html(
                        snapshot={"devices": []},
                        config=load_config(config_path),
                        storage_summary={
                            "counts": {
                                "gateway_snapshots": 0,
                                "device_readings": 0,
                                "device_daily_rollups": 0,
                            },
                            "devices": [],
                        },
                        devices=[],
                        config_text=config_toml,
                        devices_text=devices_toml,
                        contract={},
                        message="Validation failed: " + "; ".join(errors),
                    )
                    self._send_html(html, status=400)
                    return

                self.send_response(303)
                self.send_header("Location", "/settings?edit=1&message=Configuration%20saved")
                self.end_headers()
                return

            if parsed.path == "/devices/add":
                errors = add_device_from_form(
                    config_path=config_path,
                    device_id=form.get("device_id", [""])[0],
                    device_type=form.get("device_type", ["bm200"])[0],
                    device_name=form.get("device_name", [""])[0],
                    device_mac=form.get("device_mac", [""])[0],
                    battery_family=form.get("battery_family", ["lead_acid"])[0],
                    battery_profile=form.get("battery_profile", ["regular_lead_acid"])[0],
                    custom_soc_mode=form.get("custom_soc_mode", ["intelligent_algorithm"])[0],
                    custom_voltage_curve=_parse_custom_curve_from_form(form),
                    icon_key=form.get("icon_key", ["battery_monitor"])[0],
                    installed_in_vehicle=_bool_from_form(form, "installed_in_vehicle"),
                    vehicle_type=_string_from_form(form, "vehicle_type"),
                    battery_brand=_string_from_form(form, "battery_brand"),
                    battery_model=_string_from_form(form, "battery_model"),
                    battery_capacity_ah=_optional_float_from_form(form, "battery_capacity_ah"),
                    battery_production_year=_optional_int_from_form(
                        form,
                        "battery_production_year",
                    ),
                )
                if errors:
                    self._send_html(
                        render_add_device_html(message="Validation failed: " + "; ".join(errors)),
                        status=400,
                    )
                    return

                run_once_via_cli(config_path, state_dir=state_dir)
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/devices?" + urlencode({"message": "Device added. Live polling enabled."}),
                )
                self.end_headers()
                return

            if parsed.path == "/devices/update":
                errors = update_device_from_form(
                    config_path=config_path,
                    device_id=form.get("device_id", [""])[0],
                    device_type=form.get("device_type", ["bm200"])[0],
                    device_name=form.get("device_name", [""])[0],
                    device_mac=form.get("device_mac", [""])[0],
                    battery_family=form.get("battery_family", ["lead_acid"])[0],
                    battery_profile=form.get("battery_profile", ["regular_lead_acid"])[0],
                    custom_soc_mode=form.get("custom_soc_mode", ["intelligent_algorithm"])[0],
                    custom_voltage_curve=_parse_custom_curve_from_form(form),
                    icon_key=form.get("icon_key", ["battery_monitor"])[0],
                    installed_in_vehicle=_bool_from_form(form, "installed_in_vehicle"),
                    vehicle_type=_string_from_form(form, "vehicle_type"),
                    battery_brand=_string_from_form(form, "battery_brand"),
                    battery_model=_string_from_form(form, "battery_model"),
                    battery_capacity_ah=_optional_float_from_form(form, "battery_capacity_ah"),
                    battery_production_year=_optional_int_from_form(
                        form,
                        "battery_production_year",
                    ),
                )
                if errors:
                    config = load_config(config_path)
                    configured_devices = load_device_registry(config.device_registry_path)
                    device_id = form.get("device_id", [""])[0]
                    device = next(
                        (item.to_dict() for item in configured_devices if item.id == device_id),
                        {
                            "id": device_id,
                            "type": form.get("device_type", ["bm200"])[0],
                            "name": form.get("device_name", [""])[0],
                            "mac": form.get("device_mac", [""])[0],
                            "icon_key": form.get("icon_key", ["battery_monitor"])[0],
                            "installed_in_vehicle": _bool_from_form(form, "installed_in_vehicle"),
                            "vehicle": {
                                "installed": _bool_from_form(form, "installed_in_vehicle"),
                                "type": _string_from_form(form, "vehicle_type"),
                            },
                            "battery": {
                                "family": form.get("battery_family", ["lead_acid"])[0],
                                "profile": form.get("battery_profile", ["regular_lead_acid"])[0],
                                "custom_soc_mode": form.get(
                                    "custom_soc_mode", ["intelligent_algorithm"]
                                )[0],
                                "brand": _string_from_form(form, "battery_brand"),
                                "model": _string_from_form(form, "battery_model"),
                                "capacity_ah": _optional_float_from_form(
                                    form,
                                    "battery_capacity_ah",
                                ),
                                "production_year": _optional_int_from_form(
                                    form,
                                    "battery_production_year",
                                ),
                                "custom_voltage_curve": [
                                    {"percent": percent, "voltage": voltage}
                                    for percent, voltage in _parse_custom_curve_from_form(form)
                                ],
                            },
                        },
                    )
                    self._send_html(
                        render_edit_device_html(
                            device=device,
                            message="Validation failed: " + "; ".join(errors),
                        ),
                        status=400,
                    )
                    return

                self.send_response(303)
                self.send_header(
                    "Location",
                    "/devices/edit?"
                    + urlencode(
                        {
                            "device_id": form.get("device_id", [""])[0],
                            "message": "Device saved",
                        }
                    ),
                )
                self.end_headers()
                return

            if parsed.path == "/devices/icon":
                errors = update_device_icon(
                    config_path=config_path,
                    device_id=form.get("device_id", [""])[0],
                    icon_key=form.get("icon_key", ["battery_monitor"])[0],
                )
                if errors:
                    config, snapshot, database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    html = render_devices_html(
                        snapshot=snapshot,
                        devices=[device.to_dict() for device in configured_devices],
                    )
                    self._send_html(html, status=400)
                    return

                self.send_response(303)
                self.send_header("Location", "/devices")
                self.end_headers()
                return

            if parsed.path == "/settings/gateway":
                try:
                    poll_interval_seconds = int(form.get("poll_interval_seconds", ["300"])[0])
                    raw_retention_days = int(form.get("raw_retention_days", ["180"])[0])
                    daily_retention_days = int(form.get("daily_retention_days", ["0"])[0])
                except ValueError:
                    config, snapshot, current_database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_settings_html(
                            snapshot=snapshot,
                            config=config,
                            devices=[device.to_dict() for device in configured_devices],
                            edit_mode=True,
                            storage_summary=fetch_storage_summary(current_database_path),
                            config_text=_read_text(config_path),
                            devices_text=_read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: settings values must be numeric",
                        ),
                        status=400,
                    )
                    return
                errors = update_gateway_preferences(
                    config_path=config_path,
                    gateway_name=form.get("gateway_name", ["BMGateway"])[0],
                    timezone=form.get("timezone", ["Europe/Rome"])[0],
                    reader_mode=form.get("reader_mode", ["fake"])[0],
                    poll_interval_seconds=poll_interval_seconds,
                    mqtt_enabled=_bool_from_form(form, "mqtt_enabled"),
                    home_assistant_enabled=_bool_from_form(form, "home_assistant_enabled"),
                    raw_retention_days=raw_retention_days,
                    daily_retention_days=daily_retention_days,
                )
                if errors:
                    config, snapshot, current_database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_settings_html(
                            snapshot=snapshot,
                            config=config,
                            devices=[device.to_dict() for device in configured_devices],
                            edit_mode=True,
                            storage_summary=fetch_storage_summary(current_database_path),
                            config_text=_read_text(config_path),
                            devices_text=_read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                        ),
                        status=400,
                    )
                    return
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": "Settings saved"})
                )
                self.end_headers()
                return

            if parsed.path == "/settings/bluetooth":
                try:
                    scan_timeout_seconds = int(form.get("scan_timeout_seconds", ["15"])[0])
                    connect_timeout_seconds = int(form.get("connect_timeout_seconds", ["45"])[0])
                except ValueError:
                    config, snapshot, current_database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_settings_html(
                            snapshot=snapshot,
                            config=config,
                            devices=[device.to_dict() for device in configured_devices],
                            edit_mode=True,
                            storage_summary=fetch_storage_summary(current_database_path),
                            config_text=_read_text(config_path),
                            devices_text=_read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: bluetooth values must be numeric",
                        ),
                        status=400,
                    )
                    return
                errors = update_bluetooth_preferences(
                    config_path=config_path,
                    adapter=form.get("bluetooth_adapter", ["auto"])[0],
                    scan_timeout_seconds=scan_timeout_seconds,
                    connect_timeout_seconds=connect_timeout_seconds,
                )
                if errors:
                    config, snapshot, current_database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_settings_html(
                            snapshot=snapshot,
                            config=config,
                            devices=[device.to_dict() for device in configured_devices],
                            edit_mode=True,
                            storage_summary=fetch_storage_summary(current_database_path),
                            config_text=_read_text(config_path),
                            devices_text=_read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                        ),
                        status=400,
                    )
                    return
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": "Settings saved"})
                )
                self.end_headers()
                return

            if parsed.path == "/settings/web":
                settings_section = form.get("settings_section", [""])[0]
                web_enabled: bool | None = None
                web_host: str | None = None
                web_port: int | None = None
                show_chart_markers: bool | None = None
                visible_device_limit: int | None = None
                if settings_section == "web":
                    try:
                        web_port = int(form.get("web_port", ["80"])[0])
                    except ValueError:
                        config, snapshot, current_database_path = self._load_current()
                        configured_devices = load_device_registry(config.device_registry_path)
                        self._send_html(
                            render_management_html(
                                snapshot=snapshot,
                                config=config,
                                storage_summary=fetch_storage_summary(current_database_path),
                                devices=[device.to_dict() for device in configured_devices],
                                config_text=_read_text(config_path),
                                devices_text=_read_text(config.device_registry_path),
                                contract=build_contract(config, configured_devices),
                                message="Validation failed: web port must be numeric",
                            ),
                            status=400,
                        )
                        return
                    web_enabled = _bool_from_form(form, "web_enabled")
                    web_host = form.get("web_host", ["0.0.0.0"])[0]
                elif settings_section == "display":
                    show_chart_markers = _bool_from_form(form, "show_chart_markers")
                    try:
                        visible_device_limit = int(form.get("visible_device_limit", ["5"])[0])
                    except ValueError:
                        config, snapshot, current_database_path = self._load_current()
                        configured_devices = load_device_registry(config.device_registry_path)
                        self._send_html(
                            render_management_html(
                                snapshot=snapshot,
                                config=config,
                                storage_summary=fetch_storage_summary(current_database_path),
                                devices=[device.to_dict() for device in configured_devices],
                                config_text=_read_text(config_path),
                                devices_text=_read_text(config.device_registry_path),
                                contract=build_contract(config, configured_devices),
                                message="Validation failed: visible device limit must be numeric",
                            ),
                            status=400,
                        )
                        return
                else:
                    config, snapshot, current_database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_management_html(
                            snapshot=snapshot,
                            config=config,
                            storage_summary=fetch_storage_summary(current_database_path),
                            devices=[device.to_dict() for device in configured_devices],
                            config_text=_read_text(config_path),
                            devices_text=_read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: unknown settings section",
                        ),
                        status=400,
                    )
                    return
                errors = update_web_preferences(
                    config_path=config_path,
                    web_enabled=web_enabled,
                    web_host=web_host,
                    web_port=web_port,
                    show_chart_markers=show_chart_markers,
                    visible_device_limit=visible_device_limit,
                )
                if errors:
                    config, snapshot, current_database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_management_html(
                            snapshot=snapshot,
                            config=config,
                            storage_summary=fetch_storage_summary(current_database_path),
                            devices=[device.to_dict() for device in configured_devices],
                            config_text=_read_text(config_path),
                            devices_text=_read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                        ),
                        status=400,
                    )
                    return
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": "Settings saved"})
                )
                self.end_headers()
                return

            if parsed.path == "/actions/run-once":
                completed = run_once_via_cli(config_path, state_dir=state_dir)
                message = "Run completed" if completed.returncode == 0 else "Run failed"
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": message})
                )
                self.end_headers()
                return

            if parsed.path == "/actions/recover-bluetooth":
                config, _snapshot, _database_path = self._load_current()
                adapter = config.bluetooth.adapter if config.bluetooth.adapter != "auto" else "hci0"
                recover_adapter(adapter)
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/settings?"
                    + urlencode({"edit": "1", "message": "Bluetooth adapter recovery triggered"}),
                )
                self.end_headers()
                return

            if parsed.path == "/actions/prune-history":
                config, _snapshot, database_path = self._load_current()
                prune_history(
                    database_path,
                    raw_retention_days=config.retention.raw_retention_days,
                    daily_retention_days=config.retention.daily_retention_days,
                )
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/settings?" + urlencode({"edit": "1", "message": "History pruned"}),
                )
                self.end_headers()
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
