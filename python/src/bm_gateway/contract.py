"""Home Assistant contract helpers for BMGateway."""

from __future__ import annotations

from typing import cast

from .config import AppConfig
from .device_registry import Device

GATEWAY_ENTITIES = [
    "version",
    "uptime",
    "active_adapter",
    "running",
    "mqtt_connected",
    "devices_total",
    "devices_online",
]

DEVICE_ENTITIES = [
    "voltage",
    "soc",
    "temperature",
    "connected",
    "availability_reason",
    "error_code",
    "last_seen",
    "rssi",
    "state",
]


def build_contract(config: AppConfig, devices: list[Device]) -> dict[str, object]:
    base_topic = config.mqtt.base_topic.rstrip("/")
    discovery_prefix = config.mqtt.discovery_prefix.rstrip("/")

    return {
        "gateway": {
            "device_id": config.home_assistant.gateway_device_id,
            "state_topic": f"{base_topic}/gateway/state",
            "availability_topic": f"{base_topic}/gateway/availability",
            "discovery_topic": (
                f"{discovery_prefix}/device/{config.home_assistant.gateway_device_id}/config"
            ),
            "entities": list(GATEWAY_ENTITIES),
        },
        "devices": [
            {
                "id": device.id,
                "enabled": device.enabled,
                "state_topic": f"{base_topic}/devices/{device.id}/state",
                "availability_topic": f"{base_topic}/devices/{device.id}/availability",
                "discovery_topic": f"{discovery_prefix}/device/{device.id}/config",
                "entities": list(DEVICE_ENTITIES),
            }
            for device in devices
        ],
    }


def build_discovery_payloads(
    config: AppConfig, devices: list[Device]
) -> dict[str, dict[str, object]]:
    contract = build_contract(config, devices)
    payloads: dict[str, dict[str, object]] = {}

    gateway = cast(dict[str, object], contract["gateway"])
    payloads[str(gateway["discovery_topic"])] = {
        "dev": {
            "ids": config.home_assistant.gateway_device_id,
            "name": config.gateway.name,
            "sw": "0.1.0",
        },
        "o": {"name": config.gateway.name, "sw": "0.1.0"},
        "cmps": {
            entity: {
                "p": "sensor",
                "unique_id": f"{config.home_assistant.gateway_device_id}_{entity}",
                "state_topic": str(gateway["state_topic"]),
                "availability_topic": str(gateway["availability_topic"]),
                "value_template": f"{{{{ value_json.{entity} }}}}",
            }
            for entity in GATEWAY_ENTITIES
        },
    }

    for device in devices:
        state_topic = f"{config.mqtt.base_topic.rstrip('/')}/devices/{device.id}/state"
        payloads[f"{config.mqtt.discovery_prefix.rstrip('/')}/device/{device.id}/config"] = {
            "dev": {
                "ids": device.id,
                "name": device.name,
                "mdl": device.type,
                "sw": "0.1.0",
            },
            "o": {"name": config.gateway.name, "sw": "0.1.0"},
            "cmps": {
                entity: {
                    "p": "sensor",
                    "unique_id": f"{device.id}_{entity}",
                    "state_topic": state_topic,
                    "availability_topic": (
                        f"{config.mqtt.base_topic.rstrip('/')}/devices/{device.id}/availability"
                    ),
                    "value_template": f"{{{{ value_json.{entity} }}}}",
                }
                for entity in DEVICE_ENTITIES
            },
        }
    return payloads
