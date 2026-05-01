"""State-changing actions for the BMGateway web interface."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .archive_sync import (
    sync_archive_backfill_candidates,
    sync_bm200_device_archive,
    sync_bm300_device_archive,
)
from .audit_log import append_audit_event
from .config import AppConfig, load_config, write_config
from .device_registry import (
    Device,
    default_battery_family,
    default_battery_profile,
    default_color_key,
    default_icon_key,
    device_driver_type,
    generate_device_id,
    load_device_registry,
    normalize_mac_address,
    validate_devices,
    write_device_registry,
)
from .models import DeviceReading, GatewaySnapshot
from .runtime import database_file_path, state_file_path
from .state_store import (
    history_device_id_exists,
    load_snapshot,
    rename_history_device_id,
)
from .usb_otg_export import mark_usb_otg_exported, update_usb_otg_drive
from .web_support import default_curve_pairs, read_text

BM200_FULL_HISTORY_PAGE_COUNT = 85
HistorySyncProgress = Callable[[int, int, str], None]


def _audit_manual_web_action(
    config: AppConfig,
    *,
    action: str,
    status: str,
    details: dict[str, object],
    state_dir: Path | None = None,
) -> None:
    append_audit_event(
        config=config,
        state_dir=state_dir,
        source="web",
        trigger="manual",
        action=action,
        status=status,
        details=details,
    )


def _config_and_registry_texts(config_path: Path) -> tuple[str, str]:
    config_text = read_text(config_path)
    try:
        config = load_config(config_path)
        devices_text = read_text(config.device_registry_path)
    except Exception:
        devices_text = ""
    return config_text, devices_text


def _int_from_snapshot_mapping(
    mapping: dict[str, object],
    key: str,
    default: int = 0,
) -> int:
    value = mapping.get(key, default)
    if not isinstance(value, str | int | float):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _gateway_snapshot_from_mapping(snapshot: dict[str, object]) -> GatewaySnapshot:
    readings: list[DeviceReading] = []
    snapshot_devices = snapshot.get("devices", [])
    if isinstance(snapshot_devices, list):
        for item in snapshot_devices:
            if not isinstance(item, dict):
                continue
            readings.append(
                DeviceReading(
                    id=str(item.get("id", "")),
                    type=str(item.get("type", "bm200")),
                    name=str(item.get("name") or item.get("id") or "Battery"),
                    mac=str(item.get("mac", "")),
                    enabled=bool(item.get("enabled", True)),
                    connected=bool(item.get("connected", False)),
                    voltage=float(item.get("voltage", 0.0) or 0.0),
                    soc=int(float(item.get("soc", 0) or 0)),
                    temperature=(
                        float(item["temperature"]) if item.get("temperature") is not None else None
                    ),
                    rssi=int(item["rssi"]) if item.get("rssi") is not None else None,
                    state=str(item.get("state", "unknown")),
                    error_code=(
                        str(item["error_code"]) if item.get("error_code") is not None else None
                    ),
                    error_detail=(
                        str(item["error_detail"]) if item.get("error_detail") is not None else None
                    ),
                    last_seen=str(item.get("last_seen", snapshot.get("generated_at", ""))),
                    adapter=str(item.get("adapter", "")),
                    driver=str(item.get("driver", "")),
                )
            )
    return GatewaySnapshot(
        generated_at=str(snapshot.get("generated_at", "")),
        gateway_name=str(snapshot.get("gateway_name", "BMGateway")),
        active_adapter=str(snapshot.get("active_adapter", "")),
        mqtt_enabled=bool(snapshot.get("mqtt_enabled", False)),
        mqtt_connected=bool(snapshot.get("mqtt_connected", False)),
        devices_total=_int_from_snapshot_mapping(snapshot, "devices_total", len(readings)),
        devices_online=_int_from_snapshot_mapping(snapshot, "devices_online"),
        poll_interval_seconds=_int_from_snapshot_mapping(snapshot, "poll_interval_seconds"),
        devices=readings,
    )


def update_config_from_text(*, config_path: Path, config_toml: str, devices_toml: str) -> list[str]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    current_config: AppConfig | None = None
    try:
        current_config = load_config(config_path)
    except Exception:
        current_config = None
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
            if current_config is not None:
                _audit_manual_web_action(
                    current_config,
                    action="config_text_update",
                    status="failed",
                    details={"errors": errors},
                )
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
        _audit_manual_web_action(
            load_config(config_path),
            action="config_text_update",
            status="completed",
            details={"device_count": len(devices)},
        )
        return []


def add_device_from_form(
    *,
    config_path: Path,
    device_id: str | None = None,
    device_type: str,
    device_name: str,
    device_mac: str,
    battery_family: str | None = None,
    battery_profile: str | None = None,
    custom_soc_mode: str = "intelligent_algorithm",
    custom_voltage_curve: tuple[tuple[int, float], ...] | None = None,
    icon_key: str | None = None,
    color_key: str | None = None,
    installed_in_vehicle: bool = False,
    vehicle_type: str = "",
    battery_brand: str = "",
    battery_model: str = "",
    battery_nominal_voltage: int | None = None,
    battery_capacity_ah: float | None = None,
    battery_production_year: int | None = None,
) -> list[str]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    resolved_device_id = device_id.strip() if device_id else ""
    if not resolved_device_id:
        resolved_device_id = generate_device_id(
            device_name=device_name,
            device_type=device_type,
            existing_ids={device.id for device in devices},
        )
    resolved_family = battery_family or default_battery_family(device_type.strip())
    resolved_profile = battery_profile or default_battery_profile(
        device_type.strip(),
        resolved_family,
    )
    devices.append(
        Device(
            id=resolved_device_id,
            type=device_type.strip(),
            name=device_name.strip(),
            mac=normalize_mac_address(device_mac),
            enabled=True,
            battery_family=resolved_family.strip(),
            battery_profile=resolved_profile.strip(),
            custom_soc_mode=custom_soc_mode.strip(),
            custom_voltage_curve=custom_voltage_curve or tuple(default_curve_pairs()),
            icon_key=(
                icon_key
                or default_icon_key(
                    battery_family=resolved_family.strip(),
                    battery_profile=resolved_profile.strip(),
                )
            ).strip(),
            color_key=(
                color_key or default_color_key(used_colors={device.color_key for device in devices})
            ).strip(),
            installed_in_vehicle=installed_in_vehicle,
            vehicle_type=vehicle_type.strip() if installed_in_vehicle else "",
            battery_brand=battery_brand.strip(),
            battery_model=battery_model.strip(),
            battery_nominal_voltage=battery_nominal_voltage,
            battery_capacity_ah=battery_capacity_ah,
            battery_production_year=battery_production_year,
        )
    )
    errors = validate_devices(devices)
    if errors:
        _audit_manual_web_action(
            config,
            action="device_add",
            status="failed",
            details={"device_id": resolved_device_id, "errors": errors},
        )
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
    _audit_manual_web_action(
        config,
        action="device_add",
        status="completed",
        details={"device_id": resolved_device_id, "device_type": device_type.strip()},
    )
    return []


def update_device_from_form(
    *,
    config_path: Path,
    database_path: Path | None = None,
    device_id: str,
    new_device_id: str | None = None,
    device_type: str,
    device_name: str,
    device_mac: str,
    battery_family: str,
    battery_profile: str,
    custom_soc_mode: str,
    custom_voltage_curve: tuple[tuple[int, float], ...],
    icon_key: str | None = None,
    color_key: str,
    installed_in_vehicle: bool,
    vehicle_type: str,
    battery_brand: str,
    battery_model: str,
    battery_nominal_voltage: int | None,
    battery_capacity_ah: float | None,
    battery_production_year: int | None,
) -> list[str]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    resolved_device_id = device_id.strip()
    resolved_new_device_id = (
        new_device_id.strip() if new_device_id is not None else resolved_device_id
    )
    resolved_device_type = device_type.strip()
    resolved_device_name = device_name.strip()
    resolved_device_mac = normalize_mac_address(device_mac)
    updated_devices: list[Device] = []
    original_device: Device | None = None
    for device in devices:
        if device.id == resolved_device_id:
            original_device = device
            updated_devices.append(
                replace(
                    device,
                    id=resolved_new_device_id,
                    type=resolved_device_type,
                    name=resolved_device_name,
                    mac=resolved_device_mac,
                    battery_family=battery_family.strip(),
                    battery_profile=battery_profile.strip(),
                    custom_soc_mode=custom_soc_mode.strip(),
                    custom_voltage_curve=custom_voltage_curve,
                    icon_key=(
                        icon_key.strip()
                        if icon_key and icon_key.strip()
                        else default_icon_key(
                            battery_family=battery_family.strip(),
                            battery_profile=battery_profile.strip(),
                        )
                    ),
                    color_key=color_key.strip(),
                    installed_in_vehicle=installed_in_vehicle,
                    vehicle_type=vehicle_type.strip() if installed_in_vehicle else "",
                    battery_brand=battery_brand.strip(),
                    battery_model=battery_model.strip(),
                    battery_nominal_voltage=battery_nominal_voltage,
                    battery_capacity_ah=battery_capacity_ah,
                    battery_production_year=battery_production_year,
                )
            )
        else:
            updated_devices.append(device)
    if original_device is None:
        _audit_manual_web_action(
            config,
            action="device_update",
            status="failed",
            details={
                "device_id": resolved_device_id,
                "errors": [f"device {resolved_device_id} was not found"],
            },
        )
        return [f"device {resolved_device_id} was not found"]
    errors = validate_devices(updated_devices)
    if errors:
        _audit_manual_web_action(
            config,
            action="device_update",
            status="failed",
            details={"device_id": resolved_device_id, "errors": errors},
        )
        return errors
    if (
        database_path is not None
        and resolved_new_device_id != resolved_device_id
        and history_device_id_exists(database_path, resolved_new_device_id)
    ):
        _audit_manual_web_action(
            config,
            action="device_update",
            status="failed",
            details={
                "device_id": resolved_device_id,
                "errors": [
                    "device id "
                    f"{resolved_new_device_id} already has stored history; choose a different id"
                ],
            },
        )
        return [
            f"device id {resolved_new_device_id} already has stored history; choose a different id"
        ]
    history_identity_changed = (
        resolved_new_device_id != resolved_device_id
        or resolved_device_type != original_device.type
        or resolved_device_name != original_device.name
        or resolved_device_mac != normalize_mac_address(original_device.mac)
    )
    if database_path is not None and history_identity_changed:
        rename_history_device_id(
            database_path,
            old_device_id=resolved_device_id,
            new_device_id=resolved_new_device_id,
            device_type=resolved_device_type,
            name=resolved_device_name,
            mac=resolved_device_mac,
        )
    write_device_registry(config.device_registry_path, updated_devices)
    _audit_manual_web_action(
        config,
        action="device_update",
        status="completed",
        details={
            "device_id": resolved_device_id,
            "new_device_id": resolved_new_device_id,
            "device_type": resolved_device_type,
        },
        state_dir=database_path.parent.parent if database_path is not None else None,
    )
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
        color_key=target.color_key,
        installed_in_vehicle=target.installed_in_vehicle,
        vehicle_type=target.vehicle_type,
        battery_brand=target.battery_brand,
        battery_model=target.battery_model,
        battery_nominal_voltage=target.battery_nominal_voltage,
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
    appearance: str | None,
    default_chart_range: str | None,
    default_chart_metric: str | None,
    language: str | None = None,
) -> list[str]:
    config = load_config(config_path)
    resolved_enabled = config.web.enabled if web_enabled is None else web_enabled
    resolved_host = config.web.host if web_host is None else web_host
    resolved_port = config.web.port if web_port is None else web_port
    resolved_show_chart_markers = (
        config.web.show_chart_markers if show_chart_markers is None else show_chart_markers
    )
    resolved_appearance = config.web.appearance if appearance is None else appearance
    resolved_default_chart_range = (
        config.web.default_chart_range if default_chart_range is None else default_chart_range
    )
    resolved_default_chart_metric = (
        config.web.default_chart_metric if default_chart_metric is None else default_chart_metric
    )
    resolved_language = config.web.language if language is None else language
    updated = replace(
        config,
        web=replace(
            config.web,
            enabled=resolved_enabled,
            host=resolved_host,
            port=resolved_port,
            show_chart_markers=resolved_show_chart_markers,
            appearance=resolved_appearance,
            default_chart_range=resolved_default_chart_range,
            default_chart_metric=resolved_default_chart_metric,
            language=resolved_language,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        _audit_manual_web_action(
            config,
            action="web_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="web_preferences_update",
        status="completed",
        details={"host": resolved_host, "port": resolved_port, "enabled": resolved_enabled},
    )
    return []


def update_usb_otg_preferences(
    *,
    config_path: Path,
    enabled: bool,
    image_width_px: int | None = None,
    image_height_px: int | None = None,
    image_format: str | None = None,
    appearance: str | None = None,
    refresh_interval_seconds: int | None = None,
    overview_devices_per_image: int | None = None,
    export_battery_overview: bool | None = None,
    export_fleet_trend: bool | None = None,
    fleet_trend_metrics: tuple[str, ...] | None = None,
    fleet_trend_range: str | None = None,
    fleet_trend_device_ids: tuple[str, ...] | None = None,
) -> list[str]:
    config = load_config(config_path)
    updated = replace(
        config,
        usb_otg=replace(
            config.usb_otg,
            enabled=enabled,
            image_width_px=(
                config.usb_otg.image_width_px if image_width_px is None else image_width_px
            ),
            image_height_px=(
                config.usb_otg.image_height_px if image_height_px is None else image_height_px
            ),
            image_format=config.usb_otg.image_format if image_format is None else image_format,
            appearance=config.usb_otg.appearance if appearance is None else appearance,
            refresh_interval_seconds=(
                config.usb_otg.refresh_interval_seconds
                if refresh_interval_seconds is None
                else refresh_interval_seconds
            ),
            overview_devices_per_image=(
                config.usb_otg.overview_devices_per_image
                if overview_devices_per_image is None
                else overview_devices_per_image
            ),
            export_battery_overview=(
                config.usb_otg.export_battery_overview
                if export_battery_overview is None
                else export_battery_overview
            ),
            export_fleet_trend=(
                config.usb_otg.export_fleet_trend
                if export_fleet_trend is None
                else export_fleet_trend
            ),
            fleet_trend_metrics=(
                config.usb_otg.fleet_trend_metrics
                if fleet_trend_metrics is None
                else fleet_trend_metrics
            ),
            fleet_trend_range=(
                config.usb_otg.fleet_trend_range if fleet_trend_range is None else fleet_trend_range
            ),
            fleet_trend_device_ids=(
                config.usb_otg.fleet_trend_device_ids
                if fleet_trend_device_ids is None
                else fleet_trend_device_ids
            ),
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        _audit_manual_web_action(
            config,
            action="usb_otg_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="usb_otg_preferences_update",
        status="completed",
        details={"enabled": enabled},
    )
    return []


def update_archive_sync_preferences(
    *,
    config_path: Path,
    enabled: bool,
    periodic_interval_seconds: int,
    reconnect_min_gap_seconds: int,
    safety_margin_seconds: int,
    bm200_max_pages_per_sync: int,
    bm300_enabled: bool,
    bm300_max_pages_per_sync: int,
) -> list[str]:
    config = load_config(config_path)
    updated = replace(
        config,
        archive_sync=replace(
            config.archive_sync,
            enabled=enabled,
            periodic_interval_seconds=periodic_interval_seconds,
            reconnect_min_gap_seconds=reconnect_min_gap_seconds,
            safety_margin_seconds=safety_margin_seconds,
            bm200_max_pages_per_sync=bm200_max_pages_per_sync,
            bm300_enabled=bm300_enabled,
            bm300_max_pages_per_sync=bm300_max_pages_per_sync,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        _audit_manual_web_action(
            config,
            action="archive_sync_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="archive_sync_preferences_update",
        status="completed",
        details={
            "enabled": enabled,
            "bm200_max_pages_per_sync": bm200_max_pages_per_sync,
            "bm300_enabled": bm300_enabled,
            "bm300_max_pages_per_sync": bm300_max_pages_per_sync,
        },
    )
    return []


def update_gateway_preferences(
    *,
    config_path: Path,
    gateway_name: str,
    timezone: str,
    reader_mode: str,
    poll_interval_seconds: int,
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
        retention=replace(
            config.retention,
            raw_retention_days=raw_retention_days,
            daily_retention_days=daily_retention_days,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        _audit_manual_web_action(
            config,
            action="gateway_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="gateway_preferences_update",
        status="completed",
        details={
            "gateway_name": gateway_name,
            "reader_mode": reader_mode,
            "poll_interval_seconds": poll_interval_seconds,
        },
    )
    return []


def update_mqtt_preferences(
    *,
    config_path: Path,
    mqtt_enabled: bool,
    mqtt_host: str,
    mqtt_port: int,
    mqtt_username: str,
    mqtt_password: str,
    mqtt_base_topic: str,
    mqtt_discovery_prefix: str,
    mqtt_retain_discovery: bool,
    mqtt_retain_state: bool,
) -> list[str]:
    config = load_config(config_path)
    updated = replace(
        config,
        mqtt=replace(
            config.mqtt,
            enabled=mqtt_enabled,
            host=mqtt_host,
            port=mqtt_port,
            username=mqtt_username,
            password=mqtt_password,
            base_topic=mqtt_base_topic,
            discovery_prefix=mqtt_discovery_prefix,
            retain_discovery=mqtt_retain_discovery,
            retain_state=mqtt_retain_state,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        _audit_manual_web_action(
            config,
            action="mqtt_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="mqtt_preferences_update",
        status="completed",
        details={"enabled": mqtt_enabled, "host": mqtt_host, "port": mqtt_port},
    )
    return []


def update_home_assistant_preferences(
    *,
    config_path: Path,
    home_assistant_enabled: bool,
    home_assistant_status_topic: str,
    home_assistant_gateway_device_id: str,
) -> list[str]:
    config = load_config(config_path)
    updated = replace(
        config,
        home_assistant=replace(
            config.home_assistant,
            enabled=home_assistant_enabled,
            status_topic=home_assistant_status_topic,
            gateway_device_id=home_assistant_gateway_device_id,
        ),
    )
    from .config import validate_config

    errors = validate_config(updated)
    if errors:
        _audit_manual_web_action(
            config,
            action="home_assistant_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="home_assistant_preferences_update",
        status="completed",
        details={"enabled": home_assistant_enabled},
    )
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
        _audit_manual_web_action(
            config,
            action="bluetooth_preferences_update",
            status="failed",
            details={"errors": errors},
        )
        return errors
    write_config(config_path, updated)
    _audit_manual_web_action(
        updated,
        action="bluetooth_preferences_update",
        status="completed",
        details={
            "adapter": adapter,
            "scan_timeout_seconds": scan_timeout_seconds,
            "connect_timeout_seconds": connect_timeout_seconds,
        },
    )
    return []


def build_run_once_command(
    config_path: Path,
    *,
    state_dir: Path | None = None,
    publish_discovery: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "bm_gateway",
        "--config",
        str(config_path),
        "run",
        "--once",
    ]
    if publish_discovery:
        command.append("--publish-discovery")
    if state_dir is not None:
        command.extend(["--state-dir", str(state_dir)])
    return command


def run_once_via_cli(
    config_path: Path,
    *,
    state_dir: Path | None = None,
    publish_discovery: bool = False,
) -> subprocess.CompletedProcess[str]:
    config = load_config(config_path)
    completed = subprocess.run(
        build_run_once_command(
            config_path,
            state_dir=state_dir,
            publish_discovery=publish_discovery,
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    _audit_manual_web_action(
        config,
        action="run_once_via_cli",
        status="completed" if completed.returncode == 0 else "failed",
        details={"publish_discovery": publish_discovery, "returncode": completed.returncode},
        state_dir=state_dir,
    )
    return completed


def sync_history_now(
    *,
    config_path: Path,
    state_dir: Path | None = None,
) -> dict[str, object]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    device_pages = {
        device.id: (
            config.archive_sync.bm300_max_pages_per_sync
            if device_driver_type(device.type) == "bm300pro"
            else config.archive_sync.bm200_max_pages_per_sync
        )
        for device in devices
        if device.enabled
        and (
            device_driver_type(device.type) == "bm200"
            or (device_driver_type(device.type) == "bm300pro" and config.archive_sync.bm300_enabled)
        )
    }
    results = sync_archive_backfill_candidates(
        config=config,
        devices=devices,
        database_path=database_file_path(config, state_dir=state_dir),
        device_pages=device_pages,
        source="web",
        trigger="manual",
    )
    errors = [result for result in results if result.get("synced") is not True]
    payload = {
        "requested": len(device_pages),
        "synced": sum(1 for result in results if result.get("synced") is True),
        "fetched": _sum_result_int(results, "fetched"),
        "inserted": _sum_result_int(results, "inserted"),
        "errors": errors,
        "results": results,
    }
    append_audit_event(
        config=config,
        state_dir=state_dir,
        source="web",
        trigger="manual",
        action="history_sync_batch_completed",
        status="completed" if not errors else "failed",
        details={
            "requested": payload["requested"],
            "synced": payload["synced"],
            "fetched": payload["fetched"],
            "inserted": payload["inserted"],
            "error_count": len(errors),
            "device_pages": device_pages,
        },
    )
    return payload


def sync_device_history_now(
    *,
    config_path: Path,
    device_id: str,
    state_dir: Path | None = None,
    progress: HistorySyncProgress | None = None,
) -> dict[str, object]:
    config = load_config(config_path)
    devices = load_device_registry(config.device_registry_path)
    device = next((item for item in devices if item.id == device_id), None)
    if device is None:
        _audit_manual_web_action(
            config,
            action="history_sync_device_completed",
            status="failed",
            details={"device_id": device_id, "error": f"Unknown device: {device_id}"},
            state_dir=state_dir,
        )
        raise ValueError(f"Unknown device: {device_id}")
    if not device.enabled:
        _audit_manual_web_action(
            config,
            action="history_sync_device_completed",
            status="failed",
            details={"device_id": device_id, "error": f"Device is disabled: {device_id}"},
            state_dir=state_dir,
        )
        raise ValueError(f"Device is disabled: {device_id}")

    driver_type = device_driver_type(device.type)
    database_path = database_file_path(config, state_dir=state_dir)
    try:
        if driver_type == "bm200":
            payload = sync_bm200_device_archive(
                config=config,
                device=device,
                database_path=database_path,
                page_count=BM200_FULL_HISTORY_PAGE_COUNT,
                progress=progress,
            )
        elif driver_type == "bm300pro":
            if not config.archive_sync.bm300_enabled:
                raise ValueError("BM300 archive sync is disabled in settings.")
            payload = sync_bm300_device_archive(
                config=config,
                device=device,
                database_path=database_path,
                page_count=max(1, config.archive_sync.bm300_max_pages_per_sync),
                progress=progress,
            )
        else:
            raise ValueError(f"History sync is not implemented for device type: {device.type}")
    except Exception as exc:
        _audit_manual_web_action(
            config,
            action="history_sync_device_completed",
            status="failed",
            details={"device_id": device_id, "error": str(exc) or exc.__class__.__name__},
            state_dir=state_dir,
        )
        raise

    payload["requested"] = 1
    payload["synced"] = True
    append_audit_event(
        config=config,
        state_dir=state_dir,
        source="web",
        trigger="manual",
        action="history_sync_device_completed",
        status="completed",
        details={
            "device_id": device.id,
            "device_type": device.type,
            "fetched": payload.get("fetched", 0),
            "inserted": payload.get("inserted", 0),
            "page_count": payload.get("page_count", 0),
            "profile": payload.get("profile", ""),
        },
    )
    return payload


def _sum_result_int(results: list[dict[str, object]], key: str) -> int:
    total = 0
    for result in results:
        value = result.get(key, 0)
        if isinstance(value, str | int | float):
            try:
                total += int(value)
            except ValueError:
                continue
    return total


def start_run_once_via_cli(
    config_path: Path,
    *,
    state_dir: Path | None = None,
    publish_discovery: bool = False,
) -> subprocess.Popen[str]:
    config = load_config(config_path)
    process = subprocess.Popen(
        build_run_once_command(
            config_path,
            state_dir=state_dir,
            publish_discovery=publish_discovery,
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    _audit_manual_web_action(
        config,
        action="run_once_via_cli_started",
        status="completed",
        details={"publish_discovery": publish_discovery, "pid": process.pid},
        state_dir=state_dir,
    )
    return process


def _privileged_systemctl_command(*args: str) -> list[str]:
    return ["sudo", "-n", "systemctl", *args]


def restart_system_service(service_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _privileged_systemctl_command("restart", service_name),
        check=False,
        capture_output=True,
        text=True,
    )


def _usb_otg_boot_mode_command(action: str) -> list[str]:
    return ["sudo", "-n", "/usr/local/bin/bm-gateway-usb-otg-boot-mode", action]


def _usb_otg_drive_helper_command(config_path: Path, action: str) -> list[str]:
    config = load_config(config_path)
    return [
        "sudo",
        "-n",
        "/usr/local/bin/bm-gateway-usb-otg-frame-test",
        action,
        "--image-path",
        config.usb_otg.image_path,
        "--gadget-name",
        config.usb_otg.gadget_name,
    ]


def prepare_usb_otg_boot_mode() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _usb_otg_boot_mode_command("prepare"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def restore_usb_otg_boot_mode() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _usb_otg_boot_mode_command("restore"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def refresh_usb_otg_drive(config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _usb_otg_drive_helper_command(config_path, "refresh"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def export_usb_otg_images_now(
    *,
    config_path: Path,
    state_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["export-usb-otg-images"]
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
            force=True,
        )
        if result.exported:
            mark_usb_otg_exported(config=config, state_dir=state_dir)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", result.reason)
    except Exception as exc:  # pragma: no cover - defensive web action boundary
        detail = str(exc) or exc.__class__.__name__
        return subprocess.CompletedProcess(command, 1, "", detail)


def schedule_host_reboot() -> None:
    subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-lc", "sleep 1 && sudo -n systemctl reboot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def schedule_host_shutdown() -> None:
    subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-lc", "sleep 1 && sudo -n systemctl poweroff"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
