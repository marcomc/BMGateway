from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
from bm_gateway.bluetooth_recovery import BluetoothRecoveryRequiredError
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
from bm_gateway.drivers.bm200 import BleakDeviceNotFoundError, BM200Measurement, BM200TimeoutError
from bm_gateway.drivers.bm300 import BM300Measurement, BM300TimeoutError
from bm_gateway.runtime import build_snapshot, database_file_path, recover_adapter
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

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        assert device.id == "bm200_house"
        assert adapter == "hci0"
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="charging",
            temperature=23.0,
        )

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)

    assert snapshot.active_adapter == "hci0"
    assert snapshot.devices_online == 1
    assert snapshot.devices[0].voltage == 12.73
    assert snapshot.devices[0].soc == 58
    assert snapshot.devices[0].state == "charging"
    assert snapshot.devices[0].temperature == 23.0
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

    def failing_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        raise BM200TimeoutError(f"{device.id}:{adapter}")

    snapshot = build_snapshot(config, devices, bm200_reader=failing_reader)

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].state == "error"
    assert snapshot.devices[0].error_code == "timeout"
    assert snapshot.devices[0].error_detail == "bm200_house:hci0"


def test_build_snapshot_classifies_device_not_found_as_offline() -> None:
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

    def failing_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        raise BleakDeviceNotFoundError(device.mac)

    snapshot = build_snapshot(config, devices, bm200_reader=failing_reader)

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].state == "offline"
    assert snapshot.devices[0].error_code == "device_not_found"
    assert snapshot.devices[0].error_detail == "No BLE advertisement seen during the scan window."


def test_build_snapshot_requests_bluetooth_recovery_for_fatal_dbus_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    calls: list[list[str]] = []

    class Completed:
        def __init__(self) -> None:
            self.returncode = 0
            self.stderr = ""

    def fake_run(command: list[str], **_kwargs: object) -> Completed:
        calls.append(command)
        return Completed()

    def failing_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        _ = (device, adapter, timeout_seconds, scan_timeout_seconds)
        raise RuntimeError(
            "[org.freedesktop.DBus.Error.AccessDenied] Client tried to send a message "
            "other than Hello without being registered"
        )

    monkeypatch.setattr("bm_gateway.runtime.shutil.which", lambda _name: "/usr/bin/bluetoothctl")
    monkeypatch.setattr(
        "bm_gateway.bluetooth_recovery.shutil.which",
        lambda _name: f"/usr/bin/{_name}",
    )
    monkeypatch.setattr("bm_gateway.runtime.subprocess.run", fake_run)
    monkeypatch.setattr("bm_gateway.bluetooth_recovery.subprocess.run", fake_run)

    with pytest.raises(BluetoothRecoveryRequiredError):
        build_snapshot(config, devices, bm200_reader=failing_reader)

    assert calls == [
        ["bluetoothctl", "power", "on"],
        ["sudo", "-n", "systemctl", "restart", "bluetooth.service"],
    ]


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

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="charging",
            temperature=18.5,
        )

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)
    database_path = database_file_path(config, state_dir=tmp_path / "state")

    persist_snapshot(database_path, snapshot)

    counts = fetch_counts(database_path)
    assert counts["gateway_snapshots"] == 1
    assert counts["device_readings"] == 1
    assert counts["device_daily_rollups"] == 1


def test_build_snapshot_preserves_live_reader_rssi() -> None:
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

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="charging",
            temperature=18.5,
            rssi=-67,
        )

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)

    assert snapshot.devices[0].connected is True
    assert snapshot.devices[0].rssi == -67


def test_build_snapshot_uses_live_bm300_reader_when_enabled() -> None:
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

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM300Measurement:
        assert device.id == "bm300_van"
        assert adapter == "hci0"
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        return BM300Measurement(
            voltage=25.42,
            soc=83,
            status_code=0,
            state="normal",
            temperature=24.0,
            rssi=-61,
        )

    snapshot = build_snapshot(config, devices, bm300_reader=fake_reader)

    assert snapshot.devices_online == 1
    assert snapshot.devices[0].driver == "bm300pro"
    assert snapshot.devices[0].voltage == 25.42
    assert snapshot.devices[0].soc == 83
    assert snapshot.devices[0].state == "normal"
    assert snapshot.devices[0].temperature == 24.0
    assert snapshot.devices[0].rssi == -61


