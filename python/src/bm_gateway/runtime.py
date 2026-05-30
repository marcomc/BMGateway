"""Runtime support for BMGateway."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable, Sequence

from .bluetooth_lock import BluetoothOperationBusyError, exclusive_bluetooth_operation
from .bluetooth_recovery import is_fatal_bluetooth_error, require_bluetooth_recovery
from .config import AppConfig, GatewayConfig
from .device_registry import Device, device_driver_type
from .drivers.bm200 import (
    BleakDeviceNotFoundError,
    BM200Error,
    BM200Measurement,
    BM200ProtocolError,
    BM200TimeoutError,
    read_bm200_measurement,
)
from .drivers.bm300 import (
    BleakBM300DeviceNotFoundError,
    BM300Error,
    BM300Measurement,
    BM300ProtocolError,
    BM300TimeoutError,
    read_bm300_measurement,
)
from .models import DeviceReading, GatewaySnapshot
from .subprocess_runner import run_in_subprocess_with_timeout
from .system_alerts import collect_gateway_alerts

BM200Reader = Callable[[Device, str, float, float], BM200Measurement]
BM300Reader = Callable[[Device, str, float, float], BM300Measurement]
LIVE_DEVICE_TYPES = {"bm200", "bm300pro"}
DEFAULT_MISSING_DEVICE_SKIP_CYCLES = (1, 2, 4, 6)
DEFAULT_ALL_TIMEOUT_RECOVERY_CYCLES = 2


@dataclass
class _DeviceBackoffRecord:
    consecutive_not_found: int = 0
    skip_cycles_remaining: int = 0


class LiveDeviceBackoff:
    """Track short per-device skips after repeated missing advertisements."""

    def __init__(
        self,
        *,
        trigger_failures: int = 1,
        skip_cycle_sequence: Sequence[int] = DEFAULT_MISSING_DEVICE_SKIP_CYCLES,
    ) -> None:
        self._trigger_failures = max(1, trigger_failures)
        sequence = tuple(max(0, item) for item in skip_cycle_sequence)
        self._skip_cycle_sequence = sequence or (1,)
        self._records: dict[str, _DeviceBackoffRecord] = {}

    def should_skip(self, device_id: str) -> bool:
        record = self._records.get(device_id)
        if record is None or record.skip_cycles_remaining <= 0:
            return False
        record.skip_cycles_remaining -= 1
        return True

    def record_success(self, device_id: str) -> None:
        self._records.pop(device_id, None)

    def record_error(self, device_id: str, error_code: str | None) -> None:
        if error_code != "device_not_found":
            self._records.pop(device_id, None)
            return

        record = self._records.setdefault(device_id, _DeviceBackoffRecord())
        record.consecutive_not_found += 1
        if record.consecutive_not_found < self._trigger_failures:
            return

        sequence_index = min(
            record.consecutive_not_found - self._trigger_failures,
            len(self._skip_cycle_sequence) - 1,
        )
        record.skip_cycles_remaining = max(
            record.skip_cycles_remaining,
            self._skip_cycle_sequence[sequence_index],
        )


def snapshot_has_all_live_timeouts(snapshot: GatewaySnapshot) -> bool:
    live_readings = [
        reading
        for reading in snapshot.devices
        if reading.enabled and reading.driver in LIVE_DEVICE_TYPES
    ]
    return (
        bool(live_readings)
        and snapshot.devices_online == 0
        and all(reading.error_code == "timeout" for reading in live_readings)
    )


class LiveTimeoutRecoveryTracker:
    """Request host BLE recovery after consecutive all-device timeout cycles."""

    def __init__(
        self,
        *,
        consecutive_cycle_threshold: int = DEFAULT_ALL_TIMEOUT_RECOVERY_CYCLES,
    ) -> None:
        self._threshold = max(1, consecutive_cycle_threshold)
        self.consecutive_timeout_cycles = 0

    def record_snapshot(self, snapshot: GatewaySnapshot) -> bool:
        if snapshot_has_all_live_timeouts(snapshot):
            self.consecutive_timeout_cycles += 1
            return self.consecutive_timeout_cycles >= self._threshold
        self.consecutive_timeout_cycles = 0
        return False


def _active_adapter(config: AppConfig) -> str:
    return config.bluetooth.adapter if config.bluetooth.adapter != "auto" else "hci0"


def _generated_at() -> str:
    return datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def _build_fake_reading(device: Device, *, generated_at: str, adapter: str) -> DeviceReading:
    seed = sum(ord(char) for char in device.id + device.mac)
    voltage = round(12.0 + (seed % 90) / 100, 2)
    soc = min(40 + (seed % 55), 100)
    temperature = round(18.0 + (seed % 80) / 10, 1)
    rssi = -40 - (seed % 45)
    state = "normal" if device.enabled else "disabled"
    return DeviceReading(
        id=device.id,
        type=device.type,
        name=device.name,
        mac=device.mac,
        enabled=device.enabled,
        connected=device.enabled,
        voltage=voltage,
        soc=soc,
        temperature=temperature,
        rssi=rssi,
        state=state,
        error_code=None,
        error_detail=None,
        last_seen=generated_at,
        adapter=adapter,
        driver=device_driver_type(device.type),
        last_attempt=generated_at,
    )


def _build_disabled_reading(device: Device, *, generated_at: str, adapter: str) -> DeviceReading:
    return DeviceReading(
        id=device.id,
        type=device.type,
        name=device.name,
        mac=device.mac,
        enabled=device.enabled,
        connected=False,
        voltage=0.0,
        soc=0,
        temperature=None,
        rssi=None,
        state="disabled",
        error_code=None,
        error_detail=None,
        last_seen=generated_at,
        adapter=adapter,
        driver=device_driver_type(device.type),
        last_attempt=generated_at,
    )


def _build_unsupported_reading(device: Device, *, generated_at: str, adapter: str) -> DeviceReading:
    return DeviceReading(
        id=device.id,
        type=device.type,
        name=device.name,
        mac=device.mac,
        enabled=device.enabled,
        connected=False,
        voltage=0.0,
        soc=0,
        temperature=None,
        rssi=None,
        state="unsupported",
        error_code="unsupported_device_type",
        error_detail=device.type,
        last_seen=generated_at,
        adapter=adapter,
        driver=device_driver_type(device.type),
        last_attempt=generated_at,
    )


def _classify_live_error(error: Exception) -> tuple[str, str]:
    detail = str(error) or error.__class__.__name__
    if isinstance(error, BluetoothOperationBusyError):
        return "bluetooth_busy", detail
    if isinstance(error, BleakDeviceNotFoundError | BleakBM300DeviceNotFoundError):
        return "device_not_found", "No BLE advertisement seen during the scan window."
    if isinstance(error, BM200TimeoutError | BM300TimeoutError):
        return "timeout", detail
    if isinstance(error, BM200ProtocolError | BM300ProtocolError):
        return "protocol_error", detail
    if isinstance(error, BM200Error | BM300Error):
        return "driver_error", detail
    return "unexpected_error", detail


def _build_error_reading(
    device: Device,
    *,
    generated_at: str,
    adapter: str,
    error: Exception,
    last_seen: str = "",
) -> DeviceReading:
    error_code, error_detail = _classify_live_error(error)
    state = "offline" if error_code == "device_not_found" else "error"
    return DeviceReading(
        id=device.id,
        type=device.type,
        name=device.name,
        mac=device.mac,
        enabled=device.enabled,
        connected=False,
        voltage=0.0,
        soc=0,
        temperature=None,
        rssi=None,
        state=state,
        error_code=error_code,
        error_detail=error_detail,
        last_seen=last_seen,
        adapter=adapter,
        driver=device_driver_type(device.type),
        last_attempt=generated_at,
    )


def _read_live_bm200(
    device: Device,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
) -> BM200Measurement:
    return asyncio.run(
        read_bm200_measurement(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=timeout_seconds,
            scan_timeout_seconds=scan_timeout_seconds,
        )
    )


def _read_live_bm300(
    device: Device,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
) -> BM300Measurement:
    return asyncio.run(
        read_bm300_measurement(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=timeout_seconds,
            scan_timeout_seconds=scan_timeout_seconds,
        )
    )


def _live_hard_timeout_seconds(timeout_seconds: float) -> float:
    return max(timeout_seconds + 15.0, timeout_seconds * 1.5)


def _effective_live_hard_timeout_seconds(
    *, timeout_seconds: float, configured_hard_timeout_seconds: float
) -> float:
    if configured_hard_timeout_seconds > 0:
        return configured_hard_timeout_seconds
    return _live_hard_timeout_seconds(timeout_seconds)


def _read_live_bm200_isolated(
    device: Device,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    *,
    configured_hard_timeout_seconds: float = 0.0,
) -> BM200Measurement:
    hard_timeout_seconds = _effective_live_hard_timeout_seconds(
        timeout_seconds=timeout_seconds,
        configured_hard_timeout_seconds=configured_hard_timeout_seconds,
    )
    return run_in_subprocess_with_timeout(
        function=_read_live_bm200,
        args=(device, adapter, timeout_seconds, scan_timeout_seconds),
        timeout_seconds=hard_timeout_seconds,
        timeout_error=lambda: BM200TimeoutError(
            f"{device.mac} exceeded the {hard_timeout_seconds:.1f}s hard timeout."
        ),
    )


def _read_live_bm300_isolated(
    device: Device,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    *,
    configured_hard_timeout_seconds: float = 0.0,
) -> BM300Measurement:
    hard_timeout_seconds = _effective_live_hard_timeout_seconds(
        timeout_seconds=timeout_seconds,
        configured_hard_timeout_seconds=configured_hard_timeout_seconds,
    )
    return run_in_subprocess_with_timeout(
        function=_read_live_bm300,
        args=(device, adapter, timeout_seconds, scan_timeout_seconds),
        timeout_seconds=hard_timeout_seconds,
        timeout_error=lambda: BM300TimeoutError(
            f"{device.mac} exceeded the {hard_timeout_seconds:.1f}s hard timeout."
        ),
    )


def _ensure_adapter_ready(adapter: str) -> None:
    # Best-effort power-on before polling. This keeps the service resilient on
    # boards where BlueZ starts with the controller present but powered off.
    _ = adapter
    if shutil.which("bluetoothctl") is None:
        return
    subprocess.run(
        ["bluetoothctl", "power", "on"],
        check=False,
        capture_output=True,
        text=True,
    )


def recover_adapter(adapter: str) -> None:
    _ = adapter
    if shutil.which("bluetoothctl") is None:
        return
    for command in (
        ["bluetoothctl", "scan", "off"],
        ["bluetoothctl", "power", "off"],
        ["bluetoothctl", "power", "on"],
    ):
        subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        sleep(1)


def build_snapshot(
    config: AppConfig,
    devices: list[Device],
    *,
    bm200_reader: BM200Reader | None = None,
    bm300_reader: BM300Reader | None = None,
    state_dir: Path | None = None,
    last_successful_seen: dict[str, str] | None = None,
    device_backoff: LiveDeviceBackoff | None = None,
) -> GatewaySnapshot:
    generated_at = _generated_at()
    adapter = _active_adapter(config)
    readings: list[DeviceReading] = []
    previous_seen = last_successful_seen or {}
    bm200_live_reader: BM200Reader
    if bm200_reader is None:
        configured_live_hard_timeout_seconds = float(config.bluetooth.live_hard_timeout_seconds)

        def bm200_live_reader(
            device: Device,
            adapter: str,
            timeout_seconds: float,
            scan_timeout_seconds: float,
        ) -> BM200Measurement:
            return _read_live_bm200_isolated(
                device,
                adapter,
                timeout_seconds,
                scan_timeout_seconds,
                configured_hard_timeout_seconds=configured_live_hard_timeout_seconds,
            )

    else:
        bm200_live_reader = bm200_reader
    bm300_live_reader: BM300Reader
    if bm300_reader is None:
        configured_live_hard_timeout_seconds = float(config.bluetooth.live_hard_timeout_seconds)

        def bm300_live_reader(
            device: Device,
            adapter: str,
            timeout_seconds: float,
            scan_timeout_seconds: float,
        ) -> BM300Measurement:
            return _read_live_bm300_isolated(
                device,
                adapter,
                timeout_seconds,
                scan_timeout_seconds,
                configured_hard_timeout_seconds=configured_live_hard_timeout_seconds,
            )

    else:
        bm300_live_reader = bm300_reader
    if config.gateway.reader_mode == "live" and any(
        device.enabled and device_driver_type(device.type) in LIVE_DEVICE_TYPES
        for device in devices
    ):
        _ensure_adapter_ready(adapter)

    for device in devices:
        if not device.enabled:
            readings.append(
                _build_disabled_reading(device, generated_at=generated_at, adapter=adapter)
            )
            continue

        if config.gateway.reader_mode == "fake":
            readings.append(_build_fake_reading(device, generated_at=generated_at, adapter=adapter))
            continue

        live_reader: Callable[[Device, str, float, float], BM200Measurement | BM300Measurement]
        driver_type = device_driver_type(device.type)
        if driver_type == "bm200":
            live_reader = bm200_live_reader
        elif driver_type == "bm300pro":
            live_reader = bm300_live_reader
        else:
            readings.append(
                _build_unsupported_reading(device, generated_at=generated_at, adapter=adapter)
            )
            continue

        if device_backoff is not None and device_backoff.should_skip(device.id):
            error: Exception
            if driver_type == "bm300pro":
                error = BleakBM300DeviceNotFoundError(device.mac)
            else:
                error = BleakDeviceNotFoundError(device.mac)
            readings.append(
                _build_error_reading(
                    device,
                    generated_at=generated_at,
                    adapter=adapter,
                    error=error,
                    last_seen=previous_seen.get(device.id, ""),
                )
            )
            continue

        try:
            with exclusive_bluetooth_operation(
                config,
                state_dir=state_dir,
                operation=f"live_poll:{device.id}",
            ):
                try:
                    measurement = live_reader(
                        device,
                        adapter,
                        float(config.bluetooth.connect_timeout_seconds),
                        float(config.bluetooth.scan_timeout_seconds),
                    )
                except (
                    BleakDeviceNotFoundError,
                    BleakBM300DeviceNotFoundError,
                ):
                    if device_backoff is not None:
                        raise
                    recover_adapter(adapter)
                    measurement = live_reader(
                        device,
                        adapter,
                        float(config.bluetooth.connect_timeout_seconds),
                        float(config.bluetooth.scan_timeout_seconds),
                    )
                except (BM200TimeoutError, BM300TimeoutError):
                    recover_adapter(adapter)
                    measurement = live_reader(
                        device,
                        adapter,
                        float(config.bluetooth.connect_timeout_seconds),
                        float(config.bluetooth.scan_timeout_seconds),
                    )
        except Exception as error:
            if is_fatal_bluetooth_error(error):
                require_bluetooth_recovery(error)
            readings.append(
                _build_error_reading(
                    device,
                    generated_at=generated_at,
                    adapter=adapter,
                    error=error,
                    last_seen=previous_seen.get(device.id, ""),
                )
            )
            if device_backoff is not None:
                error_code, _error_detail = _classify_live_error(error)
                device_backoff.record_error(device.id, error_code)
            continue

        if device_backoff is not None:
            device_backoff.record_success(device.id)
        readings.append(
            DeviceReading(
                id=device.id,
                type=device.type,
                name=device.name,
                mac=device.mac,
                enabled=device.enabled,
                connected=True,
                voltage=measurement.voltage,
                soc=measurement.soc,
                temperature=measurement.temperature,
                rssi=measurement.rssi,
                state=measurement.state,
                error_code=None,
                error_detail=None,
                last_seen=generated_at,
                adapter=adapter,
                driver=driver_type,
                last_attempt=generated_at,
            )
        )

    return GatewaySnapshot(
        generated_at=generated_at,
        gateway_name=config.gateway.name,
        active_adapter=adapter,
        mqtt_enabled=config.mqtt.enabled,
        mqtt_connected=False,
        devices_total=len(readings),
        devices_online=sum(1 for device in readings if device.connected),
        poll_interval_seconds=config.gateway.poll_interval_seconds,
        devices=readings,
        alerts=collect_gateway_alerts(configured_adapter=adapter),
    )


def build_fake_snapshot(config: AppConfig, devices: list[Device]) -> GatewaySnapshot:
    fake_config = AppConfig(
        source_path=config.source_path,
        device_registry_path=config.device_registry_path,
        gateway=GatewayConfig(
            name=config.gateway.name,
            timezone=config.gateway.timezone,
            poll_interval_seconds=config.gateway.poll_interval_seconds,
            device_registry=config.gateway.device_registry,
            data_dir=config.gateway.data_dir,
            reader_mode="fake",
        ),
        bluetooth=config.bluetooth,
        mqtt=config.mqtt,
        home_assistant=config.home_assistant,
        web=config.web,
        retention=config.retention,
        usb_otg=config.usb_otg,
        archive_sync=config.archive_sync,
        self_healing=config.self_healing,
        verbose=config.verbose,
    )
    return build_snapshot(fake_config, devices)


def iterations_from_flags(*, once: bool, iterations: int | None) -> int | None:
    if once:
        return 1
    return iterations


def state_file_path(config: AppConfig, *, state_dir: Path | None = None) -> Path:
    base_dir = (
        state_dir
        if state_dir is not None
        else (config.source_path.parent / config.gateway.data_dir)
    )
    return base_dir / "runtime" / "latest_snapshot.json"


def database_file_path(config: AppConfig, *, state_dir: Path | None = None) -> Path:
    base_dir = (
        state_dir
        if state_dir is not None
        else (config.source_path.parent / config.gateway.data_dir)
    )
    return base_dir / "runtime" / "gateway.db"


def sleep_interval(seconds: int) -> None:
    sleep(seconds)
