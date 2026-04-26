"""Configuration support for BMGateway."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .localization import allowed_language_codes, is_supported_language_preference

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "bm-gateway" / "config.toml"


@dataclass(frozen=True)
class GatewayConfig:
    name: str = "BMGateway"
    timezone: str = "Europe/Rome"
    poll_interval_seconds: int = 300
    device_registry: str = "devices.toml"
    data_dir: str = "data"
    reader_mode: str = "fake"


@dataclass(frozen=True)
class BluetoothConfig:
    adapter: str = "auto"
    scan_timeout_seconds: int = 15
    connect_timeout_seconds: int = 45


@dataclass(frozen=True)
class MQTTConfig:
    enabled: bool = True
    host: str = "mqtt.local"
    port: int = 1883
    username: str = "mqtt-user"
    password: str = "CHANGE_ME"
    base_topic: str = "bm_gateway"
    discovery_prefix: str = "homeassistant"
    retain_discovery: bool = True
    retain_state: bool = False


@dataclass(frozen=True)
class HomeAssistantConfig:
    enabled: bool = True
    status_topic: str = "homeassistant/status"
    gateway_device_id: str = "bm_gateway"


@dataclass(frozen=True)
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 80
    show_chart_markers: bool = False
    appearance: str = "system"
    default_chart_range: str = "7"
    default_chart_metric: str = "soc"
    language: str = "auto"


@dataclass(frozen=True)
class USBOTGConfig:
    enabled: bool = False
    image_path: str = "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img"
    size_mb: int = 64
    gadget_name: str = "bmgw_frame"
    image_width_px: int = 480
    image_height_px: int = 234
    image_format: str = "jpeg"
    appearance: str = "light"
    refresh_interval_seconds: int = 0
    overview_devices_per_image: int = 3
    export_battery_overview: bool = True
    export_fleet_trend: bool = True
    fleet_trend_metrics: tuple[str, ...] = ("soc",)
    fleet_trend_range: str = "7"
    fleet_trend_device_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetentionConfig:
    raw_retention_days: int = 180
    daily_retention_days: int = 0


@dataclass(frozen=True)
class AppConfig:
    source_path: Path
    device_registry_path: Path
    gateway: GatewayConfig
    bluetooth: BluetoothConfig
    mqtt: MQTTConfig
    home_assistant: HomeAssistantConfig
    web: WebConfig
    retention: RetentionConfig
    usb_otg: USBOTGConfig = field(default_factory=USBOTGConfig)
    verbose: bool = False

    def with_cli_overrides(self, *, verbose: bool) -> "AppConfig":
        if not verbose:
            return self
        return AppConfig(
            source_path=self.source_path,
            device_registry_path=self.device_registry_path,
            gateway=self.gateway,
            bluetooth=self.bluetooth,
            mqtt=self.mqtt,
            home_assistant=self.home_assistant,
            web=self.web,
            retention=self.retention,
            usb_otg=self.usb_otg,
            verbose=True,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": str(self.source_path),
            "device_registry_path": str(self.device_registry_path),
            "gateway": {
                "name": self.gateway.name,
                "timezone": self.gateway.timezone,
                "poll_interval_seconds": self.gateway.poll_interval_seconds,
                "device_registry": self.gateway.device_registry,
                "data_dir": self.gateway.data_dir,
                "reader_mode": self.gateway.reader_mode,
            },
            "bluetooth": {
                "adapter": self.bluetooth.adapter,
                "scan_timeout_seconds": self.bluetooth.scan_timeout_seconds,
                "connect_timeout_seconds": self.bluetooth.connect_timeout_seconds,
            },
            "mqtt": {
                "enabled": self.mqtt.enabled,
                "host": self.mqtt.host,
                "port": self.mqtt.port,
                "username": self.mqtt.username,
                "password": self.mqtt.password,
                "base_topic": self.mqtt.base_topic,
                "discovery_prefix": self.mqtt.discovery_prefix,
                "retain_discovery": self.mqtt.retain_discovery,
                "retain_state": self.mqtt.retain_state,
            },
            "home_assistant": {
                "enabled": self.home_assistant.enabled,
                "status_topic": self.home_assistant.status_topic,
                "gateway_device_id": self.home_assistant.gateway_device_id,
            },
            "web": {
                "enabled": self.web.enabled,
                "host": self.web.host,
                "port": self.web.port,
                "show_chart_markers": self.web.show_chart_markers,
                "appearance": self.web.appearance,
                "default_chart_range": self.web.default_chart_range,
                "default_chart_metric": self.web.default_chart_metric,
                "language": self.web.language,
            },
            "usb_otg": {
                "enabled": self.usb_otg.enabled,
                "image_path": self.usb_otg.image_path,
                "size_mb": self.usb_otg.size_mb,
                "gadget_name": self.usb_otg.gadget_name,
                "image_width_px": self.usb_otg.image_width_px,
                "image_height_px": self.usb_otg.image_height_px,
                "image_format": self.usb_otg.image_format,
                "appearance": self.usb_otg.appearance,
                "refresh_interval_seconds": self.usb_otg.refresh_interval_seconds,
                "overview_devices_per_image": self.usb_otg.overview_devices_per_image,
                "export_battery_overview": self.usb_otg.export_battery_overview,
                "export_fleet_trend": self.usb_otg.export_fleet_trend,
                "fleet_trend_metrics": self.usb_otg.fleet_trend_metrics,
                "fleet_trend_range": self.usb_otg.fleet_trend_range,
                "fleet_trend_device_ids": self.usb_otg.fleet_trend_device_ids,
            },
            "retention": {
                "raw_retention_days": self.retention.raw_retention_days,
                "daily_retention_days": self.retention.daily_retention_days,
            },
            "verbose": self.verbose,
        }


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a TOML table at the root.")
    return data


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    table = data.get(key, {})
    if not isinstance(table, dict):
        raise ValueError(f"Config key [{key}] must be a TOML table.")
    return table


def _resolve_registry_path(config_path: Path, declared_path: str) -> Path:
    registry_path = Path(declared_path)
    if registry_path.is_absolute():
        return registry_path
    return (config_path.parent / registry_path).resolve()


def _bool_to_toml(value: bool) -> str:
    return "true" if value else "false"


def _string_to_toml(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _string_sequence_to_toml(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_string_to_toml(value) for value in values) + "]"


def _string_tuple_from_toml(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return default


def write_config(path: Path, config: AppConfig) -> None:
    payload = "\n".join(
        [
            "[gateway]",
            f"name = {_string_to_toml(config.gateway.name)}",
            f"timezone = {_string_to_toml(config.gateway.timezone)}",
            f"poll_interval_seconds = {config.gateway.poll_interval_seconds}",
            f"device_registry = {_string_to_toml(config.gateway.device_registry)}",
            f"data_dir = {_string_to_toml(config.gateway.data_dir)}",
            f"reader_mode = {_string_to_toml(config.gateway.reader_mode)}",
            "",
            "[bluetooth]",
            f"adapter = {_string_to_toml(config.bluetooth.adapter)}",
            f"scan_timeout_seconds = {config.bluetooth.scan_timeout_seconds}",
            f"connect_timeout_seconds = {config.bluetooth.connect_timeout_seconds}",
            "",
            "[mqtt]",
            f"enabled = {_bool_to_toml(config.mqtt.enabled)}",
            f"host = {_string_to_toml(config.mqtt.host)}",
            f"port = {config.mqtt.port}",
            f"username = {_string_to_toml(config.mqtt.username)}",
            f"password = {_string_to_toml(config.mqtt.password)}",
            f"base_topic = {_string_to_toml(config.mqtt.base_topic)}",
            f"discovery_prefix = {_string_to_toml(config.mqtt.discovery_prefix)}",
            f"retain_discovery = {_bool_to_toml(config.mqtt.retain_discovery)}",
            f"retain_state = {_bool_to_toml(config.mqtt.retain_state)}",
            "",
            "[home_assistant]",
            f"enabled = {_bool_to_toml(config.home_assistant.enabled)}",
            f"status_topic = {_string_to_toml(config.home_assistant.status_topic)}",
            f"gateway_device_id = {_string_to_toml(config.home_assistant.gateway_device_id)}",
            "",
            "[web]",
            f"enabled = {_bool_to_toml(config.web.enabled)}",
            f"host = {_string_to_toml(config.web.host)}",
            f"port = {config.web.port}",
            f"show_chart_markers = {_bool_to_toml(config.web.show_chart_markers)}",
            f"appearance = {_string_to_toml(config.web.appearance)}",
            f"default_chart_range = {_string_to_toml(config.web.default_chart_range)}",
            f"default_chart_metric = {_string_to_toml(config.web.default_chart_metric)}",
            f"language = {_string_to_toml(config.web.language)}",
            "",
            "[usb_otg]",
            f"enabled = {_bool_to_toml(config.usb_otg.enabled)}",
            f"image_path = {_string_to_toml(config.usb_otg.image_path)}",
            f"size_mb = {config.usb_otg.size_mb}",
            f"gadget_name = {_string_to_toml(config.usb_otg.gadget_name)}",
            f"image_width_px = {config.usb_otg.image_width_px}",
            f"image_height_px = {config.usb_otg.image_height_px}",
            f"image_format = {_string_to_toml(config.usb_otg.image_format)}",
            f"appearance = {_string_to_toml(config.usb_otg.appearance)}",
            f"refresh_interval_seconds = {config.usb_otg.refresh_interval_seconds}",
            f"overview_devices_per_image = {config.usb_otg.overview_devices_per_image}",
            f"export_battery_overview = {_bool_to_toml(config.usb_otg.export_battery_overview)}",
            f"export_fleet_trend = {_bool_to_toml(config.usb_otg.export_fleet_trend)}",
            f"fleet_trend_metrics = {_string_sequence_to_toml(config.usb_otg.fleet_trend_metrics)}",
            f"fleet_trend_range = {_string_to_toml(config.usb_otg.fleet_trend_range)}",
            (
                "fleet_trend_device_ids = "
                f"{_string_sequence_to_toml(config.usb_otg.fleet_trend_device_ids)}"
            ),
            "",
            "[retention]",
            f"raw_retention_days = {config.retention.raw_retention_days}",
            f"daily_retention_days = {config.retention.daily_retention_days}",
            "",
        ]
    )
    path.write_text(payload, encoding="utf-8")


def load_config(path: Path) -> AppConfig:
    data = _read_toml(path)
    gateway_table = _require_table(data, "gateway")
    bluetooth_table = _require_table(data, "bluetooth")
    mqtt_table = _require_table(data, "mqtt")
    home_assistant_table = _require_table(data, "home_assistant")
    web_table = _require_table(data, "web")
    usb_otg_table = _require_table(data, "usb_otg")
    retention_table = _require_table(data, "retention")

    gateway = GatewayConfig(
        name=str(gateway_table.get("name", "BMGateway")),
        timezone=str(gateway_table.get("timezone", "Europe/Rome")),
        poll_interval_seconds=int(gateway_table.get("poll_interval_seconds", 300)),
        device_registry=str(gateway_table.get("device_registry", "devices.toml")),
        data_dir=str(gateway_table.get("data_dir", "data")),
        reader_mode=str(gateway_table.get("reader_mode", "fake")),
    )
    bluetooth = BluetoothConfig(
        adapter=str(bluetooth_table.get("adapter", "auto")),
        scan_timeout_seconds=int(bluetooth_table.get("scan_timeout_seconds", 15)),
        connect_timeout_seconds=int(bluetooth_table.get("connect_timeout_seconds", 45)),
    )
    mqtt = MQTTConfig(
        enabled=bool(mqtt_table.get("enabled", True)),
        host=str(mqtt_table.get("host", "mqtt.local")),
        port=int(mqtt_table.get("port", 1883)),
        username=str(mqtt_table.get("username", "mqtt-user")),
        password=str(mqtt_table.get("password", "CHANGE_ME")),
        base_topic=str(mqtt_table.get("base_topic", "bm_gateway")),
        discovery_prefix=str(mqtt_table.get("discovery_prefix", "homeassistant")),
        retain_discovery=bool(mqtt_table.get("retain_discovery", True)),
        retain_state=bool(mqtt_table.get("retain_state", False)),
    )
    home_assistant = HomeAssistantConfig(
        enabled=bool(home_assistant_table.get("enabled", True)),
        status_topic=str(home_assistant_table.get("status_topic", "homeassistant/status")),
        gateway_device_id=str(home_assistant_table.get("gateway_device_id", "bm_gateway")),
    )
    web = WebConfig(
        enabled=bool(web_table.get("enabled", True)),
        host=str(web_table.get("host", "0.0.0.0")),
        port=int(web_table.get("port", 80)),
        show_chart_markers=bool(web_table.get("show_chart_markers", False)),
        appearance=str(web_table.get("appearance", "system")),
        default_chart_range=str(web_table.get("default_chart_range", "7")),
        default_chart_metric=str(web_table.get("default_chart_metric", "soc")),
        language=str(web_table.get("language", "auto")),
    )
    usb_otg = USBOTGConfig(
        enabled=bool(usb_otg_table.get("enabled", False)),
        image_path=str(
            usb_otg_table.get("image_path", "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img")
        ),
        size_mb=int(usb_otg_table.get("size_mb", 64)),
        gadget_name=str(usb_otg_table.get("gadget_name", "bmgw_frame")),
        image_width_px=int(usb_otg_table.get("image_width_px", 480)),
        image_height_px=int(usb_otg_table.get("image_height_px", 234)),
        image_format=str(usb_otg_table.get("image_format", "jpeg")),
        appearance=str(usb_otg_table.get("appearance", "light")),
        refresh_interval_seconds=int(usb_otg_table.get("refresh_interval_seconds", 0)),
        overview_devices_per_image=int(usb_otg_table.get("overview_devices_per_image", 3)),
        export_battery_overview=bool(usb_otg_table.get("export_battery_overview", True)),
        export_fleet_trend=bool(usb_otg_table.get("export_fleet_trend", True)),
        fleet_trend_metrics=_string_tuple_from_toml(
            usb_otg_table.get("fleet_trend_metrics"),
            default=("soc",),
        ),
        fleet_trend_range=str(usb_otg_table.get("fleet_trend_range", "7")),
        fleet_trend_device_ids=_string_tuple_from_toml(
            usb_otg_table.get("fleet_trend_device_ids"),
            default=(),
        ),
    )
    retention = RetentionConfig(
        raw_retention_days=int(retention_table.get("raw_retention_days", 180)),
        daily_retention_days=int(retention_table.get("daily_retention_days", 0)),
    )
    source_path = path.resolve()
    device_registry_path = _resolve_registry_path(source_path, gateway.device_registry)

    return AppConfig(
        source_path=source_path,
        device_registry_path=device_registry_path,
        gateway=gateway,
        bluetooth=bluetooth,
        mqtt=mqtt,
        home_assistant=home_assistant,
        web=web,
        retention=retention,
        usb_otg=usb_otg,
    )


def validate_config(config: AppConfig) -> list[str]:
    errors: list[str] = []
    if not config.gateway.name.strip():
        errors.append("gateway.name must not be empty")
    if config.gateway.poll_interval_seconds <= 0:
        errors.append("gateway.poll_interval_seconds must be greater than zero")
    if config.gateway.reader_mode not in {"fake", "live"}:
        errors.append("gateway.reader_mode must be one of: fake, live")
    if config.bluetooth.scan_timeout_seconds <= 0:
        errors.append("bluetooth.scan_timeout_seconds must be greater than zero")
    if config.bluetooth.connect_timeout_seconds <= 0:
        errors.append("bluetooth.connect_timeout_seconds must be greater than zero")
    if not config.mqtt.host.strip():
        errors.append("mqtt.host must not be empty")
    if config.mqtt.port <= 0:
        errors.append("mqtt.port must be greater than zero")
    if not config.mqtt.base_topic.strip():
        errors.append("mqtt.base_topic must not be empty")
    if not config.mqtt.discovery_prefix.strip():
        errors.append("mqtt.discovery_prefix must not be empty")
    if not config.home_assistant.gateway_device_id.strip():
        errors.append("home_assistant.gateway_device_id must not be empty")
    if config.web.port <= 0:
        errors.append("web.port must be greater than zero")
    if config.web.port > 65535:
        errors.append("web.port must be less than or equal to 65535")
    if config.web.appearance not in {"light", "dark", "system"}:
        errors.append("web.appearance must be one of: light, dark, system")
    allowed_chart_ranges = {"raw", "1", "3", "5", "7", "30", "90", "365", "730", "all"}
    if config.web.default_chart_range not in allowed_chart_ranges:
        errors.append(
            "web.default_chart_range must be one of: raw, 1, 3, 5, 7, 30, 90, 365, 730, all"
        )
    if config.web.default_chart_metric not in {"voltage", "soc", "temperature"}:
        errors.append("web.default_chart_metric must be one of: voltage, soc, temperature")
    if not is_supported_language_preference(config.web.language):
        errors.append("web.language must be one of: " + ", ".join(allowed_language_codes()))
    if not config.usb_otg.image_path.strip():
        errors.append("usb_otg.image_path must not be empty")
    if config.usb_otg.size_mb <= 0:
        errors.append("usb_otg.size_mb must be greater than zero")
    if config.usb_otg.size_mb > 4096:
        errors.append("usb_otg.size_mb must be less than or equal to 4096")
    if not config.usb_otg.gadget_name.strip():
        errors.append("usb_otg.gadget_name must not be empty")
    if config.usb_otg.image_width_px < 160:
        errors.append("usb_otg.image_width_px must be at least 160")
    if config.usb_otg.image_height_px < 120:
        errors.append("usb_otg.image_height_px must be at least 120")
    if config.usb_otg.image_format not in {"jpeg", "png", "bmp"}:
        errors.append("usb_otg.image_format must be one of: jpeg, png, bmp")
    if config.usb_otg.appearance not in {"light", "dark"}:
        errors.append("usb_otg.appearance must be one of: light, dark")
    if config.usb_otg.refresh_interval_seconds < 0:
        errors.append("usb_otg.refresh_interval_seconds must be zero or greater")
    if not 1 <= config.usb_otg.overview_devices_per_image <= 10:
        errors.append("usb_otg.overview_devices_per_image must be between 1 and 10")
    allowed_frame_metrics = {"voltage", "soc", "temperature"}
    if not config.usb_otg.fleet_trend_metrics:
        errors.append("usb_otg.fleet_trend_metrics must include at least one metric")
    invalid_frame_metrics = [
        metric
        for metric in config.usb_otg.fleet_trend_metrics
        if metric not in allowed_frame_metrics
    ]
    if invalid_frame_metrics:
        errors.append("usb_otg.fleet_trend_metrics must contain only: voltage, soc, temperature")
    allowed_usb_otg_fleet_ranges = {"1", "3", "5", "7", "30", "90", "365", "730", "all"}
    if config.usb_otg.fleet_trend_range not in allowed_usb_otg_fleet_ranges:
        errors.append("usb_otg.fleet_trend_range must be one of: 1, 3, 5, 7, 30, 90, 365, 730, all")
    if config.retention.raw_retention_days <= 0:
        errors.append("retention.raw_retention_days must be greater than zero")
    if config.retention.daily_retention_days < 0:
        errors.append("retention.daily_retention_days must be zero or greater")
    if not config.device_registry_path.exists():
        errors.append(f"device registry file not found: {config.device_registry_path}")
    return errors
