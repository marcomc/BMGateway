from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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
from bm_gateway.models import DeviceReading, GatewaySnapshot
from bm_gateway.runtime import (
    BACKOFF_DEVICE_DETAIL,
    LiveDeviceBackoff,
    LiveTimeoutRecoveryTracker,
    _effective_live_hard_timeout_seconds,
    build_snapshot,
    database_file_path,
    recover_adapter,
    snapshot_needs_timeout_recovery,
)
from bm_gateway.state_store import fetch_counts, persist_snapshot
from bm_gateway.system_alerts import GatewayAlert


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


def test_build_snapshot_uses_hard_timeout_runner_for_default_bm200_reader(
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
    captured: dict[str, Any] = {}

    def fake_run_in_subprocess_with_timeout(
        *,
        function: object,
        args: tuple[object, ...],
        timeout_seconds: float,
        timeout_error: object,
    ) -> BM200Measurement:
        _ = timeout_error
        captured["function"] = function
        captured["args"] = args
        captured["timeout_seconds"] = timeout_seconds
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="charging",
            temperature=23.0,
        )

    monkeypatch.setattr(
        "bm_gateway.runtime.run_in_subprocess_with_timeout",
        fake_run_in_subprocess_with_timeout,
    )

    snapshot = build_snapshot(config, devices)

    assert snapshot.devices_online == 1
    assert captured["function"].__name__ == "_read_live_bm200"
    assert captured["args"] == (devices[0], "hci0", 45.0, 15.0)
    assert captured["timeout_seconds"] == 67.5


def test_build_snapshot_uses_configured_bm200_hard_timeout_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="live"),
        bluetooth=BluetoothConfig(adapter="hci0", live_hard_timeout_seconds=90),
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
    captured: dict[str, Any] = {}

    def fake_run_in_subprocess_with_timeout(
        *,
        function: object,
        args: tuple[object, ...],
        timeout_seconds: float,
        timeout_error: object,
    ) -> BM200Measurement:
        _ = (function, args, timeout_error)
        captured["timeout_seconds"] = timeout_seconds
        return BM200Measurement(
            voltage=12.73,
            soc=58,
            status_code=2,
            state="charging",
            temperature=23.0,
        )

    monkeypatch.setattr(
        "bm_gateway.runtime.run_in_subprocess_with_timeout",
        fake_run_in_subprocess_with_timeout,
    )

    snapshot = build_snapshot(config, devices)

    assert snapshot.devices_online == 1
    assert captured["timeout_seconds"] == 90.0


def test_build_snapshot_includes_gateway_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="fake"),
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
    monkeypatch.setattr(
        "bm_gateway.runtime.collect_gateway_alerts",
        lambda **_kwargs: [
            GatewayAlert(
                code="bluetooth_soft_blocked",
                severity="error",
                runbook="troubleshooting-bluetooth.md",
                context={"controller": "hci0"},
            )
        ],
    )

    snapshot = build_snapshot(config, devices)

    assert [alert.code for alert in snapshot.alerts] == ["bluetooth_soft_blocked"]


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

    snapshot = build_snapshot(
        config,
        devices,
        bm200_reader=failing_reader,
        last_successful_seen={"bm200_house": "2026-05-10T20:22:09+02:00"},
    )

    assert snapshot.devices_online == 0
    assert snapshot.devices[0].state == "offline"
    assert snapshot.devices[0].error_code == "device_not_found"
    assert snapshot.devices[0].error_detail == "No BLE advertisement seen during the scan window."
    assert snapshot.devices[0].last_seen == "2026-05-10T20:22:09+02:00"
    assert snapshot.devices[0].last_attempt
    assert snapshot.devices[0].last_attempt != snapshot.devices[0].last_seen


