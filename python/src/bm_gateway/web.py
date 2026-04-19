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

from .config import AppConfig, load_config, write_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import (
    Device,
    load_device_registry,
    normalize_mac_address,
    validate_devices,
    write_device_registry,
)
from .runtime import database_file_path, state_file_path
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
    metric_tile,
    section_card,
    settings_row,
    status_badge,
    summary_card,
    tone_card,
    top_header,
)


def render_snapshot_html(snapshot: dict[str, object]) -> str:
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
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(device.get('id', '')))}</td>"
            f"<td>{html.escape(str(device.get('type', '')))}</td>"
            f"<td>{html.escape(str(device.get('name', '')))}</td>"
            f"<td>{html.escape(str(device.get('mac', '')))}</td>"
            f"<td>{html.escape(str(device.get('enabled', '')))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='5'>No configured devices</td></tr>"


def _escape_cell(value: object) -> str:
    return html.escape(str(value))


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
    if state in {"error", "critical"}:
        return "orange"
    tones = ("green", "purple", "blue", "orange")
    return tones[index % len(tones)]


def _status_kind(state: str, error_code: str | None = None, connected: bool = True) -> str:
    normalized = state.lower()
    if not connected:
        return "offline"
    if error_code is not None or normalized in {"error", "critical"}:
        return "error"
    if normalized in {"warning", "degraded", "timeout"}:
        return "warning"
    return "ok"


