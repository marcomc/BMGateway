"""Home Assistant contract helpers for BMGateway."""

from __future__ import annotations

from typing import Any, cast

from . import __version__
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

GATEWAY_COMPONENT_SPECS: dict[str, dict[str, Any]] = {
    "version": {
        "p": "sensor",
        "name": "Version",
        "icon": "mdi:identifier",
        "entity_category": "diagnostic",
    },
    "uptime": {
        "p": "sensor",
        "name": "Uptime",
        "icon": "mdi:timer-outline",
        "unit_of_measurement": "s",
        "entity_category": "diagnostic",
    },
    "active_adapter": {
        "p": "sensor",
        "name": "Active Adapter",
        "icon": "mdi:bluetooth",
        "entity_category": "diagnostic",
    },
    "running": {
        "p": "binary_sensor",
        "name": "Running",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
        "value_template": "{{ 'ON' if value_json.running else 'OFF' }}",
        "payload_on": "ON",
        "payload_off": "OFF",
    },
    "mqtt_connected": {
        "p": "binary_sensor",
        "name": "MQTT Connected",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
        "value_template": "{{ 'ON' if value_json.mqtt_connected else 'OFF' }}",
        "payload_on": "ON",
        "payload_off": "OFF",
    },
    "devices_total": {
        "p": "sensor",
        "name": "Devices Total",
        "icon": "mdi:counter",
        "entity_category": "diagnostic",
    },
    "devices_online": {
        "p": "sensor",
        "name": "Devices Online",
        "icon": "mdi:bluetooth-connect",
    },
}

DEVICE_COMPONENT_SPECS: dict[str, dict[str, Any]] = {
    "voltage": {
        "p": "sensor",
        "name": "Voltage",
        "device_class": "voltage",
        "unit_of_measurement": "V",
        "state_class": "measurement",
        "suggested_display_precision": 2,
    },
    "soc": {
        "p": "sensor",
        "name": "State of Charge",
        "device_class": "battery",
        "unit_of_measurement": "%",
        "state_class": "measurement",
        "suggested_display_precision": 0,
    },
    "temperature": {
        "p": "sensor",
        "name": "Temperature",
        "device_class": "temperature",
        "unit_of_measurement": "°C",
        "state_class": "measurement",
        "suggested_display_precision": 1,
    },
    "connected": {
        "p": "binary_sensor",
        "name": "Connected",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
        "value_template": "{{ 'ON' if value_json.connected else 'OFF' }}",
        "payload_on": "ON",
        "payload_off": "OFF",
    },
    "availability_reason": {
        "p": "sensor",
        "name": "Availability Reason",
        "icon": "mdi:lan-disconnect",
        "entity_category": "diagnostic",
    },
    "error_code": {
        "p": "sensor",
        "name": "Error Code",
        "icon": "mdi:alert-circle-outline",
        "entity_category": "diagnostic",
    },
    "last_seen": {
        "p": "sensor",
        "name": "Last Seen",
        "device_class": "timestamp",
        "entity_category": "diagnostic",
    },
    "rssi": {
        "p": "sensor",
        "name": "RSSI",
        "device_class": "signal_strength",
        "unit_of_measurement": "dBm",
        "state_class": "measurement",
        "entity_category": "diagnostic",
    },
    "state": {
        "p": "sensor",
        "name": "Reported State",
        "icon": "mdi:car-battery",
    },
}


def _component_payload(
    *,
    state_topic: str,
    availability_topic: str,
    unique_id: str,
    entity_key: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "p": spec["p"],
        "unique_id": unique_id,
        "state_topic": state_topic,
        "availability_topic": availability_topic,
    }
    if "value_template" in spec:
        payload["value_template"] = spec["value_template"]
    else:
        payload["value_template"] = f"{{{{ value_json.{entity_key} }}}}"
    for key in (
        "name",
        "icon",
        "device_class",
        "unit_of_measurement",
        "state_class",
        "entity_category",
        "payload_on",
        "payload_off",
        "suggested_display_precision",
    ):
        if key in spec:
            payload[key] = spec[key]
    return payload


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
            "mf": "BMGateway",
            "mdl": "Gateway",
            "sw": __version__,
        },
        "o": {"name": config.gateway.name, "sw": __version__},
        "cmps": {
            entity: _component_payload(
                state_topic=str(gateway["state_topic"]),
                availability_topic=str(gateway["availability_topic"]),
                unique_id=f"{config.home_assistant.gateway_device_id}_{entity}",
                entity_key=entity,
                spec=GATEWAY_COMPONENT_SPECS[entity],
            )
            for entity in GATEWAY_ENTITIES
        },
    }

    for device in devices:
        state_topic = f"{config.mqtt.base_topic.rstrip('/')}/devices/{device.id}/state"
        availability_topic = (
            f"{config.mqtt.base_topic.rstrip('/')}/devices/{device.id}/availability"
        )
        device_model = device.type.upper()
        if device.battery_brand or device.battery_model:
            battery_parts = [part for part in (device.battery_brand, device.battery_model) if part]
            device_model = f"{device_model} {' '.join(battery_parts)}".strip()
        payloads[f"{config.mqtt.discovery_prefix.rstrip('/')}/device/{device.id}/config"] = {
            "dev": {
                "ids": device.id,
                "name": device.name,
                "mf": "BMGateway",
                "mdl": device_model,
                "sw": __version__,
            },
            "o": {"name": config.gateway.name, "sw": __version__},
            "cmps": {
                entity: _component_payload(
                    state_topic=state_topic,
                    availability_topic=availability_topic,
                    unique_id=f"{device.id}_{entity}",
                    entity_key=entity,
                    spec=DEVICE_COMPONENT_SPECS[entity],
                )
                for entity in DEVICE_ENTITIES
            },
        }
    return payloads
