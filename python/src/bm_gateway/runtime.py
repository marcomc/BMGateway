"""Runtime support for BMGateway."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable

from .config import AppConfig, GatewayConfig
from .device_registry import Device
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

BM200Reader = Callable[[Device, str, float, float], BM200Measurement]
BM300Reader = Callable[[Device, str, float, float], BM300Measurement]
LIVE_DEVICE_TYPES = {"bm200", "bm300pro"}


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
        driver=device.type,
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
        driver=device.type,
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
        driver=device.type,
    )


def _classify_live_error(error: Exception) -> tuple[str, str]:
    detail = str(error) or error.__class__.__name__
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
        last_seen=generated_at,
        adapter=adapter,
        driver=device.type,
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
) -> GatewaySnapshot:
    generated_at = _generated_at()
    adapter = _active_adapter(config)
    readings: list[DeviceReading] = []
    bm200_live_reader = bm200_reader or _read_live_bm200
    bm300_live_reader = bm300_reader or _read_live_bm300
    if config.gateway.reader_mode == "live" and any(
        device.enabled and device.type in LIVE_DEVICE_TYPES for device in devices
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
        if device.type == "bm200":
            live_reader = bm200_live_reader
        elif device.type == "bm300pro":
            live_reader = bm300_live_reader
        else:
            readings.append(
                _build_unsupported_reading(device, generated_at=generated_at, adapter=adapter)
            )
            continue

        try:
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
                BM200TimeoutError,
                BM300TimeoutError,
            ):
                recover_adapter(adapter)
                measurement = live_reader(
                    device,
                    adapter,
                    float(config.bluetooth.connect_timeout_seconds),
                    float(config.bluetooth.scan_timeout_seconds),
                )
        except Exception as error:
            readings.append(
                _build_error_reading(
                    device,
                    generated_at=generated_at,
                    adapter=adapter,
                    error=error,
                )
            )
            continue

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
                driver=device.type,
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