def _format_number(value: object, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        formatted = f"{float(value):.{digits}f}" if digits > 0 else f"{int(round(float(value)))}"
        return f"{formatted}{suffix}"
    return f"{value}{suffix}"


def _chart_points(
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for row in sorted(daily_history, key=lambda item: str(item.get("day", ""))):
        points.append(
            {
                "ts": f"{row.get('day', '')}T12:00:00",
                "label": str(row.get("day", ""))[5:],
                "kind": "daily",
                "voltage": row.get("avg_voltage"),
                "soc": row.get("avg_soc"),
                "temperature": None,
            }
        )
    for row in sorted(raw_history, key=lambda item: str(item.get("ts", ""))):
        points.append(
            {
                "ts": row.get("ts"),
                "label": str(row.get("ts", ""))[11:16],
                "kind": "raw",
                "voltage": row.get("voltage"),
                "soc": row.get("soc"),
                "temperature": row.get("temperature"),
            }
        )
    return points


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
    storage_summary: dict[str, object],
    devices: list[dict[str, object]],
    config_text: str,
    devices_text: str,
    contract: dict[str, object],
    message: str = "",
) -> str:
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    counts = cast(dict[str, object], storage_summary.get("counts", {}))
    gateway_contract = cast(dict[str, object], contract.get("gateway", {}))
    contract_devices = cast(list[object], contract.get("devices", []))
    gateway_state_topic = html.escape(str(gateway_contract.get("state_topic", "")))
    gateway_discovery_topic = html.escape(str(gateway_contract.get("discovery_topic", "")))
    device_contract_count = len(contract_devices) if isinstance(contract_devices, list) else 0
    device_cards: list[str] = []
    snapshot_devices = snapshot.get("devices", [])
    for index, device in enumerate(snapshot_devices if isinstance(snapshot_devices, list) else []):
        if not isinstance(device, dict):
            continue
        tone = _device_tone(index, str(device.get("state", "")))
        device_id = str(device.get("id", ""))
        voltage_text = html.escape(_format_number(device.get("voltage"), digits=2, suffix=" V"))
        rssi_text = html.escape(str(device.get("rssi", "-")))
        status = status_badge(
            str(device.get("state", "unknown")).replace("_", " ").title(),
            kind=_status_kind(
                str(device.get("state", "")),
                cast(str | None, device.get("error_code")),
                bool(device.get("connected", True)),
            ),
        )
        device_cards.append(
            tone_card(
                (
                    f"<h3>{html.escape(str(device.get('name', device.get('id', 'Unknown'))))}</h3>"
                    f'<div class="meta">{html.escape(str(device.get("type", "bm200")))}</div>'
                    f'<div class="hero-soc">{html.escape(str(device.get("soc", "-")))}%</div>'
                    f'<div class="meta">{voltage_text} / RSSI {rssi_text}</div>'
                    f'<div style="margin-top:0.7rem">{status}</div>'
                    '<div class="footer-row">'
                    f"<a href='/device?device_id={quote(device_id)}'>Open device page</a>"
                    f"<a href='/history?device_id={quote(device_id)}'>History</a>"
                    "</div>"
                ),
                tone=tone,
            )
        )
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
    header = top_header(
        title="BMGateway Management",
        subtitle=(
            "Premium control-plane dashboard for the live gateway. All current "
            "actions, config editing, device registry flows, storage views, and "
            "Home Assistant contract surfaces remain active."
        ),
        eyebrow="Control Plane",
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
        '<form method="post" action="/actions/prune-history">'
        f"{button('Prune History Using Retention Settings', kind='secondary')}"
        "</form>"
        "</div>"
        '<div style="margin-top:1rem" class="chip-grid">'
        f"{api_chips}"
        "</div>"
    )
    control_plane = (
        '<div class="control-plane">'
        + section_card(
            title="Gateway Overview",
            subtitle="Operational Surfaces",
            body=overview_cards,
        )
        + section_card(
            title="Actions",
            subtitle="Run the collector, prune retained history, and inspect the live JSON APIs.",
            body=actions_body,
        )
        + "</div>"
    )
    add_device_form = (
        '<form id="add-device" method="post" action="/devices/add" class="two-column-grid">'
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
        '<div><label class="settings-label" for="device-mac-input">MAC or serial</label>'
        '<input id="device-mac-input" type="text" name="device_mac" '
        'autocomplete="off" spellcheck="false" placeholder="A1B2C3D4E5F6…" required></div>'
        '<div id="device-mac-help" style="grid-column:1 / -1" class="muted-note">'
        "You can paste a compact 12-hex serial such as "
        "<code>A1B2C3D4E5F6</code>; the UI normalizes it to Bluetooth MAC format."
        "</div>"
        '<div style="grid-column:1 / -1">'
        f"{button('Add Device and Enable Live Polling', kind='primary')}"
        "</div>"
        "</form>"
    )
    device_dashboard_html = "".join(device_cards) or "<p>No active device cards yet.</p>"
    body = (
        header
        + banner
        + control_plane
        + section_card(
            title="Device Dashboard",
            subtitle=(
                "Live battery cards stay prominent while raw operational details "
                "remain one click away."
            ),
            body=f'<div class="device-grid">{device_dashboard_html}</div>',
        )
        + section_card(
            title="Add Device",
            subtitle=(
                "Register BM devices, normalize compact serials to MAC format, "
                "and enable live polling."
            ),
            body=add_device_form,
        )
        + section_card(
            title="Configured Devices",
            subtitle="The registry table remains fully visible for operational clarity.",
            body=(
                '<div class="table-shell"><table><thead><tr><th>ID</th><th>Type</th>'
                "<th>Name</th><th>MAC</th><th>Enabled</th></tr></thead>"
                f"<tbody>{_device_table_rows(devices)}</tbody></table></div>"
            ),
        )
        + section_card(
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
        + section_card(
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
        + section_card(
            title="Configuration",
            subtitle=(
                "The CLI and the web UI remain complementary: both edit the "
                "same config.toml and devices.toml files."
            ),
            body=(
                '<form method="post" action="/config">'
                '<div class="config-grid">'
                '<div><label class="settings-label" for="config-toml-input">config.toml</label>'
                f'<textarea id="config-toml-input" name="config_toml" autocomplete="off" '
                f'spellcheck="false">{html.escape(config_text)}</textarea></div>'
                '<div><label class="settings-label" for="devices-toml-input">devices.toml</label>'
                f'<textarea id="devices-toml-input" name="devices_toml" autocomplete="off" '
                f'spellcheck="false">{html.escape(devices_text)}</textarea></div>'
                "</div>"
                f'<div style="margin-top:1rem">{button("Validate and Save", kind="primary")}</div>'
                "</form>"
            ),
        )
    )
    primary_device_id = _primary_device_id(snapshot, devices)
    return app_document(
        title="BMGateway Management",
        body=body,
        active_nav="management",
        primary_device_id=primary_device_id,
    )


def render_battery_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
) -> str:
    primary_device_id = _primary_device_id(snapshot, devices)
    snapshot_devices = snapshot.get("devices", [])
    device_cards: list[str] = []
    legend: list[tuple[str, str]] = []
    chart_points: list[dict[str, object]] = []
    tones = ("green", "purple", "blue", "orange")
    colors = ("#17c45a", "#9a57f5", "#4f8df7", "#f4a340")
    if isinstance(snapshot_devices, list):
        for index, device in enumerate(snapshot_devices):
            if not isinstance(device, dict):
                continue
            tone = tones[index % len(tones)]
            color = colors[index % len(colors)]
            device_id = str(device.get("id", ""))
            voltage_text = html.escape(_format_number(device.get("voltage"), digits=2, suffix=" V"))
            temperature_text = html.escape(
                _format_number(device.get("temperature"), digits=1, suffix=" C")
            )
            badge = status_badge(
                str(device.get("state", "unknown")).replace("_", " ").title(),
                kind=_status_kind(
                    str(device.get("state", "")),
                    cast(str | None, device.get("error_code")),
                    bool(device.get("connected", True)),
                ),
            )
            legend.append((str(device.get("name", device_id)), color))
            chart_points.append(
                {
                    "ts": snapshot.get("generated_at"),
                    "label": str(snapshot.get("generated_at", ""))[11:16],
                    "kind": "raw",
                    "voltage": device.get("voltage"),
                    "soc": device.get("soc"),
                    "temperature": device.get("temperature"),
                }
            )
            device_cards.append(
                tone_card(
                    (
                        f"<div class='meta'>{html.escape(str(device.get('name', device_id)))}</div>"
                        f"<div class='meta'>{html.escape(str(device.get('type', 'bm200')))}</div>"
                        f"<div class='hero-soc'>{html.escape(str(device.get('soc', '-')))}%</div>"
                        f"<div class='meta'>{voltage_text} / {temperature_text}</div>"
                        f"<div style='margin-top:0.65rem'>{badge}</div>"
                        "<div class='footer-row'>"
                        f"<a href='/device?device_id={quote(device_id)}'>Open device</a>"
                        "</div>"
                    ),
                    tone=tone,
                )
            )
    add_card = tone_card(
        (
            "<div style='display:flex;min-height:198px;align-items:center;justify-content:center;"
            "font-size:4rem;color:var(--accent-orange);font-weight:300'>+</div>"
            "<div class='meta' style='text-align:center'>"
            "<a href='/devices'>Add Device</a>"
            "</div>"
        ),
        tone="orange",
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
                '<a class="secondary-button" href="/management">Management</a>'
                "</div>"
            ),
        )
        + banner_strip(
            "Bluetooth device status is shown directly on each card. Classic-only "
            "or unavailable BLE adapters remain visible as controlled warnings.",
            kind="warning",
            trailing="<a class='secondary-button' href='/devices'>Add Device</a>",
        )
        + section_card(
            title="Battery Overview",
            subtitle=(
                "The default landing page mirrors the mobile app journey: "
                "check live state first, then dive into device detail or history."
            ),
            body=f'<div class="device-grid">{"".join(device_cards)}{add_card}</div>',
        )
        + chart_card(
            chart_id=chart_id,
            title="Fleet Trend",
            subtitle="Overview chart styled after the BM300 battery landing page.",
            points=chart_points,
            range_options=(("raw", "Live"), ("30", "30 days")),
            default_range="raw",
            default_metric="voltage",
            legend=legend or [("No devices", "#95a3b8")],
        )
    )
    return app_document(
        title="BMGateway Battery",
        body=body,
        active_nav="battery",
        primary_device_id=primary_device_id,
        script=chart_script(chart_id),
    )


