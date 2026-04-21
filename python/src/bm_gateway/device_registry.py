"""Device registry support for BMGateway."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
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
VEHICLE_TYPES = {
    "car": "Car",
    "motorcycle": "Motorcycle",
    "scooter": "Scooter",
    "electric_bike": "Electric Bike",
    "van": "Van",
    "camper": "Camper",
    "truck": "Truck",
    "bus": "Bus",
    "boat": "Boat",
    "tractor": "Tractor",
    "atv": "ATV / Quad",
    "machinery": "Machinery",
    "other_vehicle": "Other",
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
    "vehicle_car": "Car",
    "vehicle_motorcycle": "Motorcycle",
    "vehicle_scooter": "Scooter",
    "vehicle_electric_bike": "Electric Bike",
    "vehicle_van": "Van",
    "vehicle_camper": "Camper",
    "vehicle_truck": "Truck",
    "vehicle_bus": "Bus",
    "vehicle_boat": "Boat",
    "vehicle_tractor": "Tractor",
    "vehicle_atv": "ATV / Quad",
    "vehicle_machinery": "Machinery",
    "vehicle_other": "Other Vehicle",
}
COLOR_CATALOG = {
    "green": "Green",
    "blue": "Blue",
    "purple": "Purple",
    "orange": "Orange",
    "teal": "Teal",
    "rose": "Rose",
    "indigo": "Indigo",
    "amber": "Amber",
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
    color_key: str = "green"
    installed_in_vehicle: bool = False
    vehicle_type: str = ""
    battery_brand: str = ""
    battery_model: str = ""
    battery_capacity_ah: float | None = None
    battery_production_year: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "mac": self.mac,
            "enabled": self.enabled,
            "icon_key": self.icon_key,
            "icon_label": icon_label(self.icon_key),
            "color_key": self.color_key,
            "color_label": color_label(self.color_key),
            "installed_in_vehicle": self.installed_in_vehicle,
            "vehicle_type": self.vehicle_type,
            "battery_brand": self.battery_brand,
            "battery_model": self.battery_model,
            "battery_capacity_ah": self.battery_capacity_ah,
            "battery_production_year": self.battery_production_year,
            "vehicle": {
                "installed": self.installed_in_vehicle,
                "type": self.vehicle_type,
                "type_label": vehicle_type_label(self.vehicle_type),
            },
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
                "brand": self.battery_brand,
                "model": self.battery_model,
                "capacity_ah": self.battery_capacity_ah,
                "production_year": self.battery_production_year,
            },
        }


def battery_family_label(family: str) -> str:
    return BATTERY_FAMILIES.get(family, family.replace("_", " ").title())


def battery_profile_label(*, family: str, profile: str) -> str:
    options = LEAD_ACID_PROFILES if family == "lead_acid" else LITHIUM_PROFILES
    return options.get(profile, profile.replace("_", " ").title())


def icon_label(icon_key: str) -> str:
    return ICON_CATALOG.get(icon_key, icon_key.replace("_", " ").title())


def color_label(color_key: str) -> str:
    return COLOR_CATALOG.get(color_key, color_key.replace("_", " ").title())


def vehicle_type_label(vehicle_type: str) -> str:
    if not vehicle_type:
        return "Not set"
    return VEHICLE_TYPES.get(vehicle_type, vehicle_type.replace("_", " ").title())


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


def default_color_key(*, used_colors: set[str]) -> str:
    for color_key in COLOR_CATALOG:
        if color_key not in used_colors:
            return color_key
    return next(iter(COLOR_CATALOG))


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


def generate_device_id(
    *,
    device_name: str,
    device_type: str,
    existing_ids: set[str],
) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", device_name.strip().lower()).strip("_")
    if not base:
        fallback_type = re.sub(r"[^a-z0-9]+", "_", device_type.strip().lower()).strip("_")
        base = fallback_type or "device"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def load_device_registry(path: Path) -> list[Device]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    raw_devices = data.get("devices", [])
    if not isinstance(raw_devices, list):
        raise ValueError(f"Device registry {path} must define [[devices]] entries.")

    devices: list[Device] = []
    used_colors: set[str] = set()
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
        requested_color_key = str(item.get("color_key", "")).strip()
        resolved_color_key = requested_color_key or default_color_key(used_colors=used_colors)
        used_colors.add(resolved_color_key)
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
                color_key=resolved_color_key,
                installed_in_vehicle=bool(item.get("installed_in_vehicle", False)),
                vehicle_type=str(item.get("vehicle_type", "")).strip(),
                battery_brand=str(battery_table.get("brand", "")).strip(),
                battery_model=str(battery_table.get("model", "")).strip(),
                battery_capacity_ah=(
                    float(battery_table["capacity_ah"])
                    if battery_table.get("capacity_ah") not in (None, "")
                    else None
                ),
                battery_production_year=(
                    int(battery_table["production_year"])
                    if battery_table.get("production_year") not in (None, "")
                    else None
                ),
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
                f"color_key = {_toml_string(device.color_key)}",
                f"installed_in_vehicle = {'true' if device.installed_in_vehicle else 'false'}",
                f"vehicle_type = {_toml_string(device.vehicle_type)}",
                "[devices.battery]",
                f"family = {_toml_string(device.battery_family)}",
                f"profile = {_toml_string(device.battery_profile)}",
                f"custom_soc_mode = {_toml_string(device.custom_soc_mode)}",
            ]
        )
        if device.battery_brand:
            lines.append(f"brand = {_toml_string(device.battery_brand)}")
        if device.battery_model:
            lines.append(f"model = {_toml_string(device.battery_model)}")
        if device.battery_capacity_ah is not None:
            lines.append(f"capacity_ah = {device.battery_capacity_ah:g}")
        if device.battery_production_year is not None:
            lines.append(f"production_year = {device.battery_production_year}")
        lines.append("")
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
    seen_identifiers: set[str] = set()
    seen_colors: set[str] = set()

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

        if device.color_key not in COLOR_CATALOG:
            errors.append(
                f"device {device.id or '<unknown>'} color key must be one of "
                f"{', '.join(sorted(COLOR_CATALOG))}"
            )
        elif device.color_key in seen_colors:
            errors.append(f"duplicate device color key: {device.color_key}")
        else:
            seen_colors.add(device.color_key)

        if device.installed_in_vehicle:
            if device.vehicle_type not in VEHICLE_TYPES:
                errors.append(
                    f"device {device.id or '<unknown>'} vehicle_type must be one of "
                    f"{', '.join(sorted(VEHICLE_TYPES))}"
                )
        elif device.vehicle_type:
            errors.append(
                f"device {device.id or '<unknown>'} vehicle_type requires "
                "installed_in_vehicle = true"
            )

        if device.battery_capacity_ah is not None and device.battery_capacity_ah <= 0:
            errors.append(f"device {device.id or '<unknown>'} battery.capacity_ah must be positive")

        current_year = date.today().year
        if device.battery_production_year is not None and not (
            1950 <= device.battery_production_year <= current_year + 1
        ):
            errors.append(
                f"device {device.id or '<unknown>'} battery.production_year must be between "
                f"1950 and {current_year + 1}"
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

        identifier = device.mac.strip().upper()
        if not identifier:
            errors.append(f"device {device.id or '<unknown>'} mac or serial must not be empty")
        elif identifier in seen_identifiers:
            errors.append(f"duplicate device mac or serial: {device.mac}")
        else:
            seen_identifiers.add(identifier)
    return errors
