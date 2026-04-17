"""Runtime support for BMGateway."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable

from .config import AppConfig, GatewayConfig
from .device_registry import Device
from .drivers.bm200 import BM200Measurement, read_bm200_measurement
from .models import DeviceReading, GatewaySnapshot

BM200Reader = Callable[[Device, str], BM200Measurement]


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
        last_seen=generated_at,
        adapter=adapter,
        driver=device.type,
    )


def _build_error_reading(device: Device, *, generated_at: str, adapter: str) -> DeviceReading:
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
        state="error",
        last_seen=generated_at,
        adapter=adapter,
        driver=device.type,
    )


def _read_live_bm200(device: Device, adapter: str) -> BM200Measurement:
    return asyncio.run(
        read_bm200_measurement(
            address=device.mac,
            adapter=adapter,
            timeout_seconds=10,
        )
    )


def build_snapshot(
    config: AppConfig,
    devices: list[Device],
    *,
    bm200_reader: BM200Reader | None = None,
) -> GatewaySnapshot:
    generated_at = _generated_at()
    adapter = _active_adapter(config)
    readings: list[DeviceReading] = []
    live_reader = bm200_reader or _read_live_bm200

    for device in devices:
        if not device.enabled:
            readings.append(
                _build_disabled_reading(device, generated_at=generated_at, adapter=adapter)
            )
            continue

        if config.gateway.reader_mode == "fake":
            readings.append(_build_fake_reading(device, generated_at=generated_at, adapter=adapter))
            continue

        if device.type != "bm200":
            readings.append(
                _build_unsupported_reading(device, generated_at=generated_at, adapter=adapter)
            )
            continue

        try:
            measurement = live_reader(device, adapter)
        except Exception:
            readings.append(
                _build_error_reading(device, generated_at=generated_at, adapter=adapter)
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
                temperature=None,
                rssi=None,
                state=measurement.state,
                last_seen=generated_at,
                adapter=adapter,
                driver="bm200",
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


def sleep_interval(seconds: int) -> None:
    sleep(seconds)