def render_devices_html(
    *,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
) -> str:
    primary_device_id = _primary_device_id(snapshot, devices)
    snapshot_devices = {
        str(device.get("id", "")): device
        for device in cast(list[object], snapshot.get("devices", []))
        if isinstance(device, dict)
    }
    cards: list[str] = []
    battery_types = {
        "bm200": "Lead-Acid Battery",
        "bm300pro": "Lithium Battery",
    }
    for index, device in enumerate(devices):
        device_id = str(device.get("id", ""))
        tone = _device_tone(index, str(snapshot_devices.get(device_id, {}).get("state", "")))
        runtime = snapshot_devices.get(device_id, {})
        state_tile = metric_tile(
            label="Status",
            value=str(runtime.get("state", "configured")).title(),
            tone=tone,
            subvalue="Runtime signal",
        )
        signal_tile = metric_tile(
            label="Signal",
            value=(f"{runtime.get('rssi')} dBm" if runtime.get("rssi") is not None else "-"),
            tone="blue",
            subvalue="Last seen adapter RSSI",
        )
        battery_type = html.escape(
            battery_types.get(str(device.get("type", "bm200")), "Unknown Battery")
        )
        enabled_badge = status_badge(
            "Enabled" if bool(device.get("enabled", False)) else "Disabled",
            kind="ok" if bool(device.get("enabled", False)) else "offline",
        )
        device_type_text = html.escape(str(device.get("type", "bm200")))
        device_name_text = html.escape(str(device.get("name", device_id)))
        device_mac_text = html.escape(str(device.get("mac", "")))
        cards.append(
            section_card(
                body=(
                    "<div class='settings-row' style='padding-top:0;"
                    "padding-bottom:0.8rem;border-bottom:0'>"
                    f"<div><div class='settings-label'>{device_type_text}</div>"
                    f"<div class='section-title'>{device_name_text}</div>"
                    f"<div class='muted-note'>Serial / MAC: {device_mac_text}</div>"
                    "</div>"
                    f"<a class='ghost-button' href='/management'>Edit</a>"
                    "</div>"
                    "<div class='two-column-grid'>"
                    f"{state_tile}"
                    f"{signal_tile}"
                    "</div>"
                    "<div class='settings-row' style='padding-bottom:0;border-bottom:0'>"
                    f"<div class='pill-chip'>{battery_type}</div>"
                    f"{enabled_badge}"
                    "</div>"
                ),
                classes=f"tone-card {tone}",
            )
        )
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
                '<a class="secondary-button" href="/management">Management</a>'
                "</div>"
            ),
        )
        + section_card(
            title="Configured Devices",
            subtitle="Gateway-ready device registry",
            body="".join(cards),
        )
        + section_card(
            title="Add Device",
            subtitle="Use the existing live add-device flow from the management surface.",
            body="<a class='primary-button' href='/management#add-device'>Add Device</a>",
        )
    )
    return app_document(
        title="BMGateway Devices",
        body=body,
        active_nav="devices",
        primary_device_id=primary_device_id,
    )


