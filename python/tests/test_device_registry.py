from __future__ import annotations

from pathlib import Path

from bm_gateway.device_registry import (
    Device,
    default_color_key,
    device_driver_type,
    load_device_registry,
    normalize_mac_address,
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
            battery_nominal_voltage=12,
            battery_capacity_ah=18.0,
            battery_production_year=2025,
        )
    ]

    write_device_registry(path, devices)
    loaded = load_device_registry(path)

    assert loaded == devices


def test_normalize_mac_address_handles_cyrillic_confusables() -> None:
    assert normalize_mac_address("ЗСАВ72B2C667") == "3C:AB:72:B2:C6:67"


def test_commercial_device_type_aliases_map_to_driver_families() -> None:
    assert (
        validate_devices(
            [
                Device(
                    id="bm6_motorcycle",
                    type="bm6",
                    name="BM6 Motorcycle",
                    mac="3C:AB:72:82:86:EA",
                    color_key="green",
                ),
                Device(
                    id="bm900_car",
                    type="bm900pro",
                    name="BM900 Pro Car",
                    mac="3C:AB:72:82:86:EB",
                    color_key="blue",
                ),
                Device(
                    id="bm7_bench",
                    type="bm7",
                    name="BM7 Bench",
                    mac="E0:4E:7A:AF:9B:E8",
                    color_key="purple",
                ),
                Device(
                    id="bm300_bench",
                    type="bm300",
                    name="BM300 Bench",
                    mac="E0:4E:7A:AF:9B:E9",
                    color_key="orange",
                ),
            ]
        )
        == []
    )
    assert device_driver_type("bm6") == "bm200"
    assert device_driver_type("bm900pro") == "bm200"
    assert device_driver_type("bm7") == "bm300pro"
    assert device_driver_type("bm300") == "bm300pro"


def test_validate_devices_accepts_custom_hex_overview_colors() -> None:
    assert (
        validate_devices(
            [
                Device(
                    id="bm200_house",
                    type="bm200",
                    name="BM200 House",
                    mac="3C:AB:72:82:86:EA",
                    color_key="#2f80ed",
                ),
                Device(
                    id="bm200_spare",
                    type="bm200",
                    name="BM200 Spare",
                    mac="3C:AB:72:82:86:EB",
                    color_key="#2f80ed",
                ),
            ]
        )
        == []
    )


def test_default_color_key_treats_preset_hex_values_as_used() -> None:
    assert default_color_key(used_colors={"#17c45a"}) == "blue"
    assert default_color_key(used_colors={"#17C45A", "#4f8df7"}) == "purple"


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
                battery_nominal_voltage=-12,
                battery_capacity_ah=-1,
                battery_production_year=1900,
            )
        ]
    )

    assert any("nominal_voltage" in error for error in errors)
    assert any("capacity_ah" in error for error in errors)
    assert any("production_year" in error for error in errors)
