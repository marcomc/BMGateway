"""Device registry support for BMGateway."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

VALID_DEVICE_TYPES = {"bm200", "bm300pro"}
MAC_ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
COMPACT_MAC_RE = re.compile(r"^[0-9A-F]{12}$")


@dataclass(frozen=True)
class Device:
    id: str
    type: str
    name: str
    mac: str
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "mac": self.mac,
            "enabled": self.enabled,
        }


def normalize_mac_address(value: str) -> str:
    raw = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    if COMPACT_MAC_RE.fullmatch(raw):
        return ":".join(raw[index : index + 2] for index in range(0, 12, 2))
    return value.strip().upper()


def load_device_registry(path: Path) -> list[Device]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    raw_devices = data.get("devices", [])
    if not isinstance(raw_devices, list):
        raise ValueError(f"Device registry {path} must define [[devices]] entries.")

    devices: list[Device] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            raise ValueError(f"Device registry {path} contains a non-table device entry.")
        devices.append(
            Device(
                id=str(item.get("id", "")).strip(),
                type=str(item.get("type", "")).strip(),
                name=str(item.get("name", "")).strip(),
                mac=normalize_mac_address(str(item.get("mac", ""))),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return devices


def write_device_registry(path: Path, devices: list[Device]) -> None:
    lines: list[str] = []
    for device in devices:
        lines.extend(
            [
                "[[devices]]",
                f'id = "{device.id}"',
                f'type = "{device.type}"',
                f'name = "{device.name}"',
                f'mac = "{device.mac}"',
                f"enabled = {'true' if device.enabled else 'false'}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def validate_devices(devices: list[Device]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_macs: set[str] = set()

    for device in devices:
        if not device.id:
            errors.append("device.id must not be empty")
        elif device.id in seen_ids:
            errors.append(f"duplicate device id: {device.id}")
        else:
            seen_ids.add(device.id)

        if not device.name:
            errors.append(f"device {device.id or '<unknown>'} name must not be empty")

        if device.type not in VALID_DEVICE_TYPES:
            errors.append(
                f"device {device.id or '<unknown>'} type must be one of "
                f"{', '.join(sorted(VALID_DEVICE_TYPES))}"
            )

        if not MAC_ADDRESS_RE.fullmatch(device.mac):
            errors.append(f"device {device.id or '<unknown>'} mac is invalid: {device.mac}")
        elif device.mac in seen_macs:
            errors.append(f"duplicate device mac: {device.mac}")
        else:
            seen_macs.add(device.mac)
    return errors
