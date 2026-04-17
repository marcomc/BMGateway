"""Home Assistant contract helpers for BMGateway."""

from __future__ import annotations

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
                "discovery_topic": f"{discovery_prefix}/device/{device.id}/config",
                "entities": list(DEVICE_ENTITIES),
            }
            for device in devices
        ],
    }
