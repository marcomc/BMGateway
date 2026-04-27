from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from bm_gateway.config import load_config, validate_config, write_config


def test_load_config_defaults_web_port_and_chart_markers(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text("", encoding="utf-8")
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 300",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "fake"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 15",
                "connect_timeout_seconds = 45",
                "",
                "[mqtt]",
                "enabled = false",
                'host = "localhost"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "CHANGE_ME"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = false",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "0.0.0.0"',
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.web.port == 80
    assert config.web.show_chart_markers is False
    assert config.web.default_chart_range == "7"
    assert config.web.default_chart_metric == "soc"
    assert config.usb_otg.enabled is False
    assert config.usb_otg.image_path == "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img"
    assert config.usb_otg.size_mb == 64
    assert config.usb_otg.gadget_name == "bmgw_frame"
    assert config.usb_otg.image_width_px == 480
    assert config.usb_otg.image_height_px == 234
    assert config.usb_otg.image_format == "jpeg"
    assert config.usb_otg.appearance == "light"
    assert config.usb_otg.refresh_interval_seconds == 0
    assert config.usb_otg.overview_devices_per_image == 3
    assert config.usb_otg.export_battery_overview is True
    assert config.usb_otg.export_fleet_trend is True
    assert config.usb_otg.fleet_trend_metrics == ("soc",)
    assert config.usb_otg.fleet_trend_range == "7"
    assert config.usb_otg.fleet_trend_device_ids == ()
    assert config.archive_sync.enabled is True
    assert config.archive_sync.periodic_interval_seconds == 64800
    assert config.archive_sync.reconnect_min_gap_seconds == 28800
    assert config.archive_sync.safety_margin_seconds == 7200
    assert config.archive_sync.bm200_max_pages_per_sync == 3
    assert config.archive_sync.bm300_enabled is False
    assert config.archive_sync.bm300_max_pages_per_sync == 1


def test_config_schema_documents_web_language_and_usb_otg_settings() -> None:
    schema = json.loads(Path("python/config/config.schema.json").read_text(encoding="utf-8"))

    web_properties = schema["properties"]["web"]["properties"]
    usb_otg_properties = schema["properties"]["usb_otg"]["properties"]
    archive_sync_properties = schema["properties"]["archive_sync"]["properties"]

    assert web_properties["port"]["maximum"] == 65535
    assert "auto" in web_properties["language"]["enum"]
    assert "zh-Hans" in web_properties["language"]["enum"]
    assert usb_otg_properties["size_mb"]["maximum"] == 4096
    assert usb_otg_properties["image_width_px"]["minimum"] == 160
    assert usb_otg_properties["image_height_px"]["minimum"] == 120
    assert usb_otg_properties["image_format"]["enum"] == ["jpeg", "png", "bmp"]
    assert usb_otg_properties["fleet_trend_metrics"]["minItems"] == 1
    assert archive_sync_properties["periodic_interval_seconds"]["minimum"] == 1
    assert archive_sync_properties["bm200_max_pages_per_sync"]["maximum"] == 85
    assert archive_sync_properties["bm300_max_pages_per_sync"]["maximum"] == 59


def test_validate_config_caps_usb_otg_image_size_to_helper_limit() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    oversized = replace(config, usb_otg=replace(config.usb_otg, size_mb=4097))

    assert "usb_otg.size_mb must be less than or equal to 4096" in validate_config(oversized)


def test_write_config_round_trips_archive_sync_settings(tmp_path: Path) -> None:
    config = load_config(Path("python/config/config.toml.example"))
    (tmp_path / "devices.toml").write_text("", encoding="utf-8")
    target = tmp_path / "config.toml"
    updated = replace(
        config,
        source_path=target.resolve(),
        device_registry_path=(tmp_path / "devices.toml").resolve(),
        gateway=replace(config.gateway, device_registry="devices.toml"),
        archive_sync=replace(
            config.archive_sync,
            enabled=False,
            periodic_interval_seconds=43200,
            reconnect_min_gap_seconds=14400,
            safety_margin_seconds=1800,
            bm200_max_pages_per_sync=6,
            bm300_enabled=True,
            bm300_max_pages_per_sync=9,
        ),
    )

    write_config(target, updated)
    loaded = load_config(target)

    assert loaded.archive_sync.enabled is False
    assert loaded.archive_sync.periodic_interval_seconds == 43200
    assert loaded.archive_sync.reconnect_min_gap_seconds == 14400
    assert loaded.archive_sync.safety_margin_seconds == 1800
    assert loaded.archive_sync.bm200_max_pages_per_sync == 6
    assert loaded.archive_sync.bm300_enabled is True
    assert loaded.archive_sync.bm300_max_pages_per_sync == 9


def test_validate_config_bounds_archive_sync_page_count() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    too_many = replace(
        config,
        archive_sync=replace(config.archive_sync, bm200_max_pages_per_sync=86),
    )

    assert "archive_sync.bm200_max_pages_per_sync must be between 1 and 85" in validate_config(
        too_many
    )

    too_many_bm300 = replace(
        config,
        archive_sync=replace(config.archive_sync, bm300_max_pages_per_sync=60),
    )

    assert "archive_sync.bm300_max_pages_per_sync must be between 1 and 59" in validate_config(
        too_many_bm300
    )
