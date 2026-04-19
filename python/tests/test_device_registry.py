from __future__ import annotations

from pathlib import Path

from bm_gateway.device_registry import (
    Device,
    load_device_registry,
    validate_devices,
    write_device_registry,
)


def test_write_and_load_device_registry_round_trips_battery_metadata(tmp_path: Path) -> None:
    path = tmp_path / "devices.toml"
    devices = [
        Device(
            id="ancell_bm200",
            type="bm200",
            name="Ancell BM200",
            mac="3C:AB:72:82:86:EA",
            enabled=True,
            battery_family="lead_acid",
            battery_profile="custom",
            custom_soc_mode="voltage_corresponding_power",
            custom_voltage_curve=((100, 12.9), (90, 12.8), (0, 11.9)),
            icon_key="motorcycle_12v",
            installed_in_vehicle=True,
            vehicle_type="motorcycle",
            battery_brand="Ancell",
            battery_model="BM200 AGM",
            battery_capacity_ah=18.0,
            battery_production_year=2025,
        )
    ]

    write_device_registry(path, devices)
    loaded = load_device_registry(path)

    assert loaded == devices


def test_validate_devices_rejects_invalid_custom_curve() -> None:
    errors = validate_devices(
        [
            Device(
                id="ancell_bm200",
                type="bm200",
                name="Ancell BM200",
                mac="3C:AB:72:82:86:EA",
                battery_family="lead_acid",
                battery_profile="custom",
                custom_soc_mode="voltage_corresponding_power",
                custom_voltage_curve=((95, 12.8),),
            )
        ]
    )

    assert any("10-point steps" in error for error in errors)


def test_validate_devices_rejects_unknown_icon_key() -> None:
    errors = validate_devices(
        [
            Device(
                id="ancell_bm200",
                type="bm200",
                name="Ancell BM200",
                mac="3C:AB:72:82:86:EA",
                icon_key="not_a_real_icon",
            )
        ]
    )

    assert any("icon key" in error.lower() for error in errors)


def test_validate_devices_requires_vehicle_type_when_installed_in_vehicle() -> None:
    errors = validate_devices(
        [
            Device(
                id="ancell_bm200",
                type="bm200",
                name="Ancell BM200",
                mac="3C:AB:72:82:86:EA",
                installed_in_vehicle=True,
            )
        ]
    )

    assert any("vehicle_type" in error for error in errors)


def test_validate_devices_rejects_invalid_battery_metadata() -> None:
    errors = validate_devices(
        [
            Device(
                id="ancell_bm200",
                type="bm200",
                name="Ancell BM200",
                mac="3C:AB:72:82:86:EA",
                battery_capacity_ah=-1,
                battery_production_year=1900,
            )
        ]
    )

    assert any("capacity_ah" in error for error in errors)
    assert any("production_year" in error for error in errors)