def test_build_snapshot_serializes_live_reads_with_cross_process_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(
        source_path=tmp_path / "gateway.toml",
        device_registry_path=tmp_path / "devices.toml",
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
    state_dir = tmp_path / "state"
    calls: list[tuple[Path | None, str]] = []

    @contextmanager
    def fake_lock(
        _config: AppConfig,
        *,
        operation: str,
        state_dir: Path | None = None,
        timeout_seconds: float = 600.0,
        retry_interval_seconds: float = 0.25,
    ) -> Iterator[dict[str, object]]:
        _ = (timeout_seconds, retry_interval_seconds)
        calls.append((state_dir, operation))
        yield {}

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM300Measurement:
        assert device.id == "bm300_van"
        assert adapter == "hci0"
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        return BM300Measurement(
            voltage=25.42,
            soc=83,
            status_code=0,
            state="normal",
            temperature=24.0,
            rssi=-61,
        )

    monkeypatch.setattr("bm_gateway.runtime.exclusive_bluetooth_operation", fake_lock)

    snapshot = build_snapshot(config, devices, bm300_reader=fake_reader, state_dir=state_dir)

    assert snapshot.devices_online == 1
    assert calls == [(state_dir, "live_poll:bm300_van")]


def test_build_snapshot_uses_bm200_driver_for_commercial_aliases() -> None:
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
            id="bm6_motorcycle",
            type="bm6",
            name="BM6 Motorcycle",
            mac="AA:BB:CC:DD:EE:03",
            enabled=True,
        )
    ]

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        assert device.type == "bm6"
        return BM200Measurement(
            voltage=12.9,
            soc=90,
            status_code=0,
            state="normal",
            temperature=19.0,
        )

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)

    assert snapshot.devices_online == 1
    assert snapshot.devices[0].type == "bm6"
    assert snapshot.devices[0].driver == "bm200"
    assert snapshot.devices[0].voltage == 12.9


def test_build_snapshot_uses_bm300_driver_for_commercial_aliases() -> None:
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
            id="bm7_bench",
            type="bm7",
            name="BM7 Bench",
            mac="E0:4E:7A:AF:9B:E8",
            enabled=True,
        )
    ]

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM300Measurement:
        assert device.type == "bm7"
        return BM300Measurement(
            voltage=14.4,
            soc=100,
            status_code=2,
            state="charging",
            temperature=18.0,
        )

    snapshot = build_snapshot(config, devices, bm300_reader=fake_reader)

    assert snapshot.devices_online == 1
    assert snapshot.devices[0].type == "bm7"
    assert snapshot.devices[0].driver == "bm300pro"
    assert snapshot.devices[0].state == "charging"


def test_build_snapshot_classifies_bm300_reader_errors() -> None:
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

    def failing_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM300Measurement:
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        raise BM300TimeoutError(f"{device.id}:{adapter}")

    snapshot = build_snapshot(config, devices, bm300_reader=failing_reader)

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].driver == "bm300pro"
    assert snapshot.devices[0].state == "error"
    assert snapshot.devices[0].error_code == "timeout"
    assert snapshot.devices[0].error_detail == "bm300_van:hci0"


def test_build_snapshot_marks_unknown_devices_unsupported_in_live_mode() -> None:
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
            id="unknown_van",
            type="unknown",
            name="Unknown Van",
            mac="AA:BB:CC:DD:EE:02",
            enabled=True,
        )
    ]

    snapshot = build_snapshot(config, devices)

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].state == "unsupported"
    assert snapshot.devices[0].error_code == "unsupported_device_type"


def test_build_snapshot_powers_on_adapter_before_live_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> None:
        calls.append(command)

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        assert device.id == "bm200_house"
        assert adapter == "hci0"
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        return BM200Measurement(voltage=12.73, soc=58, status_code=2, state="charging")

    monkeypatch.setattr("bm_gateway.runtime.shutil.which", lambda _name: "/usr/bin/bluetoothctl")
    monkeypatch.setattr("bm_gateway.runtime.subprocess.run", fake_run)

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)

    assert calls == [["bluetoothctl", "power", "on"]]
    assert snapshot.devices_online == 1


def test_build_snapshot_retries_after_device_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    calls: list[str] = []
    attempts = {"count": 0}

    def fake_run(command: list[str], **_kwargs: object) -> None:
        calls.append(" ".join(command))

    def fake_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        attempts["count"] += 1
        assert adapter == "hci0"
        assert timeout_seconds == 45.0
        assert scan_timeout_seconds == 15.0
        if attempts["count"] == 1:
            raise BleakDeviceNotFoundError(device.mac)
        return BM200Measurement(voltage=12.73, soc=58, status_code=2, state="charging")

    monkeypatch.setattr("bm_gateway.runtime.shutil.which", lambda _name: "/usr/bin/bluetoothctl")
    monkeypatch.setattr("bm_gateway.runtime.subprocess.run", fake_run)
    monkeypatch.setattr("bm_gateway.runtime.sleep", lambda _seconds: None)

    snapshot = build_snapshot(config, devices, bm200_reader=fake_reader)

    assert snapshot.devices_online == 1
    assert attempts["count"] == 2
    assert calls == [
        "bluetoothctl power on",
        "bluetoothctl scan off",
        "bluetoothctl power off",
        "bluetoothctl power on",
    ]


def test_recover_adapter_is_noop_without_bluetoothctl(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"run": False}

    def fake_run(*_args: object, **_kwargs: object) -> None:
        called["run"] = True

    monkeypatch.setattr("bm_gateway.runtime.shutil.which", lambda _name: None)
    monkeypatch.setattr("bm_gateway.runtime.subprocess.run", fake_run)

    recover_adapter("hci0")

    assert called["run"] is False
