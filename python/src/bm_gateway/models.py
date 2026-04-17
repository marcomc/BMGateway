"""Runtime models for BMGateway."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceReading:
    id: str
    type: str
    name: str
    mac: str
    enabled: bool
    connected: bool
    voltage: float
    soc: int
    temperature: float
    rssi: int
    state: str
    last_seen: str
    adapter: str
    driver: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "mac": self.mac,
            "enabled": self.enabled,
            "connected": self.connected,
            "voltage": self.voltage,
            "soc": self.soc,
            "temperature": self.temperature,
            "rssi": self.rssi,
            "state": self.state,
            "last_seen": self.last_seen,
            "adapter": self.adapter,
            "driver": self.driver,
        }


@dataclass(frozen=True)
class GatewaySnapshot:
    generated_at: str
    gateway_name: str
    active_adapter: str
    mqtt_enabled: bool
    mqtt_connected: bool
    devices_total: int
    devices_online: int
    poll_interval_seconds: int
    devices: list[DeviceReading]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "gateway_name": self.gateway_name,
            "active_adapter": self.active_adapter,
            "mqtt_enabled": self.mqtt_enabled,
            "mqtt_connected": self.mqtt_connected,
            "devices_total": self.devices_total,
            "devices_online": self.devices_online,
            "poll_interval_seconds": self.poll_interval_seconds,
            "devices": [device.to_dict() for device in self.devices],
        }