def render_settings_html(
    *,
    config: AppConfig,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
) -> str:
    primary_device_id = _primary_device_id(snapshot, devices)
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
    mqtt_ha_enabled = (
        "enabled" if config.mqtt.enabled and config.home_assistant.enabled else "disabled"
    )
    web_enabled = f"{config.web.host}:{config.web.port}" if config.web.enabled else "disabled"
    daily_retention = (
        "unlimited"
        if config.retention.daily_retention_days == 0
        else f"{config.retention.daily_retention_days} days"
    )
    body = (
        top_header(
            title="Settings",
            subtitle=(
                "Gateway-safe settings adapted from the BM300 app. Unsupported "
                "vehicle-only features are intentionally excluded."
            ),
            eyebrow="Settings",
            right=(
                '<div class="hero-actions">'
                '<a class="secondary-button" href="/management">Advanced Config</a>'
                "</div>"
            ),
        )
        + section_card(
            title="Gateway Settings",
            subtitle="Live settings summary",
            body=(
                f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
                + settings_row("Live polling", config.gateway.reader_mode)
                + settings_row("Poll interval", f"{config.gateway.poll_interval_seconds} seconds")
                + settings_row("MQTT / Home Assistant", mqtt_ha_enabled)
                + settings_row("Web interface", web_enabled)
                + settings_row("Raw retention", f"{config.retention.raw_retention_days} days")
                + settings_row("Daily rollup retention", daily_retention)
            ),
        )
        + section_card(
            title="Device Alerts",
            subtitle="Gateway-side adaptations of the BM300 settings rhythm.",
            body=(
                settings_row("Daily power notification", "Not implemented in backend yet")
                + settings_row("Low voltage alarm", "Back-end threshold support missing")
                + settings_row("Power alarm", "Back-end threshold support missing")
                + settings_row("Export-ready history", "Available through CLI / database")
            ),
        )
        + section_card(
            title="Links",
            subtitle="Operational entry points",
            body=(
                settings_row("Export Data", "Use CLI history commands")
                + settings_row("Unit / Currency", "Not applicable to BMGateway")
                + settings_row("Language", "English")
            ),
        )
    )
    return app_document(
        title="BMGateway Settings",
        body=body,
        active_nav="settings",
        primary_device_id=primary_device_id,
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
) -> str:
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
    soc = _format_number(summary.get("soc"), digits=0, suffix="%")
    rssi = summary.get("rssi")
    chart_id = f"device-chart-{quote(device_id)}".replace("%", "")
    soc_percent = min(max(_coerce_float(summary.get("soc"), 0.0), 0.0), 100.0)
    gauge_degrees = soc_percent * 3.6
    body = (
        top_header(
            title=f"{summary.get('name', device_id)}",
            subtitle=(
                f"Device detail for {device_id}. Real history, live runtime "
                "status, and gateway-focused health signals."
            ),
            eyebrow="Battery Detail",
            right=(
                '<div class="hero-actions"><a class="secondary-button" href="/">Management</a>'
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
                f'<div class="soc-gauge" style="background: conic-gradient(var(--accent-green) '
                f"0deg {gauge_degrees}deg, rgba(191, 207, 198, 0.55) "
                f'{gauge_degrees}deg 360deg);">'
                '<div class="soc-gauge-content">'
                '<div class="soc-gauge-label">SoC</div>'
                f'<div class="soc-gauge-value">{html.escape(soc)}</div>'
                "</div></div></div>"
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
            value=f"{rssi} dBm" if rssi is not None else "-",
            tone="orange",
            subvalue="Gateway-side BLE quality indicator",
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
                + summary_card("Last Seen", _display_timestamp(summary.get("last_seen", "unknown")))
                + summary_card("Driver Status", html.escape(str(summary.get("state", "unknown"))))
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
            points=_chart_points(raw_history, daily_history),
            range_options=(
                ("raw", "Recent raw"),
                ("30", "30 days"),
                ("90", "90 days"),
                ("365", "1 year"),
            ),
            default_range="30",
            default_metric="voltage",
            legend=[(str(summary.get("name", device_id)), "#17c45a")],
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
        active_nav="device",
        script=chart_script(chart_id),
    )


def render_history_html(
    *,
    device_id: str,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
) -> str:
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
            title=f"{device_id} History",
            subtitle=(
                "Chart-first history dashboard with calmer hierarchy: key "
                "metrics and switchable trend views first, raw tables second."
            ),
            eyebrow="History",
            right=(
                '<div class="hero-actions"><a class="secondary-button" href="/">Management</a>'
                f'<a class="secondary-button" href="/device?device_id={quote(device_id)}">'
                "Device Detail</a></div>"
            ),
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
            points=_chart_points(raw_history, daily_history),
            range_options=(
                ("raw", "Recent raw"),
                ("30", "30 days"),
                ("90", "90 days"),
                ("365", "1 year"),
            ),
            default_range="30",
            default_metric="soc",
            legend=[(device_id, "#4f8df7")],
        )
        + sections
    )
    return app_document(
        title=f"{escaped_device_id} History",
        body=body,
        active_nav="history",
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
        f"<td>{_escape_cell(row['error_count'])}</td>"
        "</tr>"
        for row in monthly_history
    )
    raw_rows_html = raw_rows or "<tr><td colspan='6'>No data</td></tr>"
    daily_rows_html = daily_rows or "<tr><td colspan='7'>No data</td></tr>"
    monthly_rows_html = monthly_rows or "<tr><td colspan='7'>No data</td></tr>"
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
                "<th>Avg V</th><th>Avg SoC</th><th>Error count</th></tr></thead>"
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
                "<th>Avg V</th><th>Avg SoC</th><th>Error count</th></tr></thead>"
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
) -> list[str]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    devices.append(
        Device(
            id=device_id.strip(),
            type=device_type.strip(),
            name=device_name.strip(),
            mac=normalize_mac_address(device_mac),
            enabled=True,
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
                payload = json.dumps(snapshot, indent=2, sort_keys=True).encode("utf-8")
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
                self._send_json(snapshot)
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
                    raw_history=fetch_recent_history(database_path, device_id=device_id, limit=200),
                    daily_history=fetch_daily_history(
                        database_path,
                        device_id=device_id,
                        limit=365,
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
                )
                self._send_html(html)
                return

            if parsed.path == "/history":
                params = parse_qs(parsed.query)
                device_id = params.get("device_id", [""])[0]
                html = render_history_html(
                    device_id=device_id,
                    raw_history=fetch_recent_history(database_path, device_id=device_id, limit=200),
                    daily_history=fetch_daily_history(
                        database_path,
                        device_id=device_id,
                        limit=365,
                    ),
                    monthly_history=fetch_monthly_history(
                        database_path,
                        device_id=device_id,
                        limit=24,
                    ),
                )
                self._send_html(html)
                return

            if parsed.path == "/devices":
                html = render_devices_html(snapshot=snapshot, devices=serialized_devices)
                self._send_html(html)
                return

            if parsed.path == "/settings":
                html = render_settings_html(
                    config=config,
                    snapshot=snapshot,
                    devices=serialized_devices,
                )
                self._send_html(html)
                return

            if parsed.path == "/management":
                config_text, devices_text = _config_and_registry_texts(config_path)
                message = parse_qs(parsed.query).get("message", [""])[0]
                html = render_management_html(
                    snapshot=snapshot,
                    storage_summary=fetch_storage_summary(database_path),
                    devices=serialized_devices,
                    config_text=config_text,
                    devices_text=devices_text,
                    contract=contract,
                    message=message,
                )
                self._send_html(html)
                return

            html = render_battery_html(snapshot=snapshot, devices=serialized_devices)
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
                self.send_header("Location", "/management?message=Configuration%20saved")
                self.end_headers()
                return

            if parsed.path == "/devices/add":
                errors = add_device_from_form(
                    config_path=config_path,
                    device_id=form.get("device_id", [""])[0],
                    device_type=form.get("device_type", ["bm200"])[0],
                    device_name=form.get("device_name", [""])[0],
                    device_mac=form.get("device_mac", [""])[0],
                )
                if errors:
                    config_text, devices_text = _config_and_registry_texts(config_path)
                    config, snapshot, database_path = self._load_current()
                    configured_devices = load_device_registry(config.device_registry_path)
                    html = render_management_html(
                        snapshot=snapshot,
                        storage_summary=fetch_storage_summary(database_path),
                        devices=[device.to_dict() for device in configured_devices],
                        config_text=config_text,
                        devices_text=devices_text,
                        contract=build_contract(config, configured_devices),
                        message="Validation failed: " + "; ".join(errors),
                    )
                    self._send_html(html, status=400)
                    return

                run_once_via_cli(config_path, state_dir=state_dir)
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/management?" + urlencode({"message": "Device added. Live polling enabled."}),
                )
                self.end_headers()
                return

            if parsed.path == "/actions/run-once":
                completed = run_once_via_cli(config_path, state_dir=state_dir)
                message = "Run completed" if completed.returncode == 0 else "Run failed"
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header("Location", "/management?" + urlencode({"message": message}))
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
                    "/management?" + urlencode({"message": "History pruned"}),
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
