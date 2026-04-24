from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from bm_gateway.config import load_config, validate_config


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
    assert config.usb_otg.overview_devices_per_image == 5
    assert config.usb_otg.export_battery_overview is True
    assert config.usb_otg.export_fleet_trend is True
    assert config.usb_otg.fleet_trend_metrics == ("soc",)
    assert config.usb_otg.fleet_trend_range == "7"
    assert config.usb_otg.fleet_trend_device_ids == ()


def test_config_schema_documents_web_language_and_usb_otg_settings() -> None:
    schema = json.loads(Path("python/config/config.schema.json").read_text(encoding="utf-8"))

    web_properties = schema["properties"]["web"]["properties"]
    usb_otg_properties = schema["properties"]["usb_otg"]["properties"]

    assert web_properties["port"]["maximum"] == 65535
    assert "auto" in web_properties["language"]["enum"]
    assert "zh-Hans" in web_properties["language"]["enum"]
    assert usb_otg_properties["size_mb"]["maximum"] == 4096
    assert usb_otg_properties["image_width_px"]["minimum"] == 160
    assert usb_otg_properties["image_height_px"]["minimum"] == 120
    assert usb_otg_properties["image_format"]["enum"] == ["jpeg", "png", "bmp"]
    assert usb_otg_properties["fleet_trend_metrics"]["minItems"] == 1


def test_validate_config_caps_usb_otg_image_size_to_helper_limit() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    oversized = replace(config, usb_otg=replace(config.usb_otg, size_mb=4097))

    assert "usb_otg.size_mb must be less than or equal to 4096" in validate_config(oversized)
