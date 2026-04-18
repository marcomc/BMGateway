"""MQTT publishing for BMGateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessageInfo

from .config import AppConfig
from .contract import build_contract, build_discovery_payloads
from .device_registry import Device
from .models import DeviceReading, GatewaySnapshot


class Publisher(Protocol):
    def publish_runtime(
        self,
        *,
        config: AppConfig,
        devices: list[Device],
        snapshot: GatewaySnapshot,
        publish_discovery: bool,
    ) -> bool: ...


def _availability_for_reading(reading: DeviceReading) -> tuple[str, str]:
    if reading.connected:
        return "online", "ok"
    if reading.error_code:
        return "offline", reading.error_code
    if reading.state == "disabled":
        return "offline", "disabled"
    if reading.state == "unsupported":
        return "offline", "unsupported"
    return "offline", reading.state


def build_publish_operations(
    *,
    config: AppConfig,
    devices: list[Device],
    snapshot: GatewaySnapshot,
    publish_discovery: bool,
) -> list[dict[str, object]]:
    contract = build_contract(config, devices)
    gateway = cast(dict[str, object], contract["gateway"])
    base_topic = config.mqtt.base_topic.rstrip("/")

    operations: list[dict[str, object]] = [
        {
            "topic": str(gateway["availability_topic"]),
            "payload": "online",
            "retain": True,
        },
        {
            "topic": str(gateway["state_topic"]),
            "payload": json.dumps(
                {
                    "version": "0.1.0",
                    "uptime": config.gateway.poll_interval_seconds,
                    "active_adapter": snapshot.active_adapter,
                    "running": True,
                    "mqtt_connected": True,
                    "devices_total": snapshot.devices_total,
                    "devices_online": snapshot.devices_online,
                    "generated_at": snapshot.generated_at,
                    "availability": "online",
                },
                sort_keys=True,
            ),
            "retain": config.mqtt.retain_state,
        },
    ]

    for reading in snapshot.devices:
        availability, availability_reason = _availability_for_reading(reading)
        operations.extend(
            [
                {
                    "topic": f"{base_topic}/devices/{reading.id}/availability",
                    "payload": availability,
                    "retain": True,
                },
                {
                    "topic": f"{base_topic}/devices/{reading.id}/state",
                    "payload": json.dumps(
                        {
                            "voltage": reading.voltage,
                            "soc": reading.soc,
                            "temperature": reading.temperature,
                            "connected": reading.connected,
                            "availability": availability,
                            "availability_reason": availability_reason,
                            "last_seen": reading.last_seen,
                            "rssi": reading.rssi,
                            "state": reading.state,
                            "error_code": reading.error_code,
                            "error_detail": reading.error_detail,
                            "adapter": reading.adapter,
                            "driver": reading.driver,
                        },
                        sort_keys=True,
                    ),
                    "retain": config.mqtt.retain_state,
                },
            ]
        )

    if publish_discovery:
        for topic, payload in build_discovery_payloads(config, devices).items():
            operations.append(
                {
                    "topic": topic,
                    "payload": json.dumps(payload, sort_keys=True),
                    "retain": config.mqtt.retain_discovery,
                }
            )

    return operations


@dataclass
class DryRunPublisher:
    def publish_runtime(
        self,
        *,
        config: AppConfig,
        devices: list[Device],
        snapshot: GatewaySnapshot,
        publish_discovery: bool,
    ) -> bool:
        return False


@dataclass
class MQTTPublisher:
    timeout_seconds: int = 10

    def _build_client(self) -> mqtt.Client:
        callback_api_version = getattr(mqtt, "CallbackAPIVersion", None)
        if callback_api_version is None:
            return mqtt.Client()
        return mqtt.Client(cast(Any, callback_api_version).VERSION2)

    def publish_runtime(
        self,
        *,
        config: AppConfig,
        devices: list[Device],
        snapshot: GatewaySnapshot,
        publish_discovery: bool,
    ) -> bool:
        client = self._build_client()
        if config.mqtt.username:
            client.username_pw_set(config.mqtt.username, config.mqtt.password)
        client.connect(config.mqtt.host, config.mqtt.port, keepalive=self.timeout_seconds)
        client.loop_start()
        try:
            pending_messages: list[MQTTMessageInfo] = []
            for operation in build_publish_operations(
                config=config,
                devices=devices,
                snapshot=snapshot,
                publish_discovery=publish_discovery,
            ):
                pending_messages.append(
                    client.publish(
                        str(operation["topic"]),
                        str(operation["payload"]),
                        qos=0,
                        retain=bool(operation["retain"]),
                    )
                )
            for message_info in pending_messages:
                message_info.wait_for_publish()
        finally:
            client.loop_stop()
            client.disconnect()
        return True
