from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from bm_gateway.config import (
    is_valid_notification_recipient,
    load_config,
    validate_config,
    write_config,
)


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
    assert config.archive_sync.bm200_max_pages_per_sync == 85
    assert config.archive_sync.bm300_enabled is True
    assert config.archive_sync.bm300_max_pages_per_sync == 3
    assert config.bluetooth.live_hard_timeout_seconds == 0
    assert config.self_healing.periodic_reboot_enabled is False
    assert config.self_healing.periodic_reboot_hours == 24
    assert config.self_healing.wifi_watchdog_enabled is False
    assert config.self_healing.wifi_interface == "wlan0"
    assert config.self_healing.connectivity_check_host == "1.1.1.1"
    assert config.self_healing.wifi_reconnect_enabled is True
    assert config.self_healing.wifi_reconnect_after_minutes == 5
    assert config.self_healing.wifi_reboot_enabled is False
    assert config.self_healing.wifi_reboot_after_minutes == 15
    assert config.self_healing.usb_otg_watchdog_enabled is False
    assert config.self_healing.usb_otg_reboot_enabled is False
    assert config.self_healing.usb_otg_reboot_attempts == 1
    assert config.notifications.enabled is False
    assert config.notifications.recipient == ""
    assert config.notifications.locale == "en"
    assert config.notifications.offline_delivery == "summary"
    assert config.notifications.offline_retention_days == 7
    assert config.notifications.offline_max_events == 100


def test_load_config_defaults_archive_sync_when_section_is_absent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text("", encoding="utf-8")
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
                "[bluetooth]",
                "",
                "[mqtt]",
                "",
                "[home_assistant]",
                "",
                "[web]",
                "",
                "[retention]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.archive_sync.enabled is True
    assert config.archive_sync.periodic_interval_seconds == 64800
    assert config.archive_sync.reconnect_min_gap_seconds == 28800
    assert config.archive_sync.safety_margin_seconds == 7200
    assert config.archive_sync.bm200_max_pages_per_sync == 85
    assert config.archive_sync.bm300_enabled is True
    assert config.archive_sync.bm300_max_pages_per_sync == 3
    assert config.retention.raw_retention_days == 730
    assert config.retention.daily_retention_days == 0
    assert config.bluetooth.live_hard_timeout_seconds == 0
    assert config.self_healing.periodic_reboot_enabled is False
    assert config.self_healing.periodic_reboot_hours == 24
    assert config.self_healing.wifi_watchdog_enabled is False


def test_shipped_config_examples_share_notification_defaults() -> None:
    standard = load_config(Path("python/config/config.toml.example"))
    gateway = load_config(Path("python/config/gateway.toml.example"))

    assert gateway.notifications == standard.notifications


def test_load_config_accepts_legacy_per_driver_live_hard_timeout_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text("", encoding="utf-8")
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
                "[bluetooth]",
                "bm200_live_hard_timeout_seconds = 75",
                "bm300_live_hard_timeout_seconds = 90",
                "",
                "[mqtt]",
                "",
                "[home_assistant]",
                "",
                "[web]",
                "",
                "[retention]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.bluetooth.live_hard_timeout_seconds == 90


def test_config_schema_documents_web_language_and_usb_otg_settings() -> None:
    schema = json.loads(Path("python/config/config.schema.json").read_text(encoding="utf-8"))

    web_properties = schema["properties"]["web"]["properties"]
    usb_otg_properties = schema["properties"]["usb_otg"]["properties"]
    archive_sync_properties = schema["properties"]["archive_sync"]["properties"]
    self_healing_properties = schema["properties"]["self_healing"]["properties"]
    notification_properties = schema["properties"]["notifications"]["properties"]
    retention_properties = schema["properties"]["retention"]["properties"]
    bluetooth_properties = schema["properties"]["bluetooth"]["properties"]

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
    assert self_healing_properties["periodic_reboot_hours"]["minimum"] == 1
    assert self_healing_properties["periodic_reboot_hours"]["maximum"] == 48
    assert self_healing_properties["wifi_reconnect_after_minutes"]["minimum"] == 1
    assert self_healing_properties["usb_otg_reboot_attempts"]["minimum"] == 0
    assert self_healing_properties["usb_otg_reboot_attempts"]["maximum"] == 5
    assert notification_properties["offline_delivery"]["enum"] == ["summary", "individual", "drop"]
    assert notification_properties["offline_retention_days"]["maximum"] == 30
    assert retention_properties["raw_retention_days"]["default"] == 730
    assert retention_properties["daily_retention_days"]["default"] == 0
    assert bluetooth_properties["live_hard_timeout_seconds"]["minimum"] == 0


def test_validate_config_caps_usb_otg_image_size_to_helper_limit() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    oversized = replace(config, usb_otg=replace(config.usb_otg, size_mb=4097))

    assert "usb_otg.size_mb must be less than or equal to 4096" in validate_config(oversized)


