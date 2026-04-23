"""State-changing actions for the BMGateway web interface."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from .config import load_config, write_config
from .device_registry import (
    Device,
    default_battery_family,
    default_battery_profile,
    default_color_key,
    default_icon_key,
    generate_device_id,
    load_device_registry,
    normalize_mac_address,
    validate_devices,
    write_device_registry,
)
from .state_store import history_device_id_exists, rename_history_device_id
from .web_support import default_curve_pairs, read_text


def _config_and_registry_texts(config_path: Path) -> tuple[str, str]:
    config_text = read_text(config_path)
    try:
        config = load_config(config_path)
        devices_text = read_text(config.device_registry_path)
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
    updated_devices: list[Device] = []
    found = False
    for device in devices:
        if device.id == resolved_device_id:
            updated_devices.append(
                replace(
                    device,
                    id=resolved_new_device_id,
                    type=device_type.strip(),
                    name=device_name.strip(),
                    mac=normalize_mac_address(device_mac),
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
            found = True
        else:
            updated_devices.append(device)
    if not found:
        return [f"device {resolved_device_id} was not found"]
    errors = validate_devices(updated_devices)
    if errors:
        return errors
    if (
        database_path is not None
        and resolved_new_device_id != resolved_device_id
        and history_device_id_exists(database_path, resolved_new_device_id)
    ):
        return [
            f"device id {resolved_new_device_id} already has stored history; choose a different id"
        ]
    if database_path is not None:
        rename_history_device_id(
            database_path,
            old_device_id=resolved_device_id,
            new_device_id=resolved_new_device_id,
            device_type=device_type.strip(),
            name=device_name.strip(),
            mac=normalize_mac_address(device_mac),
        )
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
    visible_device_limit: int | None,
    appearance: str | None,
    default_chart_range: str | None,
    default_chart_metric: str | None,
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
    resolved_appearance = config.web.appearance if appearance is None else appearance
    resolved_default_chart_range = (
        config.web.default_chart_range if default_chart_range is None else default_chart_range
    )
    resolved_default_chart_metric = (
        config.web.default_chart_metric if default_chart_metric is None else default_chart_metric
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
            appearance=resolved_appearance,
            default_chart_range=resolved_default_chart_range,
            default_chart_metric=resolved_default_chart_metric,
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
        return errors
    write_config(config_path, updated)
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
        return errors
    write_config(config_path, updated)
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
    return subprocess.run(
        build_run_once_command(
            config_path,
            state_dir=state_dir,
            publish_discovery=publish_discovery,
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def _privileged_systemctl_command(*args: str) -> list[str]:
    return ["sudo", "-n", "systemctl", *args]


def restart_system_service(service_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _privileged_systemctl_command("restart", service_name),
        check=False,
        capture_output=True,
        text=True,
    )


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
