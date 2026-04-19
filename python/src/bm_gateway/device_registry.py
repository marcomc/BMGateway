"""Device registry support for BMGateway."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

VALID_DEVICE_TYPES = {"bm200", "bm300pro"}
MAC_ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
COMPACT_MAC_RE = re.compile(r"^[0-9A-F]{12}$")
BATTERY_FAMILIES = {
    "lead_acid": "Lead-Acid Battery",
    "lithium": "Lithium Battery",
}
LEAD_ACID_PROFILES = {
    "regular_lead_acid": "Regular lead-acid battery",
    "agm": "AGM Battery",
    "efb": "EFB Battery",
    "gel": "GEL Battery",
    "custom": "Custom Battery",
}
LITHIUM_PROFILES = {
    "lithium": "Lithium Battery",
    "custom": "Custom Battery",
}
CUSTOM_SOC_MODES = {
    "intelligent_algorithm": "Intelligent power algorithm",
    "voltage_corresponding_power": "Voltage corresponding to power",
}
ICON_CATALOG = {
    "battery_monitor": "Battery Monitor",
    "car_12v": "Car (12V)",
    "motorcycle_12v": "Motorcycle (12V)",
    "lead_acid_battery": "Lead-Acid Battery",
    "agm_battery": "AGM Battery",
    "efb_battery": "EFB Battery",
    "gel_battery": "GEL Battery",
    "lithium_battery": "Lithium Battery",
    "custom_battery": "Custom Battery",
}
DEFAULT_CUSTOM_CURVE = (
    (100, 12.90),
    (90, 12.80),
    (80, 12.70),
    (70, 12.60),
    (60, 12.50),
    (50, 12.40),
    (40, 12.30),
    (30, 12.20),
    (20, 12.10),
    (10, 12.00),
    (0, 11.90),
)


def _toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


@dataclass(frozen=True)
class Device:
    id: str
    type: str
    name: str
    mac: str
    enabled: bool = True
    battery_family: str = "lead_acid"
    battery_profile: str = "regular_lead_acid"
    custom_soc_mode: str = "intelligent_algorithm"
    custom_voltage_curve: tuple[tuple[int, float], ...] = DEFAULT_CUSTOM_CURVE
    icon_key: str = "battery_monitor"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "mac": self.mac,
            "enabled": self.enabled,
            "icon_key": self.icon_key,
            "icon_label": icon_label(self.icon_key),
            "battery": {
                "family": self.battery_family,
                "family_label": battery_family_label(self.battery_family),
                "profile": self.battery_profile,
                "profile_label": battery_profile_label(
                    family=self.battery_family,
                    profile=self.battery_profile,
                ),
                "custom_soc_mode": self.custom_soc_mode,
                "custom_soc_mode_label": CUSTOM_SOC_MODES.get(
                    self.custom_soc_mode,
                    self.custom_soc_mode.replace("_", " ").title(),
                ),
                "custom_voltage_curve": [
                    {"percent": percent, "voltage": voltage}
                    for percent, voltage in self.custom_voltage_curve
                ],
            },
        }


def battery_family_label(family: str) -> str:
    return BATTERY_FAMILIES.get(family, family.replace("_", " ").title())


def battery_profile_label(*, family: str, profile: str) -> str:
    options = LEAD_ACID_PROFILES if family == "lead_acid" else LITHIUM_PROFILES
    return options.get(profile, profile.replace("_", " ").title())


def icon_label(icon_key: str) -> str:
    return ICON_CATALOG.get(icon_key, icon_key.replace("_", " ").title())


def default_battery_family(device_type: str) -> str:
    if device_type == "bm300pro":
        return "lithium"
    return "lead_acid"


def default_battery_profile(device_type: str, family: str) -> str:
    if family == "lithium":
        return "lithium"
    if device_type == "bm300pro" and family == "lead_acid":
        return "regular_lead_acid"
    return "regular_lead_acid"


def default_icon_key(*, battery_family: str, battery_profile: str) -> str:
    if battery_profile == "agm":
        return "agm_battery"
    if battery_profile == "efb":
        return "efb_battery"
    if battery_profile == "gel":
        return "gel_battery"
    if battery_profile == "custom":
        return "custom_battery"
    if battery_family == "lithium":
        return "lithium_battery"
    if battery_family == "lead_acid":
        return "lead_acid_battery"
    return "battery_monitor"


def _parse_custom_voltage_curve(
    raw_curve: object,
) -> tuple[tuple[int, float], ...]:
    if not isinstance(raw_curve, list):
        return DEFAULT_CUSTOM_CURVE
    rows: list[tuple[int, float]] = []
    for item in raw_curve:
        if not isinstance(item, dict):
            continue
        percent = int(item.get("percent", 0))
        voltage = float(item.get("voltage", 0.0))
        rows.append((percent, voltage))
    if not rows:
        return DEFAULT_CUSTOM_CURVE
    return tuple(sorted(rows, key=lambda row: row[0], reverse=True))


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
        device_type = str(item.get("type", "")).strip()
        battery_table = item.get("battery", {})
        if not isinstance(battery_table, dict):
            raise ValueError(f"Device registry {path} contains an invalid battery table.")
        battery_family = str(
            battery_table.get("family", default_battery_family(device_type))
        ).strip()
        battery_profile = str(
            battery_table.get(
                "profile",
                default_battery_profile(device_type, battery_family),
            )
        ).strip()
        custom_soc_mode = str(battery_table.get("custom_soc_mode", "intelligent_algorithm")).strip()
        devices.append(
            Device(
                id=str(item.get("id", "")).strip(),
                type=device_type,
                name=str(item.get("name", "")).strip(),
                mac=normalize_mac_address(str(item.get("mac", ""))),
                enabled=bool(item.get("enabled", True)),
                battery_family=battery_family,
                battery_profile=battery_profile,
                custom_soc_mode=custom_soc_mode,
                custom_voltage_curve=_parse_custom_voltage_curve(
                    battery_table.get("custom_voltage_curve", [])
                ),
                icon_key=str(
                    item.get(
                        "icon_key",
                        default_icon_key(
                            battery_family=battery_family,
                            battery_profile=battery_profile,
                        ),
                    )
                ).strip(),
            )
        )
    return devices


def write_device_registry(path: Path, devices: list[Device]) -> None:
    lines: list[str] = []
    for device in devices:
        lines.extend(
            [
                "[[devices]]",
                f"id = {_toml_string(device.id)}",
                f"type = {_toml_string(device.type)}",
                f"name = {_toml_string(device.name)}",
                f"mac = {_toml_string(device.mac)}",
                f"enabled = {'true' if device.enabled else 'false'}",
                f"icon_key = {_toml_string(device.icon_key)}",
                "[devices.battery]",
                f"family = {_toml_string(device.battery_family)}",
                f"profile = {_toml_string(device.battery_profile)}",
                f"custom_soc_mode = {_toml_string(device.custom_soc_mode)}",
                "",
            ]
        )
        for percent, voltage in device.custom_voltage_curve:
            lines.extend(
                [
                    "[[devices.battery.custom_voltage_curve]]",
                    f"percent = {percent}",
                    f"voltage = {voltage:.2f}",
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

        if device.battery_family not in BATTERY_FAMILIES:
            errors.append(
                f"device {device.id or '<unknown>'} battery.family must be one of "
                f"{', '.join(sorted(BATTERY_FAMILIES))}"
            )

        valid_profiles = (
            LEAD_ACID_PROFILES if device.battery_family == "lead_acid" else LITHIUM_PROFILES
        )
        if device.battery_profile not in valid_profiles:
            errors.append(
                f"device {device.id or '<unknown>'} battery.profile must be one of "
                f"{', '.join(sorted(valid_profiles))}"
            )

        if device.custom_soc_mode not in CUSTOM_SOC_MODES:
            errors.append(
                f"device {device.id or '<unknown>'} battery.custom_soc_mode must be one of "
                f"{', '.join(sorted(CUSTOM_SOC_MODES))}"
            )

        if device.icon_key not in ICON_CATALOG:
            errors.append(
                f"device {device.id or '<unknown>'} icon key must be one of "
                f"{', '.join(sorted(ICON_CATALOG))}"
            )

        if device.battery_profile == "custom" and (
            device.custom_soc_mode == "voltage_corresponding_power"
        ):
            curve_rows = list(device.custom_voltage_curve)
            if not curve_rows:
                errors.append(
                    "device "
                    f"{device.id or '<unknown>'} "
                    "battery.custom_voltage_curve must not be empty"
                )
            seen_percents: set[int] = set()
            for percent, voltage in curve_rows:
                if percent < 0 or percent > 100 or percent % 10 != 0:
                    errors.append(
                        f"device {device.id or '<unknown>'} battery.custom_voltage_curve "
                        f"percent must be in 10-point steps between 0 and 100"
                    )
                if percent in seen_percents:
                    errors.append(
                        f"device {device.id or '<unknown>'} battery.custom_voltage_curve "
                        f"contains duplicate percent {percent}"
                    )
                seen_percents.add(percent)
                if voltage <= 0:
                    errors.append(
                        f"device {device.id or '<unknown>'} battery.custom_voltage_curve "
                        f"voltage must be positive"
                    )

        if not MAC_ADDRESS_RE.fullmatch(device.mac):
            errors.append(f"device {device.id or '<unknown>'} mac is invalid: {device.mac}")
        elif device.mac in seen_macs:
            errors.append(f"duplicate device mac: {device.mac}")
        else:
            seen_macs.add(device.mac)
    return errors
