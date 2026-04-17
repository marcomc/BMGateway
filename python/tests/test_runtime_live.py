from __future__ import annotations

from pathlib import Path

from bm_gateway.config import (
    AppConfig,
    BluetoothConfig,
    GatewayConfig,
    HomeAssistantConfig,
    MQTTConfig,
    WebConfig,
)
from bm_gateway.device_registry import Device
from bm_gateway.drivers.bm200 import BM200Measurement
from bm_gateway.runtime import build_snapshot


def test_build_snapshot_uses_live_bm200_reader_when_enabled() -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="live"),
        bluetooth=BluetoothConfig(adapter="hci0"),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
    )
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
            enabled=False,
        ),
    ]

    def fake_reader(device: Device, adapter: str) -> BM200Measurement:
        assert device.id == "bm200_house"
        assert adapter == "hci0"
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="normal",
        )

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)

    assert snapshot.active_adapter == "hci0"
    assert snapshot.devices_online == 1
    assert snapshot.devices[0].voltage == 12.73
    assert snapshot.devices[0].soc == 58
    assert snapshot.devices[0].state == "normal"
    assert snapshot.devices[0].temperature is None
    assert snapshot.devices[1].connected is False
    assert snapshot.devices[1].state == "disabled"
