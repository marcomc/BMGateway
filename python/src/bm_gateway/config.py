"""Configuration support for BMGateway."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "bm-gateway" / "config.toml"


@dataclass(frozen=True)
class GatewayConfig:
    name: str = "BMGateway"
    timezone: str = "Europe/Rome"
    poll_interval_seconds: int = 15
    device_registry: str = "devices.toml"
    data_dir: str = "data"


@dataclass(frozen=True)
class BluetoothConfig:
    adapter: str = "auto"
    scan_timeout_seconds: int = 8
    connect_timeout_seconds: int = 10


@dataclass(frozen=True)
class MQTTConfig:
    enabled: bool = True
    host: str = "localhost"
    port: int = 1883
    username: str = "homeassistant"
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
    port: int = 8080


@dataclass(frozen=True)
class AppConfig:
    source_path: Path
    device_registry_path: Path
    gateway: GatewayConfig
    bluetooth: BluetoothConfig
    mqtt: MQTTConfig
    home_assistant: HomeAssistantConfig
    web: WebConfig
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


def load_config(path: Path) -> AppConfig:
    data = _read_toml(path)
    gateway_table = _require_table(data, "gateway")
    bluetooth_table = _require_table(data, "bluetooth")
    mqtt_table = _require_table(data, "mqtt")
    home_assistant_table = _require_table(data, "home_assistant")
    web_table = _require_table(data, "web")

    gateway = GatewayConfig(
        name=str(gateway_table.get("name", "BMGateway")),
        timezone=str(gateway_table.get("timezone", "Europe/Rome")),
        poll_interval_seconds=int(gateway_table.get("poll_interval_seconds", 15)),
        device_registry=str(gateway_table.get("device_registry", "devices.toml")),
        data_dir=str(gateway_table.get("data_dir", "data")),
    )
    bluetooth = BluetoothConfig(
        adapter=str(bluetooth_table.get("adapter", "auto")),
        scan_timeout_seconds=int(bluetooth_table.get("scan_timeout_seconds", 8)),
        connect_timeout_seconds=int(bluetooth_table.get("connect_timeout_seconds", 10)),
    )
    mqtt = MQTTConfig(
        enabled=bool(mqtt_table.get("enabled", True)),
        host=str(mqtt_table.get("host", "localhost")),
        port=int(mqtt_table.get("port", 1883)),
        username=str(mqtt_table.get("username", "homeassistant")),
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
        port=int(web_table.get("port", 8080)),
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
    )


def validate_config(config: AppConfig) -> list[str]:
    errors: list[str] = []
    if not config.gateway.name.strip():
        errors.append("gateway.name must not be empty")
    if config.gateway.poll_interval_seconds <= 0:
        errors.append("gateway.poll_interval_seconds must be greater than zero")
    if config.bluetooth.scan_timeout_seconds <= 0:
        errors.append("bluetooth.scan_timeout_seconds must be greater than zero")
    if config.bluetooth.connect_timeout_seconds <= 0:
        errors.append("bluetooth.connect_timeout_seconds must be greater than zero")
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
    if not config.device_registry_path.exists():
        errors.append(f"device registry file not found: {config.device_registry_path}")
    return errors
