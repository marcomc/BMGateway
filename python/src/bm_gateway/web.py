"""Web interfaces for BMGateway."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import AppConfig, load_config, write_config
from .device_registry import load_device_registry, validate_devices, write_device_registry
from .runtime import database_file_path, state_file_path
from .state_store import fetch_counts, fetch_daily_history, fetch_recent_history, load_snapshot


def render_snapshot_html(snapshot: dict[str, object]) -> str:
    devices = snapshot.get("devices", [])
    device_items = []
    for device in devices if isinstance(devices, list) else []:
        if not isinstance(device, dict):
            continue
        device_items.append(
            "<tr>"
            f"<td>{device.get('name')}</td>"
            f"<td>{device.get('type')}</td>"
            f"<td>{device.get('voltage')}</td>"
            f"<td>{device.get('soc')}</td>"
            f"<td>{device.get('connected')}</td>"
            f"<td>{device.get('rssi')}</td>"
            "</tr>"
        )

    rows = "\n".join(device_items) or "<tr><td colspan='6'>No devices</td></tr>"
    gateway_name = snapshot.get("gateway_name", "unknown")
    adapter = snapshot.get("active_adapter", "unknown")
    devices_online = snapshot.get("devices_online", 0)
    devices_total = snapshot.get("devices_total", 0)
    mqtt_connected = snapshot.get("mqtt_connected", False)
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
    <p>Generated at <code>{snapshot.get("generated_at", "unknown")}</code></p>
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
                f'<li><a href="/history?device_id={device_id}">{device_id} history</a></li>'
            )
    return "\n".join(items) or "<li>No devices available</li>"


def render_management_html(
    *,
    snapshot: dict[str, object],
    counts: dict[str, int],
    config_text: str,
    devices_text: str,
    message: str = "",
) -> str:
    banner = f"<p><strong>{message}</strong></p>" if message else ""
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
    </style>
  </head>
  <body>
    <h1>BMGateway Management</h1>
    {banner}
    <div class="grid">
      <div class="panel">
        <strong>Latest snapshot</strong><br><code>{snapshot.get("generated_at", "missing")}</code>
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
    </div>
    <div class="panel">
      <h2>History</h2>
      <ul>
        {_management_links(snapshot)}
      </ul>
      <p>
        JSON APIs: <code>/api/status</code>, <code>/api/config</code>,
        <code>/api/history?device_id=&lt;id&gt;&amp;kind=daily</code>
      </p>
    </div>
    <div class="panel">
      <h2>Configuration</h2>
      <form method="post" action="/config">
        <p><strong>config.toml</strong></p>
        <textarea name="config_toml">{config_text}</textarea>
        <p><strong>devices.toml</strong></p>
        <textarea name="devices_toml">{devices_text}</textarea>
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
) -> str:
    raw_rows = "\n".join(
        f"<tr><td>{row['ts']}</td><td>{row['voltage']}</td><td>{row['soc']}</td><td>{row['state']}</td><td>{row['error_code']}</td></tr>"
        for row in raw_history
    )
    daily_rows = "\n".join(
        f"<tr><td>{row['day']}</td><td>{row['samples']}</td><td>{row['min_voltage']}</td><td>{row['max_voltage']}</td><td>{row['avg_voltage']}</td><td>{row['avg_soc']}</td><td>{row['error_count']}</td></tr>"
        for row in daily_history
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
    <h1>{device_id} History</h1>
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


def build_run_once_command(config_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "bm_gateway",
        "--config",
        str(config_path),
        "run",
        "--once",
    ]


def run_once_via_cli(config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        build_run_once_command(config_path),
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
            if parsed.path == "/api/config":
                config_text, devices_text = _config_and_registry_texts(config_path)
                self._send_json({"config_toml": config_text, "devices_toml": devices_text})
                return

            config, snapshot, database_path = self._load_current()
            if parsed.path == "/api/status":
                self._send_json(snapshot)
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
                )
                self._send_html(html)
                return

            config_text, devices_text = _config_and_registry_texts(config_path)
            message = parse_qs(parsed.query).get("message", [""])[0]
            counts = fetch_counts(database_path)
            html = render_management_html(
                snapshot=snapshot,
                counts=counts,
                config_text=config_text,
                devices_text=devices_text,
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
                        counts={
                            "gateway_snapshots": 0,
                            "device_readings": 0,
                            "device_daily_rollups": 0,
                        },
                        config_text=config_toml,
                        devices_text=devices_toml,
                        message="Validation failed: " + "; ".join(errors),
                    )
                    self._send_html(html, status=400)
                    return

                self.send_response(303)
                self.send_header("Location", "/?message=Configuration%20saved")
                self.end_headers()
                return

            if parsed.path == "/actions/run-once":
                completed = run_once_via_cli(config_path)
                message = "Run completed" if completed.returncode == 0 else "Run failed"
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header("Location", f"/?message={message.replace(' ', '%20')}")
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
