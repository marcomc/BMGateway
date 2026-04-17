"""MQTT publishing for BMGateway."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, cast

import paho.mqtt.client as mqtt

from .config import AppConfig
from .contract import build_contract, build_discovery_payloads
from .device_registry import Device
from .models import GatewaySnapshot


class Publisher(Protocol):
    def publish_runtime(
        self,
        *,
        config: AppConfig,
        devices: list[Device],
        snapshot: GatewaySnapshot,
        publish_discovery: bool,
    ) -> bool: ...


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

    def publish_runtime(
        self,
        *,
        config: AppConfig,
        devices: list[Device],
        snapshot: GatewaySnapshot,
        publish_discovery: bool,
    ) -> bool:
        client = mqtt.Client()
        if config.mqtt.username:
            client.username_pw_set(config.mqtt.username, config.mqtt.password)
        client.connect(config.mqtt.host, config.mqtt.port, keepalive=self.timeout_seconds)
        client.loop_start()
        try:
            contract = build_contract(config, devices)
            gateway = cast(dict[str, object], contract["gateway"])
            base_topic = config.mqtt.base_topic.rstrip("/")
            gateway_payload = {
                "version": "0.1.0",
                "uptime": config.gateway.poll_interval_seconds,
                "active_adapter": snapshot.active_adapter,
                "running": True,
                "mqtt_connected": True,
                "devices_total": snapshot.devices_total,
                "devices_online": snapshot.devices_online,
                "generated_at": snapshot.generated_at,
            }
            client.publish(
                str(gateway["state_topic"]),
                json.dumps(gateway_payload, sort_keys=True),
                qos=0,
                retain=config.mqtt.retain_state,
            )
            for reading in snapshot.devices:
                client.publish(
                    f"{base_topic}/devices/{reading.id}/state",
                    json.dumps(
                        {
                            "voltage": reading.voltage,
                            "soc": reading.soc,
                            "temperature": reading.temperature,
                            "connected": reading.connected,
                            "last_seen": reading.last_seen,
                            "rssi": reading.rssi,
                            "state": reading.state,
                            "adapter": reading.adapter,
                            "driver": reading.driver,
                        },
                        sort_keys=True,
                    ),
                    qos=0,
                    retain=config.mqtt.retain_state,
                )
            if publish_discovery:
                for topic, payload in build_discovery_payloads(config, devices).items():
                    client.publish(
                        topic,
                        json.dumps(payload, sort_keys=True),
                        qos=0,
                        retain=config.mqtt.retain_discovery,
                    )
        finally:
            client.loop_stop()
            client.disconnect()
        return True