def test_validate_config_rejects_invalid_timezone() -> None:
    config = load_config(Path("python/config/config.toml.example"))

    for timezone_name in ("Not/A_Real_Timezone", "/etc/localtime"):
        invalid = replace(config, gateway=replace(config.gateway, timezone=timezone_name))

        assert "gateway.timezone must be a valid IANA timezone" in validate_config(invalid)


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
        bluetooth=replace(
            config.bluetooth,
            live_hard_timeout_seconds=120,
        ),
        self_healing=replace(
            config.self_healing,
            periodic_reboot_enabled=True,
            periodic_reboot_hours=12,
            wifi_watchdog_enabled=True,
            wifi_interface="wlan1",
            connectivity_check_host="192.168.1.1",
            wifi_reconnect_enabled=True,
            wifi_reconnect_after_minutes=7,
            wifi_reboot_enabled=True,
            wifi_reboot_after_minutes=20,
            usb_otg_watchdog_enabled=True,
            usb_otg_reboot_enabled=True,
            usb_otg_reboot_attempts=2,
        ),
        notifications=replace(
            config.notifications,
            enabled=True,
            recipient="operator@example.test",
            locale="it",
            offline_delivery="individual",
            offline_retention_days=14,
            offline_max_events=200,
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
    assert loaded.bluetooth.live_hard_timeout_seconds == 120
    assert loaded.self_healing.periodic_reboot_enabled is True
    assert loaded.self_healing.periodic_reboot_hours == 12
    assert loaded.self_healing.wifi_watchdog_enabled is True
    assert loaded.self_healing.wifi_interface == "wlan1"
    assert loaded.self_healing.connectivity_check_host == "192.168.1.1"
    assert loaded.self_healing.wifi_reconnect_after_minutes == 7
    assert loaded.self_healing.wifi_reboot_enabled is True
    assert loaded.self_healing.wifi_reboot_after_minutes == 20
    assert loaded.self_healing.usb_otg_watchdog_enabled is True
    assert loaded.self_healing.usb_otg_reboot_enabled is True
    assert loaded.self_healing.usb_otg_reboot_attempts == 2
    assert loaded.notifications.enabled is True
    assert loaded.notifications.recipient == "operator@example.test"
    assert loaded.notifications.locale == "it"
    assert loaded.notifications.offline_delivery == "individual"
    assert loaded.notifications.offline_retention_days == 14
    assert loaded.notifications.offline_max_events == 200


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


def test_validate_config_rejects_negative_live_hard_timeout() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    negative_live_hard_timeout = replace(
        config,
        bluetooth=replace(config.bluetooth, live_hard_timeout_seconds=-1),
    )

    assert "bluetooth.live_hard_timeout_seconds must be zero or greater" in validate_config(
        negative_live_hard_timeout
    )


def test_validate_config_bounds_self_healing_values() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    invalid = replace(
        config,
        self_healing=replace(
            config.self_healing,
            periodic_reboot_hours=49,
            wifi_interface="",
            connectivity_check_host="",
            wifi_reconnect_after_minutes=0,
            wifi_reboot_enabled=True,
            wifi_reboot_after_minutes=0,
            usb_otg_reboot_attempts=6,
        ),
    )

    errors = validate_config(invalid)

    assert "self_healing.periodic_reboot_hours must be between 1 and 48" in errors
    assert "self_healing.wifi_interface must not be empty" in errors
    assert "self_healing.connectivity_check_host must not be empty" in errors
    assert "self_healing.wifi_reconnect_after_minutes must be at least 1" in errors
    assert "self_healing.wifi_reboot_after_minutes must be at least 1" in errors
    assert "self_healing.usb_otg_reboot_attempts must be between 0 and 5" in errors


def test_validate_config_requires_usb_export_for_usb_otg_watchdog() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    invalid = replace(
        config,
        self_healing=replace(config.self_healing, usb_otg_watchdog_enabled=True),
    )

    assert "self_healing.usb_otg_watchdog_enabled requires usb_otg.enabled" in validate_config(
        invalid
    )


def test_validate_config_rejects_invalid_notification_preferences() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    invalid = replace(
        config,
        notifications=replace(
            config.notifications,
            enabled=True,
            recipient="",
            locale="auto",
            offline_delivery="all",
            offline_retention_days=31,
            offline_max_events=0,
        ),
    )

    errors = validate_config(invalid)

    assert "notifications.recipient must not be empty when notifications are enabled" in errors
    assert "notifications.locale must be a supported locale" in errors
    assert "notifications.offline_delivery must be one of: summary, individual, drop" in errors
    assert "notifications.offline_retention_days must be between 1 and 30" in errors
    assert "notifications.offline_max_events must be between 1 and 1000" in errors


def test_validate_config_rejects_notification_header_injection() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    invalid = replace(
        config,
        notifications=replace(
            config.notifications,
            enabled=True,
            recipient="operator@example.test\nBcc: attacker@example.test",
        ),
    )

    assert "notifications.recipient must be a single email address" in validate_config(invalid)


def test_validate_config_rejects_multiple_or_malformed_notification_recipients() -> None:
    config = load_config(Path("python/config/config.toml.example"))
    for recipient in (
        "one@example.test, two@example.test",
        ".operator@example.test",
        "operator..name@example.test",
        "operator.@example.test",
        "Operator <operator@example.test>",
        "operator(comment)@example.test",
        " operator@example.test",
        "operator@localhost",
        "operator @example.test",
        "operator@-example.test",
        "operator@example-.test",
        "operator@example_test.test",
        f"{'a' * 65}@example.test",
        f"operator@{'a' * 64}.test",
        "operator@" + ".".join(["a" * 63] * 4),
    ):
        invalid = replace(
            config,
            notifications=replace(config.notifications, enabled=True, recipient=recipient),
        )

        assert "notifications.recipient must be a single email address" in validate_config(invalid)


def test_notification_recipient_accepts_plain_boundary_addr_specs() -> None:
    assert is_valid_notification_recipient("operator+alerts@example.test")
    assert is_valid_notification_recipient(f"{'a' * 64}@example.test")
