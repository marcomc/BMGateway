"""Web service entrypoints for BMGateway."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .config import AppConfig, load_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import COLOR_CATALOG, default_color_key, load_device_registry
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
from .web_actions import (
    _config_and_registry_texts,
    add_device_from_form,
    build_run_once_command,
    restart_system_service,
    run_once_via_cli,
    schedule_host_reboot,
    update_bluetooth_preferences,
    update_config_from_text,
    update_device_from_form,
    update_device_icon,
    update_gateway_preferences,
    update_home_assistant_preferences,
    update_mqtt_preferences,
    update_web_preferences,
)
from .web_assets import (
    apple_touch_icon_bytes,
    favicon_png_bytes,
    favicon_svg_source,
    web_manifest_source,
)
from .web_pages import (
    RECENT_CHART_HISTORY_LIMIT,
    _add_device_form_html,
    _battery_form_script,
    _bool_from_form,
    _chart_points,
    _discover_bluetooth_adapters,
    _fleet_chart_points,
    _optional_float_from_form,
    _optional_int_from_form,
    _parse_custom_curve_from_form,
    _parse_history_limit,
    _snapshot_with_version,
    _string_from_form,
    render_add_device_html,
    render_device_html,
    render_devices_html,
    render_edit_device_html,
    render_history_html,
    render_home_html,
    render_management_html,
    render_reboot_pending_html,
    render_settings_html,
    render_snapshot_html,
)
from .web_support import read_text

__all__ = [
    "add_device_from_form",
    "build_run_once_command",
    "render_add_device_html",
    "render_home_html",
    "render_device_html",
    "render_devices_html",
    "render_edit_device_html",
    "render_history_html",
    "render_management_html",
    "render_reboot_pending_html",
    "render_settings_html",
    "render_snapshot_html",
    "serve_management",
    "serve_snapshot",
    "update_bluetooth_preferences",
    "update_config_from_text",
    "update_device_from_form",
    "update_device_icon",
    "update_gateway_preferences",
    "update_home_assistant_preferences",
    "update_mqtt_preferences",
    "update_web_preferences",
    "_add_device_form_html",
    "_battery_form_script",
    "_chart_points",
    "_discover_bluetooth_adapters",
]


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

        def _send_bytes(self, payload: bytes, *, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
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

            if parsed.path == "/favicon.svg":
                self._send_bytes(
                    favicon_svg_source().encode("utf-8"),
                    content_type="image/svg+xml; charset=utf-8",
                )
                return
            if parsed.path in {"/favicon.png", "/favicon.ico"}:
                self._send_bytes(favicon_png_bytes(), content_type="image/png")
                return
            if parsed.path == "/apple-touch-icon.png":
                self._send_bytes(apple_touch_icon_bytes(), content_type="image/png")
                return
            if parsed.path == "/site.webmanifest":
                self._send_bytes(
                    web_manifest_source().encode("utf-8"),
                    content_type="application/manifest+json; charset=utf-8",
                )
                return

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
                configured_device: dict[str, object] | None = next(
                    (
                        device
                        for device in serialized_devices
                        if str(device.get("id", "")) == device_id
                    ),
                    None,
                )
                if isinstance(snapshot_devices, list):
                    for device in snapshot_devices:
                        if isinstance(device, dict) and str(device.get("id", "")) == device_id:
                            snapshot_device = device
                            break
                merged_device_summary: dict[str, object] | None = None
                if configured_device is not None or snapshot_device is not None:
                    merged_device_summary = {}
                    if configured_device is not None:
                        merged_device_summary.update(configured_device)
                    if snapshot_device is not None:
                        merged_device_summary.update(snapshot_device)
                html = render_device_html(
                    device_id=device_id,
                    raw_history=fetch_recent_history(
                        database_path,
                        device_id=device_id,
                        limit=RECENT_CHART_HISTORY_LIMIT,
                    ),
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
                    device_summary=merged_device_summary,
                    show_chart_markers=config.web.show_chart_markers,
                    theme_preference=config.web.appearance,
                    default_chart_range=config.web.default_chart_range,
                    default_chart_metric=config.web.default_chart_metric,
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
                        fetch_recent_history(
                            database_path,
                            device_id=device_id,
                            limit=RECENT_CHART_HISTORY_LIMIT,
                        )
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
                    theme_preference=config.web.appearance,
                    default_chart_range=config.web.default_chart_range,
                    default_chart_metric=config.web.default_chart_metric,
                )
                self._send_html(html)
                return

            if parsed.path == "/devices":
                message = parse_qs(parsed.query).get("message", [""])[0]
                html = render_devices_html(
                    snapshot=snapshot,
                    devices=serialized_devices,
                    message=message,
                    theme_preference=config.web.appearance,
                )
                self._send_html(html)
                return

            if parsed.path == "/rebooting":
                self._send_html(render_reboot_pending_html(theme_preference=config.web.appearance))
                return

            if parsed.path == "/devices/new":
                message = parse_qs(parsed.query).get("message", [""])[0]
                reserved_color_keys = {
                    str(device.get("color_key", "")).strip()
                    for device in serialized_devices
                    if str(device.get("color_key", "")).strip() in COLOR_CATALOG
                }
                self._send_html(
                    render_add_device_html(
                        message=message,
                        theme_preference=config.web.appearance,
                        selected_color_key=default_color_key(used_colors=reserved_color_keys),
                        reserved_color_keys=reserved_color_keys,
                    )
                )
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
                        render_devices_html(
                            snapshot=snapshot,
                            devices=serialized_devices,
                            theme_preference=config.web.appearance,
                        ),
                        status=404,
                    )
                    return
                message = parse_qs(parsed.query).get("message", [""])[0]
                reserved_color_keys = {
                    str(item.get("color_key", "")).strip()
                    for item in serialized_devices
                    if str(item.get("id", "")) != device_id
                    and str(item.get("color_key", "")).strip() in COLOR_CATALOG
                }
                self._send_html(
                    render_edit_device_html(
                        device=device,
                        message=message,
                        theme_preference=config.web.appearance,
                        reserved_color_keys=reserved_color_keys,
                    )
                )
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
                    config_text=read_text(config_path),
                    devices_text=read_text(config.device_registry_path),
                    contract=contract,
                    theme_preference=config.web.appearance,
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
                    config_text=read_text(config_path),
                    devices_text=read_text(config.device_registry_path),
                    contract=contract,
                    theme_preference=config.web.appearance,
                )
                self._send_html(html)
                return

            battery_chart_points, battery_legend = _fleet_chart_points(
                database_path=database_path,
                devices=serialized_devices,
            )
            html = render_home_html(
                snapshot=snapshot,
                devices=serialized_devices,
                chart_points=battery_chart_points,
                legend=battery_legend,
                show_chart_markers=config.web.show_chart_markers,
                visible_device_limit=config.web.visible_device_limit,
                appearance=config.web.appearance,
                default_chart_range=config.web.default_chart_range,
                default_chart_metric=config.web.default_chart_metric,
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
                    config = load_config(config_path)
                    html = render_management_html(
                        snapshot={"devices": []},
                        config=config,
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
                        theme_preference=config.web.appearance,
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
                    device_type=form.get("device_type", ["bm200"])[0],
                    device_name=form.get("device_name", [""])[0],
                    device_mac=form.get("device_mac", [""])[0],
                    battery_family=form.get("battery_family", ["lead_acid"])[0],
                    battery_profile=form.get("battery_profile", ["regular_lead_acid"])[0],
                    custom_soc_mode=form.get("custom_soc_mode", ["intelligent_algorithm"])[0],
                    custom_voltage_curve=_parse_custom_curve_from_form(form),
                    color_key=form.get("color_key", ["green"])[0],
                    installed_in_vehicle=_bool_from_form(form, "installed_in_vehicle"),
                    vehicle_type=_string_from_form(form, "vehicle_type"),
                    battery_brand=_string_from_form(form, "battery_brand"),
                    battery_model=_string_from_form(form, "battery_model"),
                    battery_nominal_voltage=_optional_int_from_form(
                        form,
                        "battery_nominal_voltage",
                    ),
                    battery_capacity_ah=_optional_float_from_form(form, "battery_capacity_ah"),
                    battery_production_year=_optional_int_from_form(
                        form,
                        "battery_production_year",
                    ),
                )
                if errors:
                    self._send_html(
                        render_add_device_html(
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
                            selected_color_key=form.get("color_key", ["green"])[0],
                            reserved_color_keys={
                                device.color_key
                                for device in load_device_registry(config.device_registry_path)
                            },
                        ),
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
                config = load_config(config_path)
                old_device_id = form.get("old_device_id", form.get("device_id", [""]))[0]
                submitted_device_id = form.get("device_id", [""])[0]
                errors = update_device_from_form(
                    config_path=config_path,
                    database_path=database_file_path(config, state_dir=state_dir),
                    device_id=old_device_id,
                    new_device_id=submitted_device_id,
                    device_type=form.get("device_type", ["bm200"])[0],
                    device_name=form.get("device_name", [""])[0],
                    device_mac=form.get("device_mac", [""])[0],
                    battery_family=form.get("battery_family", ["lead_acid"])[0],
                    battery_profile=form.get("battery_profile", ["regular_lead_acid"])[0],
                    custom_soc_mode=form.get("custom_soc_mode", ["intelligent_algorithm"])[0],
                    custom_voltage_curve=_parse_custom_curve_from_form(form),
                    color_key=form.get("color_key", ["green"])[0],
                    installed_in_vehicle=_bool_from_form(form, "installed_in_vehicle"),
                    vehicle_type=_string_from_form(form, "vehicle_type"),
                    battery_brand=_string_from_form(form, "battery_brand"),
                    battery_model=_string_from_form(form, "battery_model"),
                    battery_nominal_voltage=_optional_int_from_form(
                        form,
                        "battery_nominal_voltage",
                    ),
                    battery_capacity_ah=_optional_float_from_form(form, "battery_capacity_ah"),
                    battery_production_year=_optional_int_from_form(
                        form,
                        "battery_production_year",
                    ),
                )
                if errors:
                    configured_devices = load_device_registry(config.device_registry_path)
                    device = next(
                        (item.to_dict() for item in configured_devices if item.id == old_device_id),
                        {
                            "id": submitted_device_id,
                            "type": form.get("device_type", ["bm200"])[0],
                            "name": form.get("device_name", [""])[0],
                            "mac": form.get("device_mac", [""])[0],
                            "color_key": form.get("color_key", ["green"])[0],
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
                                "nominal_voltage": _optional_int_from_form(
                                    form,
                                    "battery_nominal_voltage",
                                ),
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
                    device["id"] = submitted_device_id
                    device["type"] = form.get("device_type", ["bm200"])[0]
                    device["name"] = form.get("device_name", [""])[0]
                    device["mac"] = form.get("device_mac", [""])[0]
                    self._send_html(
                        render_edit_device_html(
                            device=device,
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
                            reserved_color_keys={
                                item.color_key
                                for item in configured_devices
                                if item.id != old_device_id
                            },
                            original_device_id=old_device_id,
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
                            "device_id": submitted_device_id,
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
                        theme_preference=config.web.appearance,
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: settings values must be numeric",
                            theme_preference=config.web.appearance,
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
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

            if parsed.path == "/settings/mqtt":
                try:
                    mqtt_port = int(form.get("mqtt_port", ["1883"])[0])
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: MQTT port must be numeric",
                            theme_preference=config.web.appearance,
                        ),
                        status=400,
                    )
                    return
                errors = update_mqtt_preferences(
                    config_path=config_path,
                    mqtt_enabled=_bool_from_form(form, "mqtt_enabled"),
                    mqtt_host=form.get("mqtt_host", ["mqtt.local"])[0],
                    mqtt_port=mqtt_port,
                    mqtt_username=form.get("mqtt_username", ["mqtt-user"])[0],
                    mqtt_password=form.get("mqtt_password", ["CHANGE_ME"])[0],
                    mqtt_base_topic=form.get("mqtt_base_topic", ["bm_gateway"])[0],
                    mqtt_discovery_prefix=form.get("mqtt_discovery_prefix", ["homeassistant"])[0],
                    mqtt_retain_discovery=_bool_from_form(form, "mqtt_retain_discovery"),
                    mqtt_retain_state=_bool_from_form(form, "mqtt_retain_state"),
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
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

            if parsed.path == "/settings/home-assistant":
                errors = update_home_assistant_preferences(
                    config_path=config_path,
                    home_assistant_enabled=_bool_from_form(form, "home_assistant_enabled"),
                    home_assistant_status_topic=form.get(
                        "home_assistant_status_topic", ["homeassistant/status"]
                    )[0],
                    home_assistant_gateway_device_id=form.get(
                        "home_assistant_gateway_device_id", ["bm_gateway"]
                    )[0],
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: bluetooth values must be numeric",
                            theme_preference=config.web.appearance,
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
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
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
                config, snapshot, current_database_path = self._load_current()
                settings_section = form.get("settings_section", [""])[0]
                web_enabled: bool | None = None
                web_host: str | None = None
                web_port: int | None = None
                show_chart_markers: bool | None = None
                visible_device_limit: int | None = None
                appearance: str | None = None
                default_chart_range: str | None = None
                default_chart_metric: str | None = None
                if settings_section == "web":
                    try:
                        web_port = int(form.get("web_port", ["80"])[0])
                    except ValueError:
                        configured_devices = load_device_registry(config.device_registry_path)
                        self._send_html(
                            render_management_html(
                                snapshot=snapshot,
                                config=config,
                                storage_summary=fetch_storage_summary(current_database_path),
                                devices=[device.to_dict() for device in configured_devices],
                                config_text=read_text(config_path),
                                devices_text=read_text(config.device_registry_path),
                                contract=build_contract(config, configured_devices),
                                message="Validation failed: web port must be numeric",
                                theme_preference=config.web.appearance,
                            ),
                            status=400,
                        )
                        return
                    web_enabled = _bool_from_form(form, "web_enabled")
                    web_host = form.get("web_host", ["0.0.0.0"])[0]
                elif settings_section == "display":
                    show_chart_markers = _bool_from_form(form, "show_chart_markers")
                    try:
                        visible_device_limit = int(form.get("visible_device_limit", ["4"])[0])
                    except ValueError:
                        configured_devices = load_device_registry(config.device_registry_path)
                        self._send_html(
                            render_management_html(
                                snapshot=snapshot,
                                config=config,
                                storage_summary=fetch_storage_summary(current_database_path),
                                devices=[device.to_dict() for device in configured_devices],
                                config_text=read_text(config_path),
                                devices_text=read_text(config.device_registry_path),
                                contract=build_contract(config, configured_devices),
                                message="Validation failed: visible device limit must be numeric",
                                theme_preference=config.web.appearance,
                            ),
                            status=400,
                        )
                        return
                    appearance = form.get("appearance", [config.web.appearance])[0]
                    default_chart_range = form.get(
                        "default_chart_range", [config.web.default_chart_range]
                    )[0]
                    default_chart_metric = form.get(
                        "default_chart_metric", [config.web.default_chart_metric]
                    )[0]
                else:
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_management_html(
                            snapshot=snapshot,
                            config=config,
                            storage_summary=fetch_storage_summary(current_database_path),
                            devices=[device.to_dict() for device in configured_devices],
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: unknown settings section",
                            theme_preference=config.web.appearance,
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
                    appearance=appearance,
                    default_chart_range=default_chart_range,
                    default_chart_metric=default_chart_metric,
                )
                if errors:
                    configured_devices = load_device_registry(config.device_registry_path)
                    self._send_html(
                        render_management_html(
                            snapshot=snapshot,
                            config=config,
                            storage_summary=fetch_storage_summary(current_database_path),
                            devices=[device.to_dict() for device in configured_devices],
                            config_text=read_text(config_path),
                            devices_text=read_text(config.device_registry_path),
                            contract=build_contract(config, configured_devices),
                            message="Validation failed: " + "; ".join(errors),
                            theme_preference=config.web.appearance,
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
                self.send_header("Location", "/settings?" + urlencode({"message": message}))
                self.end_headers()
                return

            if parsed.path == "/actions/republish-discovery":
                completed = run_once_via_cli(
                    config_path,
                    state_dir=state_dir,
                    publish_discovery=True,
                )
                message = (
                    "Home Assistant discovery republished"
                    if completed.returncode == 0
                    else "Home Assistant discovery republish failed"
                )
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header("Location", "/settings?" + urlencode({"message": message}))
                self.end_headers()
                return

            if parsed.path == "/actions/restart-runtime":
                completed = restart_system_service("bm-gateway.service")
                message = (
                    "bm-gateway service restarted"
                    if completed.returncode == 0
                    else "Failed to restart bm-gateway service"
                )
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header("Location", "/settings?" + urlencode({"message": message}))
                self.end_headers()
                return

            if parsed.path == "/actions/restart-bluetooth-service":
                completed = restart_system_service("bluetooth.service")
                message = (
                    "Bluetooth service restarted"
                    if completed.returncode == 0
                    else "Failed to restart Bluetooth service"
                )
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header("Location", "/settings?" + urlencode({"message": message}))
                self.end_headers()
                return

            if parsed.path == "/actions/reboot-host":
                schedule_host_reboot()
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/rebooting",
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
                    "/settings?" + urlencode({"message": "Bluetooth adapter recovery triggered"}),
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
                    "/settings?" + urlencode({"message": "History pruned"}),
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
