from __future__ import annotations

from pathlib import Path

from bm_gateway.config import load_config


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
