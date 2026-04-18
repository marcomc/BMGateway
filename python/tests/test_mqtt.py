from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from bm_gateway.config import (
    AppConfig,
    BluetoothConfig,
    GatewayConfig,
    HomeAssistantConfig,
    MQTTConfig,
    RetentionConfig,
    WebConfig,
)
from bm_gateway.contract import build_discovery_payloads
from bm_gateway.device_registry import Device
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.mqtt import MQTTPublisher, build_publish_operations


def _config() -> AppConfig:
    return AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(name="BMGateway"),
        bluetooth=BluetoothConfig(adapter="hci0"),
        mqtt=MQTTConfig(base_topic="bm_gateway", discovery_prefix="homeassistant"),
        home_assistant=HomeAssistantConfig(gateway_device_id="bm_gateway"),
        web=WebConfig(),
        retention=RetentionConfig(),
    )


def _snapshot() -> GatewaySnapshot:
    return GatewaySnapshot(
        generated_at="2026-04-18T10:00:00+02:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=True,
        mqtt_connected=True,
        devices_total=2,
        devices_online=1,
        poll_interval_seconds=15,
        devices=[
            DeviceReading(
                id="bm200_house",
                type="bm200",
                name="BM200 House",
                mac="AA:BB:CC:DD:EE:01",
                enabled=True,
                connected=True,
                voltage=12.74,
                soc=81,
                temperature=22.4,
                rssi=-62,
                state="normal",
                error_code=None,
                error_detail=None,
                last_seen="2026-04-18T10:00:00+02:00",
                adapter="hci0",
                driver="bm200",
            ),
            DeviceReading(
                id="bm300_van",
                type="bm300pro",
                name="BM300 Van",
                mac="AA:BB:CC:DD:EE:02",
                enabled=True,
                connected=False,
                voltage=0.0,
                soc=0,
                temperature=None,
                rssi=None,
                state="error",
                error_code="unsupported_device_type",
                error_detail="bm300pro",
                last_seen="2026-04-18T10:00:00+02:00",
                adapter="hci0",
                driver="bm300pro",
            ),
        ],
    )


def test_build_publish_operations_emits_gateway_and_device_availability_topics() -> None:
    config = _config()
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            enabled=True,
        ),
        Device(
            id="bm300_van",
            type="bm300pro",
            name="BM300 Van",
            mac="AA:BB:CC:DD:EE:02",
            enabled=True,
        ),
    ]

    operations = build_publish_operations(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        publish_discovery=True,
    )

    topics = {operation["topic"]: operation for operation in operations}
    assert topics["bm_gateway/gateway/availability"]["payload"] == "online"
    assert topics["bm_gateway/devices/bm200_house/availability"]["payload"] == "online"
    assert topics["bm_gateway/devices/bm300_van/availability"]["payload"] == "offline"

    device_state = json.loads(str(topics["bm_gateway/devices/bm300_van/state"]["payload"]))
    assert device_state["availability"] == "offline"
    assert device_state["availability_reason"] == "unsupported_device_type"


def test_build_discovery_payloads_include_availability_topics() -> None:
    config = _config()
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            enabled=True,
        )
    ]

    payloads = build_discovery_payloads(config, devices)

    gateway_payload = payloads["homeassistant/device/bm_gateway/config"]
    device_payload = payloads["homeassistant/device/bm200_house/config"]
    gateway_components = cast(dict[str, dict[str, object]], gateway_payload["cmps"])
    device_components = cast(dict[str, dict[str, object]], device_payload["cmps"])
    assert gateway_components["running"]["availability_topic"] == (
        "bm_gateway/gateway/availability"
    )
    assert device_components["connected"]["availability_topic"] == (
        "bm_gateway/devices/bm200_house/availability"
    )


def test_mqtt_publisher_waits_for_publish_before_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            enabled=True,
        )
    ]
    publish_info = Mock()
    fake_client = Mock()
    fake_client.publish.return_value = publish_info

    publisher = MQTTPublisher()
    monkeypatch.setattr(publisher, "_build_client", lambda: fake_client)

    result = publisher.publish_runtime(
        config=config,
        devices=devices,
        snapshot=_snapshot(),
        publish_discovery=False,
    )

    assert result is True
    assert publish_info.wait_for_publish.call_count == fake_client.publish.call_count
    fake_client.disconnect.assert_called_once_with()
