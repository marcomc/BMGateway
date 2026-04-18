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
from urllib.parse import parse_qs, quote, urlparse

from .config import AppConfig, load_config, write_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import load_device_registry, validate_devices, write_device_registry
from .runtime import database_file_path, state_file_path
from .state_store import (
    fetch_daily_history,
    fetch_monthly_history,
    fetch_recent_history,
    fetch_storage_summary,
    load_snapshot,
    prune_history,
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
    banner = f"<p><strong>{html.escape(message)}</strong></p>" if message else ""
    counts = cast(dict[str, object], storage_summary.get("counts", {}))
    gateway_contract = cast(dict[str, object], contract.get("gateway", {}))
    contract_devices = cast(list[object], contract.get("devices", []))
    gateway_state_topic = html.escape(str(gateway_contract.get("state_topic", "")))
    gateway_discovery_topic = html.escape(str(gateway_contract.get("discovery_topic", "")))
    device_contract_count = len(contract_devices) if isinstance(contract_devices, list) else 0
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>BMGateway Management</title>
    <style>
      body {{ font-family: sans-serif; margin: 2rem; background: #f4f6f8; color: #132029; }}
      .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }}
      .panel {{
        background: white;
        border-radius: 14px;
        padding: 1rem;
        box-shadow: 0 2px 10px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
      }}
      textarea {{ width: 100%; min-height: 18rem; font-family: monospace; }}
      code {{ background: #edf2f7; padding: 0.125rem 0.375rem; border-radius: 6px; }}
      button {{ padding: 0.6rem 0.9rem; }}
      ul {{ margin: 0; padding-left: 1.25rem; }}
      table {{ width: 100%; border-collapse: collapse; background: white; }}
      th, td {{ padding: 0.55rem; border-bottom: 1px solid #ddd; text-align: left; }}
    </style>
  </head>
  <body>
    <h1>BMGateway Management</h1>
    {banner}
    <div class="grid">
      <div class="panel">
        <strong>Latest snapshot</strong><br>
        <code>{html.escape(str(snapshot.get("generated_at", "missing")))}</code>
      </div>
      <div class="panel">
        <strong>Gateway snapshots</strong><br>{counts.get("gateway_snapshots", 0)}
      </div>
      <div class="panel">
        <strong>Raw readings / daily rollups</strong><br>
        {counts.get("device_readings", 0)} / {counts.get("device_daily_rollups", 0)}
      </div>
    </div>
    <div class="panel">
      <h2>Actions</h2>
      <form method="post" action="/actions/run-once">
        <button type="submit">Run One Collection Cycle</button>
      </form>
      <form method="post" action="/actions/prune-history" style="margin-top: 0.75rem;">
        <button type="submit">Prune History Using Retention Settings</button>
      </form>
    </div>
    <div class="panel">
      <h2>History</h2>
      <ul>
        {_management_links(snapshot)}
      </ul>
      <p>
        JSON APIs:
        <code>/api/status</code>,
        <code>/api/config</code>,
        <code>/api/devices</code>,
        <code>/api/ha/contract</code>,
        <code>/api/ha/discovery</code>,
        <code>/api/storage</code>,
        <code>/api/history?device_id=&lt;id&gt;&amp;kind=daily</code>
      </p>
    </div>
    <div class="panel">
      <h2>Configured Devices</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Type</th><th>Name</th><th>MAC</th><th>Enabled</th>
          </tr>
        </thead>
        <tbody>{_device_table_rows(devices)}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Home Assistant Contract</h2>
      <p><strong>Gateway state topic:</strong> <code>{gateway_state_topic}</code></p>
      <p><strong>Gateway discovery topic:</strong> <code>{gateway_discovery_topic}</code></p>
      <p><strong>Device discovery payloads:</strong> {device_contract_count}</p>
    </div>
    <div class="panel">
      <h2>Storage Summary</h2>
      <table>
        <thead>
          <tr>
            <th>Device</th><th>Raw samples</th><th>Raw first</th><th>Raw last</th>
            <th>Daily days</th><th>Daily first</th><th>Daily last</th>
          </tr>
        </thead>
        <tbody>{_storage_rows(storage_summary)}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Configuration</h2>
      <form method="post" action="/config">
        <p><strong>config.toml</strong></p>
        <textarea name="config_toml">{html.escape(config_text)}</textarea>
        <p><strong>devices.toml</strong></p>
        <textarea name="devices_toml">{html.escape(devices_text)}</textarea>
        <p><button type="submit">Validate and Save</button></p>
      </form>
    </div>
  </body>
</html>
"""


def render_history_html(
    *,
    device_id: str,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
) -> str:
    raw_rows = "\n".join(
        f"<tr><td>{row['ts']}</td><td>{row['voltage']}</td><td>{row['soc']}</td><td>{row['state']}</td><td>{row['error_code']}</td></tr>"
        for row in raw_history
    )
    daily_rows = "\n".join(
        f"<tr><td>{row['day']}</td><td>{row['samples']}</td><td>{row['min_voltage']}</td><td>{row['max_voltage']}</td><td>{row['avg_voltage']}</td><td>{row['avg_soc']}</td><td>{row['error_count']}</td></tr>"
        for row in daily_history
    )
    monthly_rows = "\n".join(
        f"<tr><td>{row['month']}</td><td>{row['samples']}</td><td>{row['min_voltage']}</td><td>{row['max_voltage']}</td><td>{row['avg_voltage']}</td><td>{row['avg_soc']}</td><td>{row['error_count']}</td></tr>"
        for row in monthly_history
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{device_id} History</title>
    <style>
      body {{ font-family: sans-serif; margin: 2rem; background: #f4f6f8; color: #132029; }}
      table {{ width: 100%; border-collapse: collapse; background: white; margin-bottom: 2rem; }}
      th, td {{ padding: 0.6rem; border-bottom: 1px solid #ddd; text-align: left; }}
    </style>
  </head>
  <body>
    <p><a href="/">Back</a></p>
    <h1>{html.escape(device_id)} History</h1>
    <h2>Recent raw readings</h2>
    <table>
      <thead><tr><th>Timestamp</th><th>Voltage</th><th>SoC</th><th>State</th><th>Error</th></tr></thead>
      <tbody>{raw_rows or "<tr><td colspan='5'>No data</td></tr>"}</tbody>
    </table>
    <h2>Daily rollups</h2>
    <table>
      <thead>
        <tr>
          <th>Day</th><th>Samples</th><th>Min V</th><th>Max V</th>
          <th>Avg V</th><th>Avg SoC</th><th>Error count</th>
        </tr>
      </thead>
      <tbody>{daily_rows or "<tr><td colspan='7'>No data</td></tr>"}</tbody>
    </table>
    <h2>Monthly summaries</h2>
    <table>
      <thead>
        <tr>
          <th>Month</th><th>Samples</th><th>Min V</th><th>Max V</th>
          <th>Avg V</th><th>Avg SoC</th><th>Error count</th>
        </tr>
      </thead>
      <tbody>{monthly_rows or "<tr><td colspan='7'>No data</td></tr>"}</tbody>
    </table>
  </body>
</html>
"""


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

            if parsed.path == "/api/history":
                params = parse_qs(parsed.query)
                device_id = params.get("device_id", [""])[0]
                kind = params.get("kind", ["daily"])[0]
                limit = int(params.get("limit", ["365"])[0])
                if kind == "raw":
                    self._send_json(
                        fetch_recent_history(database_path, device_id=device_id, limit=limit)
                    )
                elif kind == "monthly":
                    self._send_json(
                        fetch_monthly_history(database_path, device_id=device_id, limit=limit)
                    )
                else:
                    self._send_json(
                        fetch_daily_history(database_path, device_id=device_id, limit=limit)
                    )
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
                self.send_header("Location", "/?message=Configuration%20saved")
                self.end_headers()
                return

            if parsed.path == "/actions/run-once":
                completed = run_once_via_cli(config_path, state_dir=state_dir)
                message = "Run completed" if completed.returncode == 0 else "Run failed"
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header("Location", f"/?message={message.replace(' ', '%20')}")
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
                self.send_header("Location", "/?message=History%20pruned")
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