def test_build_snapshot_skips_missing_device_after_not_found_backoff() -> None:
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
            id="spare_nlp20",
            type="bm200",
            name="Spare NLP20",
            mac="AA:BB:CC:DD:EE:01",
            enabled=True,
        )
    ]
    backoff = LiveDeviceBackoff(skip_cycle_sequence=(1,))
    attempts = {"count": 0}

    def missing_reader(
        device: Device,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> BM200Measurement:
        _ = (adapter, timeout_seconds, scan_timeout_seconds)
        attempts["count"] += 1
        raise BleakDeviceNotFoundError(device.mac)

    first_snapshot = build_snapshot(
        config,
        devices,
        bm200_reader=missing_reader,
        device_backoff=backoff,
        last_successful_seen={"spare_nlp20": "2026-05-27T05:29:22+02:00"},
    )
    second_snapshot = build_snapshot(
        config,
        devices,
        bm200_reader=missing_reader,
        device_backoff=backoff,
        last_successful_seen={"spare_nlp20": "2026-05-27T05:29:22+02:00"},
    )

    assert attempts["count"] == 1
    assert first_snapshot.devices[0].error_code == "device_not_found"
    assert first_snapshot.devices[0].error_detail == (
        "No BLE advertisement seen during the scan window."
    )
    assert second_snapshot.devices[0].error_code == "device_not_found"
    assert second_snapshot.devices[0].error_detail == (
        "Skipped BLE poll after repeated missing advertisements."
    )
    assert second_snapshot.devices[0].last_seen == "2026-05-27T05:29:22+02:00"


def test_live_device_backoff_resets_after_success() -> None:
    backoff = LiveDeviceBackoff(skip_cycle_sequence=(1,))

    backoff.record_error("spare_nlp20", "device_not_found")
    assert backoff.should_skip("spare_nlp20") is True
    assert backoff.should_skip("spare_nlp20") is False

    backoff.record_success("spare_nlp20")
    assert backoff.should_skip("spare_nlp20") is False


def _snapshot_with_readings(readings: list[DeviceReading]) -> GatewaySnapshot:
    return GatewaySnapshot(
        generated_at="2026-05-30T18:00:00+02:00",
        gateway_name="BMGateway",
        active_adapter="hci0",
        mqtt_enabled=False,
        mqtt_connected=False,
        devices_total=len(readings),
        devices_online=sum(1 for reading in readings if reading.connected),
        poll_interval_seconds=600,
        devices=readings,
    )


def _reading(
    device_id: str,
    *,
    connected: bool,
    error_code: str | None,
    error_detail: str | None = None,
    driver: str = "bm200",
    enabled: bool = True,
) -> DeviceReading:
    return DeviceReading(
        id=device_id,
        type=driver,
        name=device_id,
        mac="AA:BB:CC:DD:EE:01",
        enabled=enabled,
        connected=connected,
        voltage=12.7 if connected else 0.0,
        soc=70 if connected else 0,
        temperature=None,
        rssi=-60 if connected else None,
        state="normal" if connected else "error",
        error_code=error_code,
        error_detail=error_detail if error_detail is not None else error_code,
        last_seen="2026-05-30T18:00:00+02:00",
        adapter="hci0",
        driver=driver,
        last_attempt="2026-05-30T18:00:00+02:00",
    )


def test_live_timeout_recovery_tracker_counts_mixed_fleet_unreachable_cycles() -> None:
    all_real_failures_snapshot = _snapshot_with_readings(
        [
            _reading("bm200_house", connected=False, error_code="timeout"),
            _reading(
                "bm300_van",
                connected=False,
                error_code="device_not_found",
                error_detail="No BLE advertisement seen during the scan window.",
                driver="bm300pro",
            ),
        ]
    )
    real_failure_with_backoff_skip_snapshot = _snapshot_with_readings(
        [
            _reading(
                "bm200_house",
                connected=False,
                error_code="timeout",
            ),
            _reading(
                "spare_nlp20",
                connected=False,
                error_code="device_not_found",
                error_detail="Skipped BLE poll after repeated missing advertisements.",
            ),
        ]
    )
    all_backoff_skip_snapshot = _snapshot_with_readings(
        [
            _reading(
                "bm200_house",
                connected=False,
                error_code="device_not_found",
                error_detail=BACKOFF_DEVICE_DETAIL,
            ),
            _reading(
                "spare_nlp20",
                connected=False,
                error_code="device_not_found",
                error_detail=BACKOFF_DEVICE_DETAIL,
            ),
        ]
    )
    one_missing_while_others_online_snapshot = _snapshot_with_readings(
        [
            _reading("spare_nlp5", connected=True, error_code=None),
            _reading("spare_nlp20", connected=False, error_code="device_not_found"),
        ]
    )

    assert snapshot_needs_timeout_recovery(all_real_failures_snapshot) is True
    assert snapshot_needs_timeout_recovery(real_failure_with_backoff_skip_snapshot) is False
    assert snapshot_needs_timeout_recovery(all_backoff_skip_snapshot) is False
    assert snapshot_needs_timeout_recovery(one_missing_while_others_online_snapshot) is False

    tracker = LiveTimeoutRecoveryTracker(consecutive_cycle_threshold=2)
    assert tracker.record_snapshot(all_real_failures_snapshot) is False
    assert tracker.record_snapshot(real_failure_with_backoff_skip_snapshot) is True
    assert tracker.consecutive_timeout_cycles == 2

    backoff_tracker = LiveTimeoutRecoveryTracker(consecutive_cycle_threshold=2)
    assert backoff_tracker.record_snapshot(all_backoff_skip_snapshot) is False
    assert backoff_tracker.record_snapshot(all_backoff_skip_snapshot) is True
    assert backoff_tracker.consecutive_recovery_cycles == 2


def test_live_timeout_recovery_tracker_requests_recovery_after_threshold() -> None:
    tracker = LiveTimeoutRecoveryTracker(consecutive_cycle_threshold=2)
    timeout_snapshot = _snapshot_with_readings(
        [_reading("bm200_house", connected=False, error_code="timeout")]
    )
    success_snapshot = _snapshot_with_readings(
        [_reading("bm200_house", connected=True, error_code=None)]
    )
    non_backoff_failure_snapshot = _snapshot_with_readings(
        [_reading("bm200_house", connected=False, error_code="protocol_error")]
    )

    assert tracker.record_snapshot(timeout_snapshot) is False
    assert tracker.record_snapshot(timeout_snapshot) is True
    assert tracker.record_snapshot(success_snapshot) is False
    assert tracker.consecutive_timeout_cycles == 0
    assert tracker.consecutive_backoff_only_cycles == 0
    assert tracker.record_snapshot(timeout_snapshot) is False
    assert tracker.record_snapshot(non_backoff_failure_snapshot) is False
    assert tracker.consecutive_timeout_cycles == 0


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
    assert counts["device_samples"] == 1
    assert counts["device_readings"] == 0
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


def test_build_snapshot_uses_hard_timeout_runner_for_default_bm300_reader(
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
            id="bm300_van",
            type="bm300pro",
            name="BM300 Van",
            mac="AA:BB:CC:DD:EE:02",
            enabled=True,
        )
    ]
    captured: dict[str, Any] = {}

    def fake_run_in_subprocess_with_timeout(
        *,
        function: object,
        args: tuple[object, ...],
        timeout_seconds: float,
        timeout_error: object,
    ) -> BM300Measurement:
        _ = timeout_error
        captured["function"] = function
        captured["args"] = args
        captured["timeout_seconds"] = timeout_seconds
        return BM300Measurement(
            voltage=25.42,
            soc=83,
            status_code=0,
            state="normal",
            temperature=24.0,
            rssi=-61,
        )

    monkeypatch.setattr(
        "bm_gateway.runtime.run_in_subprocess_with_timeout",
        fake_run_in_subprocess_with_timeout,
    )

    snapshot = build_snapshot(config, devices)

    assert snapshot.devices_online == 1
    assert captured["function"].__name__ == "_read_live_bm300"
    assert captured["args"] == (devices[0], "hci0", 45.0, 15.0)
    assert captured["timeout_seconds"] == 67.5


