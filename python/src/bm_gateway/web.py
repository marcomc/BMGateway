"""Web service entrypoints for BMGateway."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .config import AppConfig, load_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import default_color_key, load_device_registry
from .localization import resolve_locale_preference, translation_for
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
from .usb_otg_export import mark_usb_otg_exported, update_usb_otg_drive
from .web_actions import (
    _config_and_registry_texts,
    _gateway_snapshot_from_mapping,
    add_device_from_form,
    build_run_once_command,
    export_usb_otg_images_now,
    prepare_usb_otg_boot_mode,
    refresh_usb_otg_drive,
    restart_system_service,
    restore_usb_otg_boot_mode,
    run_once_via_cli,
    schedule_host_reboot,
    schedule_host_shutdown,
    start_run_once_via_cli,
    update_bluetooth_preferences,
    update_config_from_text,
    update_device_from_form,
    update_device_icon,
    update_gateway_preferences,
    update_home_assistant_preferences,
    update_mqtt_preferences,
    update_usb_otg_preferences,
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
    render_diagnostics_html,
    render_edit_device_html,
    render_frame_battery_overview_html,
    render_frame_fleet_trend_html,
    render_history_html,
    render_home_html,
    render_management_html,
    render_reboot_pending_html,
    render_settings_html,
    render_shutdown_pending_html,
    render_snapshot_html,
    render_usb_otg_export_pending_html,
)
from .web_pages_frame import frame_battery_overview_page_count
from .web_support import read_text

__all__ = [
    "add_device_from_form",
    "build_run_once_command",
    "export_usb_otg_images_now",
    "render_add_device_html",
    "render_diagnostics_html",
    "render_home_html",
    "render_device_html",
    "render_devices_html",
    "render_edit_device_html",
    "render_frame_battery_overview_html",
    "render_frame_fleet_trend_html",
    "render_history_html",
    "render_management_html",
    "render_reboot_pending_html",
    "render_settings_html",
    "render_shutdown_pending_html",
    "render_usb_otg_export_pending_html",
    "render_snapshot_html",
    "serve_management",
    "serve_snapshot",
    "prepare_usb_otg_boot_mode",
    "refresh_usb_otg_drive",
    "restore_usb_otg_boot_mode",
    "start_run_once_via_cli",
    "update_bluetooth_preferences",
    "update_config_from_text",
    "update_device_from_form",
    "update_device_icon",
    "update_gateway_preferences",
    "update_home_assistant_preferences",
    "update_mqtt_preferences",
    "update_usb_otg_preferences",
    "update_web_preferences",
    "_add_device_form_html",
    "_battery_form_script",
    "_chart_points",
    "_discover_bluetooth_adapters",
]

_USB_OTG_EXPORT_LOCK = threading.Lock()
_USB_OTG_EXPORT_STATUS: dict[str, object] = {
    "status": "idle",
    "completed": 0,
    "total": 0,
    "message": "Preparing USB OTG frame image export",
    "detail": "",
    "redirect_message": "",
}


def _set_usb_otg_export_status(**updates: object) -> None:
    with _USB_OTG_EXPORT_LOCK:
        _USB_OTG_EXPORT_STATUS.update(updates)


def _usb_otg_export_status_snapshot() -> dict[str, object]:
    with _USB_OTG_EXPORT_LOCK:
        snapshot = dict(_USB_OTG_EXPORT_STATUS)
    completed = _int_from_mapping(snapshot, "completed")
    total = _int_from_mapping(snapshot, "total")
    snapshot["percent"] = 0 if total <= 0 else round((completed / total) * 100, 1)
    return snapshot


def _int_from_mapping(mapping: dict[str, object], key: str, default: int = 0) -> int:
    value = mapping.get(key, default)
    if not isinstance(value, str | int | float):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _start_tracked_usb_otg_image_export(
    *,
    config_path: Path,
    state_dir: Path | None = None,
) -> threading.Thread | None:
    with _USB_OTG_EXPORT_LOCK:
        if _USB_OTG_EXPORT_STATUS.get("status") == "running":
            return None
        _USB_OTG_EXPORT_STATUS.update(
            {
                "status": "running",
                "completed": 0,
                "total": 0,
                "message": "Preparing USB OTG frame image export",
                "detail": "",
                "redirect_message": "",
            }
        )

    def _progress(completed: int, total: int, message: str) -> None:
        _set_usb_otg_export_status(
            status="running",
            completed=completed,
            total=total,
            message=message,
        )

    def _worker() -> None:
        try:
            config = load_config(config_path)
            devices = load_device_registry(config.device_registry_path)
            snapshot_path = state_file_path(config, state_dir=state_dir)
            empty_snapshot: dict[str, object] = {"generated_at": "", "devices": []}
            snapshot_mapping = (
                load_snapshot(snapshot_path) if snapshot_path.exists() else empty_snapshot
            )
            result = update_usb_otg_drive(
                config=config,
                devices=devices,
                snapshot=_gateway_snapshot_from_mapping(snapshot_mapping),
                database_path=database_file_path(config, state_dir=state_dir),
                progress=_progress,
                force=True,
            )
            if result.exported:
                mark_usb_otg_exported(config=config, state_dir=state_dir)
                _set_usb_otg_export_status(
                    status="completed",
                    message="USB OTG frame images exported",
                    detail="",
                    redirect_message="USB OTG frame images exported",
                )
            else:
                _set_usb_otg_export_status(
                    status="failed",
                    message="USB OTG frame image export failed",
                    detail=result.reason,
                    redirect_message=f"USB OTG frame image export failed: {result.reason}",
                )
        except Exception as exc:  # pragma: no cover - defensive web boundary
            detail = str(exc) or exc.__class__.__name__
            export_status = _usb_otg_export_status_snapshot()
            _set_usb_otg_export_status(
                status="failed",
                completed=_int_from_mapping(export_status, "total"),
                message="USB OTG frame image export failed",
                detail=detail,
                redirect_message=f"USB OTG frame image export failed: {detail}",
            )

    thread = threading.Thread(target=_worker, daemon=True, name="usb-otg-image-export")
    thread.start()
    return thread


def _start_usb_otg_image_export(
    *,
    config_path: Path,
    state_dir: Path | None = None,
) -> threading.Thread | None:
    with _USB_OTG_EXPORT_LOCK:
        if _USB_OTG_EXPORT_STATUS.get("status") == "running":
            return None
        _USB_OTG_EXPORT_STATUS.update(
            {
                "status": "running",
                "completed": 0,
                "total": 0,
                "message": "Preparing USB OTG frame image export",
                "detail": "",
                "redirect_message": "",
            }
        )

    def _worker() -> None:
        completed = export_usb_otg_images_now(config_path=config_path, state_dir=state_dir)
        if completed.returncode == 0:
            _set_usb_otg_export_status(
                status="completed",
                completed=1,
                total=1,
                message="USB OTG frame images exported",
                detail="",
                redirect_message="USB OTG frame images exported",
            )
            return

        detail = completed.stderr.strip() or completed.stdout.strip() or "USB OTG export failed"
        _set_usb_otg_export_status(
            status="failed",
            completed=1,
            total=1,
            message="USB OTG frame image export failed",
            detail=detail,
            redirect_message=f"USB OTG frame image export failed: {detail}",
        )

    thread = threading.Thread(
        target=_worker,
        daemon=True,
        name="usb-otg-image-export",
    )
    thread.start()
    return thread


def _usb_otg_fleet_trend_device_ids_from_form(
    form: dict[str, list[str]],
    config: AppConfig,
) -> tuple[str, ...]:
    if "fleet_trend_device_ids" not in form:
        return config.usb_otg.fleet_trend_device_ids

    selected_ids = tuple(
        device_id.strip()
        for device_id in form.get("fleet_trend_device_ids", [])
        if device_id.strip()
    )
    if config.usb_otg.fleet_trend_device_ids:
        return selected_ids

    configured_ids = {
        device.id
        for device in load_device_registry(config.device_registry_path)
        if device.id.strip()
    }
    if not configured_ids or set(selected_ids) == configured_ids:
        return ()
    return selected_ids


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

        def _request_language(self, config: AppConfig) -> str:
            return resolve_locale_preference(
                config.web.language,
                self.headers.get("Accept-Language"),
            )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            config, snapshot, database_path = self._load_current()
            request_language = self._request_language(config)
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
            if parsed.path == "/api/usb-otg-export/status":
                status = _usb_otg_export_status_snapshot()
                translation = translation_for(request_language)
                message = str(status.get("message", ""))
                redirect_message = str(status.get("redirect_message", ""))
                status["message"] = translation.gettext(message)
                if redirect_message:
                    if ": " in redirect_message:
                        prefix, detail = redirect_message.split(": ", 1)
                        status["redirect_message"] = f"{translation.gettext(prefix)}: {detail}"
                    else:
                        status["redirect_message"] = translation.gettext(redirect_message)
                self._send_json(status)
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

            if parsed.path == "/usb-otg-export/progress":
                self._send_html(
                    render_usb_otg_export_pending_html(
                        theme_preference=config.web.appearance,
                        language=request_language,
                    )
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
                    language=request_language,
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
                    language=request_language,
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
                    language=request_language,
                )
                self._send_html(html)
                return

            if parsed.path == "/rebooting":
                self._send_html(
                    render_reboot_pending_html(
                        theme_preference=config.web.appearance,
                        language=request_language,
                    )
                )
                return

            if parsed.path == "/shutting-down":
                self._send_html(
                    render_shutdown_pending_html(
                        theme_preference=config.web.appearance,
                        language=request_language,
                    )
                )
                return

            if parsed.path == "/devices/new":
                message = parse_qs(parsed.query).get("message", [""])[0]
                reserved_color_keys = {
                    str(device.get("color_key", "")).strip()
                    for device in serialized_devices
                    if str(device.get("color_key", "")).strip()
                }
                self._send_html(
                    render_add_device_html(
                        message=message,
                        theme_preference=config.web.appearance,
                        selected_color_key=default_color_key(used_colors=reserved_color_keys),
                        reserved_color_keys=reserved_color_keys,
                        language=request_language,
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
                            language=request_language,
                        ),
                        status=404,
                    )
                    return
                message = parse_qs(parsed.query).get("message", [""])[0]
                reserved_color_keys = {
                    str(item.get("color_key", "")).strip()
                    for item in serialized_devices
                    if str(item.get("id", "")) != device_id
                    and str(item.get("color_key", "")).strip()
                }
                self._send_html(
                    render_edit_device_html(
                        device=device,
                        message=message,
                        theme_preference=config.web.appearance,
                        reserved_color_keys=reserved_color_keys,
                        language=request_language,
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
                    language=request_language,
                )
                self._send_html(html)
                return

            if parsed.path in {"/diagnostics", "/debug"}:
                frame_snapshot = _snapshot_for_frame_devices(snapshot, config)
                frame_devices = _usb_otg_frame_devices(config, serialized_devices)
                self._send_html(
                    render_diagnostics_html(
                        theme_preference=config.web.appearance,
                        fleet_trend_metrics=config.usb_otg.fleet_trend_metrics,
                        battery_overview_page_count=frame_battery_overview_page_count(
                            snapshot=frame_snapshot,
                            devices=frame_devices,
                            devices_per_page=config.usb_otg.overview_devices_per_image,
                        ),
                        language=request_language,
                    )
                )
                return

            if parsed.path == "/frame/fleet-trend":
                params = parse_qs(parsed.query)
                selected_metrics = config.usb_otg.fleet_trend_metrics or ("soc",)
                requested_metric = params.get("metric", [selected_metrics[0]])[0]
                frame_metric = (
                    requested_metric
                    if requested_metric in selected_metrics
                    else selected_metrics[0]
                )
                frame_devices = _usb_otg_frame_devices(config, serialized_devices)
                battery_chart_points, battery_legend = _fleet_chart_points(
                    database_path=database_path,
                    devices=frame_devices,
                )
                self._send_html(
                    render_frame_fleet_trend_html(
                        chart_points=battery_chart_points,
                        legend=battery_legend,
                        show_chart_markers=config.web.show_chart_markers,
                        appearance=config.usb_otg.appearance,
                        default_chart_range=config.usb_otg.fleet_trend_range,
                        default_chart_metric=frame_metric,
                        width=config.usb_otg.image_width_px,
                        height=config.usb_otg.image_height_px,
                        language=request_language,
                    )
                )
                return

            if parsed.path == "/frame/battery-overview":
                params = parse_qs(parsed.query)
                try:
                    page = max(1, int(params.get("page", ["1"])[0]))
                except ValueError:
                    page = 1
                self._send_html(
                    render_frame_battery_overview_html(
                        snapshot=_snapshot_for_frame_devices(snapshot, config),
                        devices=_usb_otg_frame_devices(config, serialized_devices),
                        page=page,
                        devices_per_page=config.usb_otg.overview_devices_per_image,
                        appearance=config.usb_otg.appearance,
                        width=config.usb_otg.image_width_px,
                        height=config.usb_otg.image_height_px,
                        language=request_language,
                    )
                )
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
                    language=request_language,
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
                appearance=config.web.appearance,
                default_chart_range=config.web.default_chart_range,
                default_chart_metric=config.web.default_chart_metric,
                language=request_language,
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
                        language=self._request_language(config),
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
                            language=self._request_language(config),
                        ),
                        status=400,
                    )
                    return

                start_run_once_via_cli(config_path, state_dir=state_dir)
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/devices?" + urlencode({"message": "Device added. First poll started."}),
                )
                self.end_headers()
                return

            if parsed.path == "/devices/update":
                config = load_config(config_path)
                old_device_id = form.get("old_device_id", form.get("device_id", [""]))[0]
                submitted_device_id = form.get("device_id", [""])[0]
                normalized_submitted_device_id = submitted_device_id.strip()
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
                            language=self._request_language(config),
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
                            "device_id": normalized_submitted_device_id,
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
                        language=self._request_language(config),
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
                            language=self._request_language(config),
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
                            language=self._request_language(config),
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
                            language=self._request_language(config),
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
                            language=self._request_language(config),
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
                            language=self._request_language(config),
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
                            language=self._request_language(config),
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
                            language=self._request_language(config),
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
                appearance: str | None = None
                default_chart_range: str | None = None
                default_chart_metric: str | None = None
                language: str | None = None
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
                                language=self._request_language(config),
                            ),
                            status=400,
                        )
                        return
                    web_enabled = _bool_from_form(form, "web_enabled")
                    web_host = form.get("web_host", ["0.0.0.0"])[0]
                elif settings_section == "display":
                    show_chart_markers = _bool_from_form(form, "show_chart_markers")
                    appearance = form.get("appearance", [config.web.appearance])[0]
                    default_chart_range = form.get(
                        "default_chart_range", [config.web.default_chart_range]
                    )[0]
                    default_chart_metric = form.get(
                        "default_chart_metric", [config.web.default_chart_metric]
                    )[0]
                    language = form.get("language", [config.web.language])[0]
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
                            language=self._request_language(config),
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
                    appearance=appearance,
                    default_chart_range=default_chart_range,
                    default_chart_metric=default_chart_metric,
                    language=language,
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
                            language=self._request_language(config),
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

            if parsed.path == "/settings/usb-otg":
                config, snapshot, current_database_path = self._load_current()
                try:
                    image_width_px = int(form.get("image_width_px", ["480"])[0])
                    image_height_px = int(form.get("image_height_px", ["234"])[0])
                    refresh_interval_seconds = int(form.get("refresh_interval_seconds", ["0"])[0])
                    overview_devices_per_image = int(
                        form.get("overview_devices_per_image", ["5"])[0]
                    )
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
                            message="Validation failed: USB OTG settings values must be numeric",
                            theme_preference=config.web.appearance,
                            language=self._request_language(config),
                        ),
                        status=400,
                    )
                    return
                errors = update_usb_otg_preferences(
                    config_path=config_path,
                    enabled=_bool_from_form(form, "usb_otg_enabled"),
                    image_width_px=image_width_px,
                    image_height_px=image_height_px,
                    image_format=form.get("image_format", [config.usb_otg.image_format])[0],
                    appearance=form.get("appearance", [config.usb_otg.appearance])[0],
                    refresh_interval_seconds=refresh_interval_seconds,
                    overview_devices_per_image=overview_devices_per_image,
                    export_battery_overview=_bool_from_form(form, "export_battery_overview"),
                    export_fleet_trend=_bool_from_form(form, "export_fleet_trend"),
                    fleet_trend_metrics=(
                        tuple(form.get("fleet_trend_metrics", []))
                        if "fleet_trend_metrics" in form
                        else config.usb_otg.fleet_trend_metrics
                    ),
                    fleet_trend_range=form.get(
                        "fleet_trend_range",
                        [config.usb_otg.fleet_trend_range],
                    )[0],
                    fleet_trend_device_ids=(
                        _usb_otg_fleet_trend_device_ids_from_form(form, config)
                    ),
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
                            language=self._request_language(config),
                        ),
                        status=400,
                    )
                    return
                updated_config = load_config(config_path)
                message = "Settings saved"
                if updated_config.usb_otg.enabled and (
                    updated_config.usb_otg.export_battery_overview
                    or updated_config.usb_otg.export_fleet_trend
                ):
                    export_thread = _start_usb_otg_image_export(
                        config_path=config_path,
                        state_dir=state_dir,
                    )
                    if export_thread is not None:
                        message += "; USB OTG frame image export started"
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": message})
                )
                self.end_headers()
                return

            if parsed.path == "/actions/export-usb-otg-images":
                _start_tracked_usb_otg_image_export(
                    config_path=config_path,
                    state_dir=state_dir,
                )
                self.send_response(303)
                self.send_header("Location", "/usb-otg-export/progress")
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

            if parsed.path == "/actions/prepare-usb-otg-mode":
                completed = prepare_usb_otg_boot_mode()
                message = (
                    "USB OTG boot mode prepared; reboot required"
                    if completed.returncode == 0
                    else "Failed to prepare USB OTG boot mode"
                )
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": message})
                )
                self.end_headers()
                return

            if parsed.path == "/actions/restore-usb-host-mode":
                completed = restore_usb_otg_boot_mode()
                message = (
                    "USB host boot mode restored; reboot required"
                    if completed.returncode == 0
                    else "Failed to restore USB host boot mode"
                )
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": message})
                )
                self.end_headers()
                return

            if parsed.path == "/actions/refresh-usb-otg-drive":
                completed = refresh_usb_otg_drive(config_path)
                message = (
                    "USB OTG drive refreshed"
                    if completed.returncode == 0
                    else "Failed to refresh USB OTG drive"
                )
                if completed.stderr:
                    message += f": {completed.stderr.strip()}"
                self.send_response(303)
                self.send_header(
                    "Location", "/settings?" + urlencode({"edit": "1", "message": message})
                )
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

            if parsed.path == "/actions/shutdown-host":
                schedule_host_shutdown()
                self.send_response(303)
                self.send_header(
                    "Location",
                    "/shutting-down",
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


def _usb_otg_frame_devices(
    config: AppConfig,
    devices: list[dict[str, object]],
) -> list[dict[str, object]]:
    selected_ids = set(config.usb_otg.fleet_trend_device_ids)
    if not selected_ids:
        return devices
    return [device for device in devices if str(device.get("id", "")) in selected_ids]


def _snapshot_for_frame_devices(
    snapshot: dict[str, object],
    config: AppConfig,
) -> dict[str, object]:
    selected_ids = set(config.usb_otg.fleet_trend_device_ids)
    if not selected_ids:
        return snapshot
    snapshot_devices = snapshot.get("devices", [])
    if not isinstance(snapshot_devices, list):
        return snapshot
    filtered_devices = [
        device
        for device in snapshot_devices
        if isinstance(device, dict) and str(device.get("id", "")) in selected_ids
    ]
    filtered_snapshot = dict(snapshot)
    filtered_snapshot["devices"] = filtered_devices
    filtered_snapshot["devices_total"] = len(filtered_devices)
    filtered_snapshot["devices_online"] = sum(
        1 for device in filtered_devices if bool(device.get("connected"))
    )
    return filtered_snapshot
