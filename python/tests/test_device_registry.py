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