def test_build_snapshot_uses_configured_bm300_hard_timeout_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        source_path=Path("/tmp/gateway.toml"),
        device_registry_path=Path("/tmp/devices.toml"),
        gateway=GatewayConfig(reader_mode="live"),
        bluetooth=BluetoothConfig(adapter="hci0", live_hard_timeout_seconds=120),
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
    captured: dict[str, Any] = {}

    def fake_run_in_subprocess_with_timeout(
        *,
        function: object,
        args: tuple[object, ...],
        timeout_seconds: float,
        timeout_error: object,
    ) -> BM300Measurement:
        _ = (function, args, timeout_error)
        captured["timeout_seconds"] = timeout_seconds
        return BM300Measurement(
            voltage=25.42,
            soc=83,
            status_code=0,
            state="normal",
            temperature=24.0,
            rssi=-61,
        )

    monkeypatch.setattr(
        "bm_gateway.runtime.run_in_subprocess_with_timeout",
        fake_run_in_subprocess_with_timeout,
    )

    snapshot = build_snapshot(config, devices)

    assert snapshot.devices_online == 1
    assert captured["timeout_seconds"] == 120.0


def test_effective_bm300_live_hard_timeout_uses_override_when_present() -> None:
    assert (
        _effective_live_hard_timeout_seconds(
            timeout_seconds=45.0,
            configured_hard_timeout_seconds=120.0,
        )
        == 120.0
    )
    assert (
        _effective_live_hard_timeout_seconds(
            timeout_seconds=45.0,
            configured_hard_timeout_seconds=0.0,
        )
        == 67.5
    )


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
            mac="00:00:5E:00:53:03",
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
    monkeypatch.setattr("bm_gateway.runtime.collect_gateway_alerts", lambda **_kwargs: [])

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
    monkeypatch.setattr("bm_gateway.runtime.collect_gateway_alerts", lambda **_kwargs: [])

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
