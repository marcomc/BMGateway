"""Runtime support for BMGateway."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import sleep

from .config import AppConfig
from .device_registry import Device
from .models import DeviceReading, GatewaySnapshot


def build_fake_snapshot(config: AppConfig, devices: list[Device]) -> GatewaySnapshot:
    generated_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    adapter = config.bluetooth.adapter if config.bluetooth.adapter != "auto" else "hci0"
    readings: list[DeviceReading] = []

    for _index, device in enumerate(devices, start=1):
        seed = sum(ord(char) for char in device.id + device.mac)
        voltage = round(12.0 + (seed % 90) / 100, 2)
        soc = 40 + (seed % 55)
        temperature = round(18.0 + (seed % 80) / 10, 1)
        rssi = -40 - (seed % 45)
        state = "normal" if device.enabled else "disabled"
        readings.append(
            DeviceReading(
                id=device.id,
                type=device.type,
                name=device.name,
                mac=device.mac,
                enabled=device.enabled,
                connected=device.enabled,
                voltage=voltage,
                soc=min(soc, 100),
                temperature=temperature,
                rssi=rssi,
                state=state,
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
