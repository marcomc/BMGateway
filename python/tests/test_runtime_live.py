from __future__ import annotations

from pathlib import Path

from bm_gateway.config import (
    AppConfig,
    BluetoothConfig,
    GatewayConfig,
    HomeAssistantConfig,
    MQTTConfig,
    RetentionConfig,
    WebConfig,
)
from bm_gateway.device_registry import Device
from bm_gateway.drivers.bm200 import BM200Measurement, BM200TimeoutError
from bm_gateway.runtime import build_snapshot, database_file_path
from bm_gateway.state_store import fetch_counts, persist_snapshot


def test_build_snapshot_uses_live_bm200_reader_when_enabled() -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="live"),
        bluetooth=BluetoothConfig(adapter="hci0"),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
        retention=RetentionConfig(),
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


def test_build_snapshot_classifies_live_reader_errors() -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="live"),
        bluetooth=BluetoothConfig(adapter="hci0"),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
        retention=RetentionConfig(),
    )
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            enabled=True,
        )
    ]

    def failing_reader(device: Device, adapter: str) -> BM200Measurement:
        raise BM200TimeoutError(f"{device.id}:{adapter}")

    snapshot = build_snapshot(config, devices, bm200_reader=failing_reader)

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].state == "error"
    assert snapshot.devices[0].error_code == "timeout"
    assert snapshot.devices[0].error_detail == "bm200_house:hci0"


def test_persist_snapshot_writes_gateway_and_device_rows(tmp_path: Path) -> None:
    config = AppConfig(
        source_path=tmp_path / "gateway.toml",
        device_registry_path=tmp_path / "devices.toml",
        gateway=GatewayConfig(reader_mode="live", data_dir="data"),
        bluetooth=BluetoothConfig(adapter="hci0"),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
        retention=RetentionConfig(),
    )
    devices = [
        Device(
            id="bm200_house",
            type="bm200",
            name="BM200 House",
            mac="AA:BB:CC:DD:EE:01",
            enabled=True,
        )
    ]

    def fake_reader(device: Device, adapter: str) -> BM200Measurement:
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="normal",
        )

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)
    database_path = database_file_path(config, state_dir=tmp_path / "state")

    persist_snapshot(database_path, snapshot)

    counts = fetch_counts(database_path)
    assert counts["gateway_snapshots"] == 1
    assert counts["device_readings"] == 1
    assert counts["device_daily_rollups"] == 1


def test_build_snapshot_marks_non_bm200_devices_unsupported_in_live_mode() -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="live"),
        bluetooth=BluetoothConfig(adapter="hci0"),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
        retention=RetentionConfig(),
    )
    devices = [
        Device(
            id="bm300_van",
            type="bm300pro",
            name="BM300 Van",
            mac="AA:BB:CC:DD:EE:02",
            enabled=True,
        )
    ]

    snapshot = build_snapshot(config, devices)

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].state == "unsupported"
    assert snapshot.devices[0].error_code == "unsupported_device_type"
