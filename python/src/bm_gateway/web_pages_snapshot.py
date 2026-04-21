"""Snapshot/status page rendering for the BMGateway web interface."""

from __future__ import annotations

import html

from . import __version__
from . import web_pages as shared


def render_snapshot_html(snapshot: dict[str, object]) -> str:
    snapshot = shared._snapshot_with_version(snapshot)
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
