"""Management and settings page rendering for the BMGateway web interface."""

from __future__ import annotations

import html
from functools import lru_cache
from typing import cast
from zoneinfo import available_timezones

from . import display_version
from . import web_pages as shared
from .config import AppConfig
from .localization import locale_options
from .usb_otg import (
    usb_otg_boot_mode_prepared as detect_usb_otg_boot_mode_prepared,
)
from .usb_otg import (
    usb_otg_device_controller_detected as detect_usb_otg_device_controller,
)
from .usb_otg import (
    usb_otg_support_installed as detect_usb_otg_support_installed,
)
from .web_pages_frame import FRAME_OVERVIEW_DEVICES_PER_PAGE
from .web_ui import (
    api_chip,
    app_document,
    banner_strip,
    button,
    section_card,
    settings_control_row,
    settings_row,
    summary_card,
    top_header,
)


@lru_cache(maxsize=1)
def _available_timezone_options() -> tuple[str, ...]:
    try:
        zones = sorted(available_timezones())
    except OSError:
        zones = []
    if "UTC" not in zones:
        zones.insert(0, "UTC")
    return tuple(zones)


def _settings_markup_row(label: str, value_html: str) -> str:
    return (
        '<div class="settings-row">'
        f'<div class="settings-label">{html.escape(label)}</div>'
        f'<div class="settings-value">{value_html}</div>'
        "</div>"
    )


def _usb_otg_fleet_device_checkbox(
    *,
    device: dict[str, object],
    checked: bool,
) -> str:
    device_id = str(device.get("id", ""))
    label = str(device.get("name") or device.get("id") or "Device")
    return (
        f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
        '<input type="checkbox" name="fleet_trend_device_ids" '
        f'value="{html.escape(device_id)}"{shared._checked_attr(checked)}>'
        f"<span>{html.escape(label)}</span>"
        "</label>"
    )


def _poll_interval_warning(config: AppConfig) -> str:
    if config.gateway.poll_interval_seconds >= 300:
        return ""
    return banner_strip(
        html.escape(
            "Poll interval warning: Polling faster than 300 seconds can increase Bluetooth "
            "discovery failures, device contention, and error-heavy history on BM6/BM200 "
            "monitors."
        ),
        kind="error",
    )


def _usb_otg_refresh_interval_label(config: AppConfig) -> str:
    if config.usb_otg.refresh_interval_seconds == 0:
        return f"Use gateway poll interval ({config.gateway.poll_interval_seconds} seconds)"
    return f"{config.usb_otg.refresh_interval_seconds} seconds"


def _duration_label(seconds: int) -> str:
    if seconds % 86400 == 0:
        value = seconds // 86400
        return f"{value} day" if value == 1 else f"{value} days"
    if seconds % 3600 == 0:
        value = seconds // 3600
        return f"{value} hour" if value == 1 else f"{value} hours"
    if seconds % 60 == 0:
        value = seconds // 60
        return f"{value} minute" if value == 1 else f"{value} minutes"
    return f"{seconds} seconds"


def _usb_otg_refresh_interval_warning(config: AppConfig) -> str:
    refresh_interval = (
        config.gateway.poll_interval_seconds
        if config.usb_otg.refresh_interval_seconds == 0
        else config.usb_otg.refresh_interval_seconds
    )
    if refresh_interval >= config.gateway.poll_interval_seconds:
        return ""
    return banner_strip(
        html.escape(
            "USB OTG export interval warning: exporting faster than the gateway poll interval "
            "can repeat stale battery data and detach/reattach the USB drive more often than "
            "the picture frame can reliably rescan it."
        ),
        kind="error",
    )


def render_management_html(
    *,
    snapshot: dict[str, object],
    config: AppConfig,
    storage_summary: dict[str, object],
    devices: list[dict[str, object]],
    config_text: str,
    devices_text: str,
    contract: dict[str, object],
    message: str = "",
    theme_preference: str = "system",
    language: str | None = None,
) -> str:
    return render_settings_html(
        config=config,
        snapshot=snapshot,
        devices=devices,
        edit_mode=True,
        message=message,
        storage_summary=storage_summary,
        config_text=config_text,
        devices_text=devices_text,
        contract=contract,
        theme_preference=theme_preference,
        language=language,
    )


def render_settings_html(
    *,
    config: AppConfig,
    snapshot: dict[str, object],
    devices: list[dict[str, object]],
    edit_mode: bool = False,
    message: str = "",
    storage_summary: dict[str, object] | None = None,
    config_text: str | None = None,
    devices_text: str | None = None,
    contract: dict[str, object] | None = None,
    detected_bluetooth_adapters: list[dict[str, str]] | None = None,
    usb_otg_device_controller_detected: bool | None = None,
    usb_otg_boot_mode_prepared: bool | None = None,
    usb_otg_support_installed: bool | None = None,
    theme_preference: str = "system",
    language: str | None = None,
) -> str:
    resolved_language = language or config.web.language
    version_label = display_version()
    primary_device_id = shared._primary_device_id(snapshot, devices)
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    storage_summary = storage_summary or {
        "counts": {
            "gateway_snapshots": 0,
            "device_readings": 0,
            "device_daily_rollups": 0,
        },
        "devices": [],
    }
    configured_device_ids = {str(device.get("id", "")) for device in devices}
    contract = contract or {}
    detected_bluetooth_adapters = (
        shared._discover_bluetooth_adapters()
        if detected_bluetooth_adapters is None
        else detected_bluetooth_adapters
    )
    detected_usb_otg_controller = (
        detect_usb_otg_device_controller()
        if usb_otg_device_controller_detected is None
        else usb_otg_device_controller_detected
    )
    prepared_usb_otg_boot_mode = (
        detect_usb_otg_boot_mode_prepared()
        if usb_otg_boot_mode_prepared is None
        else usb_otg_boot_mode_prepared
    )
    installed_usb_otg_support = (
        detect_usb_otg_support_installed()
        if usb_otg_support_installed is None
        else usb_otg_support_installed
    )
    device_tabs = (
        "".join(
            (
                f"<span class='pill-chip'>"
                f"{html.escape(str(device.get('name', device.get('id', 'Device'))))}"
                "</span>"
            )
            for device in devices
        )
        or "<span class='pill-chip'>No devices configured</span>"
    )
    web_enabled = f"{config.web.host}:{config.web.port}" if config.web.enabled else "disabled"
    daily_retention = (
        "unlimited"
        if config.retention.daily_retention_days == 0
        else f"{config.retention.daily_retention_days} days"
    )
    counts = cast(dict[str, object], storage_summary.get("counts", {}))
    gateway_contract = cast(dict[str, object], contract.get("gateway", {}))
    contract_devices = cast(list[object], contract.get("devices", []))
    gateway_state_topic = html.escape(str(gateway_contract.get("state_topic", "")))
    gateway_discovery_topic = html.escape(str(gateway_contract.get("discovery_topic", "")))
    device_contract_count = len(contract_devices) if isinstance(contract_devices, list) else 0
    detected_adapter_names = [
        str(adapter.get("name", ""))
        for adapter in detected_bluetooth_adapters
        if str(adapter.get("name", ""))
    ]
    configured_adapter_present = (
        config.bluetooth.adapter == "auto" or config.bluetooth.adapter in detected_adapter_names
    )
    adapter_status = (
        "No Bluetooth adapters detected"
        if not detected_adapter_names
        else (
            f"Configured adapter {config.bluetooth.adapter} is missing"
            if not configured_adapter_present
            else "Adapter detected"
        )
    )
    mqtt_connected = bool(snapshot.get("mqtt_connected", False))
    mqtt_connection_badge = (
        '<span class="status-badge ok">Connected</span>'
        if mqtt_connected
        else '<span class="status-badge error">Disconnected</span>'
    )
    detected_adapter_summary = ", ".join(detected_adapter_names) or "No adapters detected"
    api_chips = "".join(
        api_chip(endpoint)
        for endpoint in (
            "/api/status",
            "/api/config",
            "/api/devices",
            "/api/ha/contract",
            "/api/ha/discovery",
            "/api/storage",
            "/api/analytics?device_id=<id>",
            "/api/history?device_id=<id>&kind=daily",
        )
    )
    overview_cards = (
        '<div class="metrics-grid compact-overview-grid">'
        + summary_card(
            "Latest snapshot",
            shared._display_timestamp(snapshot.get("generated_at", "missing")),
            subvalue=f"Gateway: {html.escape(str(snapshot.get('gateway_name', 'BMGateway')))}",
            classes="compact-summary timestamp-summary",
        )
        + summary_card(
            "Gateway snapshots",
            str(counts.get("gateway_snapshots", 0)),
            subvalue=(
                f"Devices online: {snapshot.get('devices_online', 0)} / "
                f"{snapshot.get('devices_total', 0)}"
            ),
            classes="compact-summary",
        )
        + summary_card(
            "Raw / rollups",
            f"{counts.get('device_readings', 0)} / {counts.get('device_daily_rollups', 0)}",
            subvalue=f"MQTT connected: {snapshot.get('mqtt_connected', False)}",
            classes="compact-summary",
        )
        + "</div>"
    )
    actions_body = (
        '<div class="inline-actions">'
        '<form method="post" action="/actions/run-once">'
        f"{button('Run One Collection Cycle', kind='primary')}"
        "</form>"
        '<form method="post" action="/actions/republish-discovery">'
        f"{button('Republish Home Assistant Discovery', kind='secondary')}"
        "</form>"
        + (
            '<form method="post" action="/actions/refresh-usb-otg-drive">'
            f"{button('Refresh USB OTG Drive', kind='secondary')}"
            "</form>"
            '<form method="post" action="/actions/export-usb-otg-images">'
            f"{button('Export Frame Images', kind='secondary')}"
            "</form>"
            if installed_usb_otg_support
            else ""
        )
        + '<form method="post" action="/actions/restart-runtime">'
        f"{button('Restart bm-gateway service', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/restart-bluetooth-service">'
        f"{button('Restart Bluetooth service', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/reboot-host" '
        "onsubmit=\"return confirm('Reboot the Raspberry Pi now?')\">"
        f"{button('Reboot Raspberry Pi', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/shutdown-host" '
        "onsubmit=\"return confirm('Shut down the Raspberry Pi now? Wait for the activity LED "
        "to stop blinking before unplugging power.')\">"
        f"{button('Shut Down Raspberry Pi', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/recover-bluetooth">'
        f"{button('Recover Bluetooth Adapter', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/prune-history">'
        f"{button('Prune History Using Retention Settings', kind='secondary')}"
        "</form>"
        "</div>"
        '<div style="margin-top:1rem" class="chip-grid">'
        f"{api_chips}"
        "</div>"
    )
    web_section_body = (
        settings_row("Web interface", web_enabled)
        + settings_row("Configured host", config.web.host)
        + settings_row("Configured port", str(config.web.port))
    )
    display_section_body = (
        settings_row(
            "Chart point markers",
            "Enabled" if config.web.show_chart_markers else "Disabled",
        )
        + settings_row(
            "Default chart range",
            {
                "1": "1 day",
                "3": "3 days",
                "5": "5 days",
                "7": "7 days",
                "30": "30 days",
                "90": "90 days",
                "365": "1 year",
                "730": "2 years",
                "all": "All",
            }.get(
                shared._sanitize_default_chart_range(config.web.default_chart_range),
                shared._sanitize_default_chart_range(config.web.default_chart_range),
            ),
        )
        + settings_row(
            "Default chart metric",
            {
                "voltage": "Voltage",
                "soc": "State of Charge",
                "temperature": "Temperature",
            }.get(config.web.default_chart_metric, config.web.default_chart_metric),
        )
        + settings_row(
            "Appearance",
            {
                "light": "Light",
                "dark": "Dark",
                "system": "System",
            }.get(config.web.appearance, config.web.appearance),
        )
        + settings_row(
            "Language",
            dict(locale_options()).get(config.web.language, config.web.language),
        )
    )
    archive_sync_section_body = (
        settings_row(
            "Archive history import",
            "Enabled" if config.archive_sync.enabled else "Disabled",
        )
        + settings_row(
            "Periodic sync interval",
            _duration_label(config.archive_sync.periodic_interval_seconds),
        )
        + settings_row(
            "Reconnect backfill threshold",
            _duration_label(config.archive_sync.reconnect_min_gap_seconds),
        )
        + settings_row(
            "Safety margin",
            _duration_label(config.archive_sync.safety_margin_seconds),
        )
        + settings_row(
            "BM200 pages per sync",
            str(config.archive_sync.bm200_max_pages_per_sync),
        )
        + settings_row(
            "BM300 Pro history import",
            "Enabled" if config.archive_sync.bm300_enabled else "Disabled",
        )
        + settings_row(
            "BM300 pages per sync",
            str(config.archive_sync.bm300_max_pages_per_sync),
        )
    )
    usb_otg_warning = (
        banner_strip(
            html.escape(
                "USB OTG image export is enabled, but no USB OTG device controller is "
                "currently detected. Check that the Zero USB Plug or OTG cable is connected "
                "and that dwc2 peripheral mode is enabled."
            ),
            kind="error",
        )
        if config.usb_otg.enabled and not detected_usb_otg_controller
        else ""
    )
    usb_otg_install_warning = (
        banner_strip(
            html.escape(
                "USB OTG support was not installed on this system. Re-run the Raspberry Pi "
                "installer without --skip-usb-otg-tools to install dosfstools, the drive "
                "export helper, and the web sudo policy."
            ),
            kind="error",
        )
        if not installed_usb_otg_support
        else ""
    )
    usb_otg_controller_badge = (
        '<span class="status-badge ok">Detected</span>'
        if detected_usb_otg_controller
        else '<span class="status-badge error">Not detected</span>'
    )
    usb_otg_support_badge = (
        '<span class="status-badge ok">Installed</span>'
        if installed_usb_otg_support
        else '<span class="status-badge error">Not installed</span>'
    )
    usb_otg_section_body = (
        usb_otg_install_warning
        + usb_otg_warning
        + _usb_otg_refresh_interval_warning(config)
        + settings_row(
            "USB OTG image export",
            "Enabled" if config.usb_otg.enabled else "Disabled",
        )
        + _settings_markup_row("USB OTG support", usb_otg_support_badge)
        + _settings_markup_row("USB OTG device controller", usb_otg_controller_badge)
        + settings_row(
            "Output size",
            f"{config.usb_otg.image_width_px} x {config.usb_otg.image_height_px} px",
        )
        + settings_row("Output format", config.usb_otg.image_format.upper())
        + settings_row("Frame appearance", config.usb_otg.appearance.title())
        + settings_row("Export interval", _usb_otg_refresh_interval_label(config))
        + settings_row("Devices per overview image", str(FRAME_OVERVIEW_DEVICES_PER_PAGE))
        + settings_row(
            "Exported images",
            ", ".join(
                label
                for enabled, label in (
                    (config.usb_otg.export_battery_overview, "battery overview"),
                    (config.usb_otg.export_fleet_trend, "fleet trend"),
                )
                if enabled
            )
            or "None",
        )
        + settings_row(
            "Fleet Trend metrics",
            ", ".join(
                label
                for value, label in (
                    ("voltage", "Voltage"),
                    ("soc", "SoC"),
                    ("temperature", "Temperature"),
                )
                if value in config.usb_otg.fleet_trend_metrics
            )
            or "None",
        )
        + settings_row(
            "Fleet Trend range",
            dict(shared._visible_chart_range_options()).get(
                config.usb_otg.fleet_trend_range,
                config.usb_otg.fleet_trend_range,
            ),
        )
        + settings_row(
            "Frame devices",
            (
                "All configured devices"
                if not config.usb_otg.fleet_trend_device_ids
                else ", ".join(config.usb_otg.fleet_trend_device_ids)
            ),
        )
        + settings_row("Backing disk image", config.usb_otg.image_path)
        + settings_row("Image size", f"{config.usb_otg.size_mb} MB")
        + settings_row("Gadget name", config.usb_otg.gadget_name)
    )
    bluetooth_section_body = (
        settings_row("Adapter", config.bluetooth.adapter)
        + settings_row("Detected adapters", detected_adapter_summary)
        + settings_row("Adapter status", adapter_status)
        + settings_row("Scan timeout", f"{config.bluetooth.scan_timeout_seconds} seconds")
        + settings_row("Connect timeout", f"{config.bluetooth.connect_timeout_seconds} seconds")
    )
    gateway_section_body = (
        _poll_interval_warning(config)
        + f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
        + settings_row("Gateway name", config.gateway.name)
        + settings_row("Timezone", config.gateway.timezone)
        + settings_row("Live polling", config.gateway.reader_mode)
        + settings_row("Poll interval", f"{config.gateway.poll_interval_seconds} seconds")
        + settings_row("Raw retention", f"{config.retention.raw_retention_days} days")
        + settings_row("Daily rollup retention", daily_retention)
    )
    mqtt_section_body = (
        settings_row("MQTT", "Enabled" if config.mqtt.enabled else "Disabled")
        + _settings_markup_row(
            "MQTT broker connection",
            mqtt_connection_badge,
        )
        + settings_row("MQTT broker host", config.mqtt.host)
        + settings_row("MQTT broker port", str(config.mqtt.port))
        + settings_row(
            "MQTT username",
            config.mqtt.username or "Anonymous / not set",
        )
        + settings_row(
            "MQTT password",
            "Configured" if config.mqtt.password else "Empty / anonymous",
        )
        + settings_row("MQTT base topic", config.mqtt.base_topic)
        + settings_row("MQTT discovery prefix", config.mqtt.discovery_prefix)
        + settings_row(
            "MQTT retain discovery",
            "Enabled" if config.mqtt.retain_discovery else "Disabled",
        )
        + settings_row(
            "MQTT retain state",
            "Enabled" if config.mqtt.retain_state else "Disabled",
        )
    )
    home_assistant_section_body = (
        settings_row(
            "Home Assistant MQTT discovery",
            "Enabled" if config.home_assistant.enabled else "Disabled",
        )
        + settings_row("Home Assistant status topic", config.home_assistant.status_topic)
        + settings_row("Home Assistant gateway device id", config.home_assistant.gateway_device_id)
    )
    if edit_mode:
        reader_mode_options = "".join(
            _option_html(value, value, config.gateway.reader_mode) for value in ("fake", "live")
        )
        default_chart_range_options = "".join(
            _option_html(
                value,
                label,
                shared._sanitize_default_chart_range(config.web.default_chart_range),
            )
            for value, label in shared._visible_chart_range_options()
        )
        default_chart_metric_options = "".join(
            _option_html(value, label, config.web.default_chart_metric)
            for value, label in (
                ("voltage", "Voltage"),
                ("soc", "State of Charge"),
                ("temperature", "Temperature"),
            )
        )
        appearance_options = "".join(
            _option_html(value, label, config.web.appearance)
            for value, label in (
                ("light", "Light"),
                ("dark", "Dark"),
                ("system", "System"),
            )
        )
        language_options = "".join(
            _option_html(value, label, config.web.language) for value, label in locale_options()
        )
        timezone_choices = _available_timezone_options()
        timezone_options = (
            ""
            if config.gateway.timezone in timezone_choices
            else _option_html(
                config.gateway.timezone,
                f"{config.gateway.timezone} (configured)",
                config.gateway.timezone,
            )
        ) + "".join(
            _option_html(value, value, config.gateway.timezone) for value in timezone_choices
        )
        usb_otg_format_options = "".join(
            _option_html(value, label, config.usb_otg.image_format)
            for value, label in (("jpeg", "JPEG"), ("png", "PNG"), ("bmp", "BMP"))
        )
        usb_otg_appearance_options = "".join(
            _option_html(value, label, config.usb_otg.appearance)
            for value, label in (("light", "Light"), ("dark", "Dark"))
        )
        usb_otg_devices_per_image_options = _option_html(
            str(FRAME_OVERVIEW_DEVICES_PER_PAGE),
            str(FRAME_OVERVIEW_DEVICES_PER_PAGE),
            str(FRAME_OVERVIEW_DEVICES_PER_PAGE),
        )
        usb_otg_fleet_range_options = "".join(
            _option_html(
                value,
                label,
                shared._sanitize_default_chart_range(config.usb_otg.fleet_trend_range),
            )
            for value, label in shared._visible_chart_range_options()
        )
        usb_otg_fleet_metric_controls = "".join(
            (
                f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                f'<input type="checkbox" name="fleet_trend_metrics" value="{value}"'
                f"{shared._checked_attr(value in config.usb_otg.fleet_trend_metrics)}>"
                f"<span>{label}</span></label>"
            )
            for value, label in (
                ("voltage", "Voltage"),
                ("soc", "SoC"),
                ("temperature", "Temperature"),
            )
        )
        selected_frame_device_ids = set(config.usb_otg.fleet_trend_device_ids)
        use_all_frame_devices = not selected_frame_device_ids
        usb_otg_fleet_device_controls = (
            '<input type="hidden" name="fleet_trend_device_ids" value="">'
            + (
                "".join(
                    _usb_otg_fleet_device_checkbox(
                        device=device,
                        checked=(
                            use_all_frame_devices
                            or str(device.get("id", "")) in selected_frame_device_ids
                        ),
                    )
                    for device in devices
                    if str(device.get("id", "")).strip()
                )
                or (
                    '<div class="inline-field-help">'
                    "Add at least one device before selecting frame devices."
                    "</div>"
                )
            )
        )
        bluetooth_adapter_options = (
            _option_html("auto", "Auto", config.bluetooth.adapter)
            + "".join(
                _option_html(name, name, config.bluetooth.adapter)
                for name in detected_adapter_names
            )
            + (
                ""
                if config.bluetooth.adapter == "auto" or configured_adapter_present
                else _option_html(
                    config.bluetooth.adapter,
                    f"{config.bluetooth.adapter} (missing)",
                    config.bluetooth.adapter,
                )
            )
        )
        gateway_section_body = (
            '<form method="post" action="/settings/gateway">'
            + _poll_interval_warning(config)
            + f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
            + settings_control_row(
                "Gateway name",
                (
                    f'<input id="gateway-name-input" type="text" name="gateway_name" '
                    f'value="{html.escape(config.gateway.name)}" autocomplete="off">'
                ),
                help_text="Set the display name shown across the gateway UI and status views.",
            )
            + settings_control_row(
                "Timezone",
                (
                    '<select id="timezone-input" name="timezone" autocomplete="off" translate="no">'
                    f"{timezone_options}"
                    "</select>"
                ),
                help_text=(
                    "Use an IANA timezone such as Europe/Rome so timestamps render correctly."
                ),
            )
            + settings_control_row(
                "Live polling",
                (
                    '<select id="reader-mode-input" name="reader_mode" autocomplete="off">'
                    f"{reader_mode_options}"
                    "</select>"
                ),
                help_text=(
                    "Choose live to read real devices over Bluetooth, or fake for offline "
                    "UI testing."
                ),
            )
            + settings_control_row(
                "Poll interval",
                (
                    f'<input id="poll-interval-input" type="text" name="poll_interval_seconds" '
                    f'value="{config.gateway.poll_interval_seconds}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text="Set how often the gateway performs a full collection cycle.",
            )
            + settings_control_row(
                "Raw retention",
                (
                    f'<input id="raw-retention-input" type="text" name="raw_retention_days" '
                    f'value="{config.retention.raw_retention_days}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text="Keep detailed raw readings for this many days before pruning.",
            )
            + settings_control_row(
                "Daily rollup retention",
                (
                    f'<input id="daily-retention-input" type="text" name="daily_retention_days" '
                    f'value="{config.retention.daily_retention_days}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text="Use 0 to keep daily summaries indefinitely, or set a day limit.",
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save gateway settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        mqtt_section_body = (
            '<form method="post" action="/settings/mqtt">'
            + settings_control_row(
                "MQTT publishing",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    f'<input type="checkbox" name="mqtt_enabled"'
                    f"{shared._checked_attr(config.mqtt.enabled)}>"
                    "<span>Enable MQTT publishing</span></label>"
                ),
                help_text="Turn this on to publish gateway and device updates to an MQTT broker.",
            )
            + settings_control_row(
                "MQTT broker host",
                (
                    f'<input id="mqtt-host-input" type="text" name="mqtt_host" '
                    f'value="{html.escape(config.mqtt.host)}" autocomplete="off">'
                ),
                help_text="Set the hostname or IP address of the MQTT broker.",
            )
            + settings_control_row(
                "MQTT broker port",
                (
                    f'<input id="mqtt-port-input" type="text" name="mqtt_port" '
                    f'value="{config.mqtt.port}" inputmode="numeric" autocomplete="off">'
                ),
                help_text=(
                    "Use the TCP port exposed by your broker, usually 1883 for unencrypted MQTT."
                ),
            )
            + settings_control_row(
                "MQTT username",
                (
                    f'<input id="mqtt-username-input" type="text" name="mqtt_username" '
                    f'value="{html.escape(config.mqtt.username)}" autocomplete="off">'
                ),
                help_text="Leave blank if your broker allows anonymous connections.",
            )
            + settings_control_row(
                "MQTT password",
                (
                    f'<input id="mqtt-password-input" type="password" name="mqtt_password" '
                    f'value="{html.escape(config.mqtt.password)}" autocomplete="off">'
                ),
                help_text=(
                    "Used only when a username is provided. Leave blank for anonymous brokers."
                ),
            )
            + settings_control_row(
                "MQTT base topic",
                (
                    f'<input id="mqtt-base-topic-input" type="text" name="mqtt_base_topic" '
                    f'value="{html.escape(config.mqtt.base_topic)}" autocomplete="off">'
                ),
                help_text=(
                    "This is the root topic under which gateway and device state messages are "
                    "published."
                ),
            )
            + settings_control_row(
                "MQTT discovery prefix",
                (
                    f'<input id="mqtt-discovery-prefix-input" type="text" '
                    f'name="mqtt_discovery_prefix" '
                    f'value="{html.escape(config.mqtt.discovery_prefix)}" autocomplete="off">'
                ),
                help_text="Home Assistant listens under this prefix for MQTT discovery payloads.",
            )
            + settings_control_row(
                "Retain discovery",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    f'<input type="checkbox" name="mqtt_retain_discovery"'
                    f"{shared._checked_attr(config.mqtt.retain_discovery)}>"
                    "<span>Keep MQTT discovery topics retained</span></label>"
                ),
                help_text=(
                    "Keeps discovery messages on the broker so Home Assistant can rediscover the "
                    "gateway after restarts."
                ),
            )
            + settings_control_row(
                "Retain state",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    f'<input type="checkbox" name="mqtt_retain_state"'
                    f"{shared._checked_attr(config.mqtt.retain_state)}>"
                    "<span>Keep MQTT state topics retained</span></label>"
                ),
                help_text=(
                    "Keeps the last known gateway and battery state on the broker for new "
                    "subscribers."
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save MQTT settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        home_assistant_section_body = (
            '<form method="post" action="/settings/home-assistant">'
            + settings_control_row(
                "Home Assistant MQTT discovery",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="home_assistant_enabled"'
                    f"{shared._checked_attr(config.home_assistant.enabled)}>"
                    "<span>Enable Home Assistant MQTT discovery</span></label>"
                ),
                help_text=(
                    "Publishes Home Assistant-compatible MQTT discovery messages so entities can "
                    "appear automatically."
                ),
            )
            + settings_control_row(
                "Home Assistant status topic",
                (
                    '<input id="home-assistant-status-topic-input" type="text" '
                    f'name="home_assistant_status_topic" '
                    f'value="{html.escape(config.home_assistant.status_topic)}" '
                    'autocomplete="off">'
                ),
                help_text=(
                    "Home Assistant publishes its online status here so the gateway can align "
                    "discovery behavior."
                ),
            )
            + settings_control_row(
                "Home Assistant gateway device id",
                (
                    '<input id="home-assistant-gateway-device-id-input" type="text" '
                    f'name="home_assistant_gateway_device_id" '
                    f'value="{html.escape(config.home_assistant.gateway_device_id)}" '
                    'autocomplete="off">'
                ),
                help_text=(
                    "This becomes the stable device identifier Home Assistant uses for the "
                    "gateway device."
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save Home Assistant settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        web_section_body = (
            '<form method="post" action="/settings/web">'
            '<input type="hidden" name="settings_section" value="web">'
            + settings_control_row(
                "Web interface",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="web_enabled"'
                    f"{shared._checked_attr(config.web.enabled)}>"
                    "<span>Enable web interface</span></label>"
                ),
                help_text=(
                    "Turn this off if you only want CLI and MQTT behavior without the local web UI."
                ),
            )
            + settings_control_row(
                "Host",
                (
                    f'<input id="web-host-input" type="text" name="web_host" '
                    f'value="{html.escape(config.web.host)}" autocomplete="off">'
                ),
                help_text=(
                    "Choose which network interface the web server listens on, for example "
                    "0.0.0.0 or 127.0.0.1."
                ),
            )
            + settings_control_row(
                "Port",
                (
                    f'<input id="web-port-input" type="text" name="web_port" '
                    f'value="{config.web.port}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text="Set the TCP port used by the web UI, such as 80 or 8080.",
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save web service settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        display_section_body = (
            '<form method="post" action="/settings/web">'
            '<input type="hidden" name="settings_section" value="display">'
            + settings_control_row(
                "Chart point markers",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    f'<input id="show-chart-markers-input" type="checkbox" '
                    f'name="show_chart_markers"{shared._checked_attr(config.web.show_chart_markers)}>'
                    "<span>Show chart point markers</span></label>"
                ),
                help_text=(
                    "Turn point markers back on if you prefer exact sample dots "
                    "over the cleaner default BM-style lines."
                ),
            )
            + settings_control_row(
                "Default chart range",
                (
                    '<select id="default-chart-range-input" name="default_chart_range" '
                    'autocomplete="off">'
                    f"{default_chart_range_options}"
                    "</select>"
                ),
                help_text="Choose which retained time window charts should open with by default.",
            )
            + settings_control_row(
                "Default chart metric",
                (
                    '<select id="default-chart-metric-input" name="default_chart_metric" '
                    'autocomplete="off">'
                    f"{default_chart_metric_options}"
                    "</select>"
                ),
                help_text=(
                    "Pick whether charts should open on Voltage, State of Charge, or Temperature."
                ),
            )
            + settings_control_row(
                "Appearance",
                (
                    '<select id="appearance-input" name="appearance" autocomplete="off">'
                    f"{appearance_options}"
                    "</select>"
                ),
                help_text=(
                    "Pick whether the web UI follows the system theme or stays locked to "
                    "light or dark styling."
                ),
            )
            + settings_control_row(
                "Language",
                (
                    '<select id="language-input" name="language" autocomplete="off">'
                    f"{language_options}"
                    "</select>"
                ),
                help_text="Choose the language used by the local web interface.",
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save display settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        archive_sync_section_body = (
            '<form method="post" action="/settings/archive-sync">'
            + settings_control_row(
                "Archive history import",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="archive_sync_enabled"'
                    f"{shared._checked_attr(config.archive_sync.enabled)}>"
                    "<span>Enable periodic onboard history import</span></label>"
                ),
                help_text=(
                    "Imports dense supported-device history periodically and after long "
                    "offline gaps."
                ),
            )
            + settings_control_row(
                "Periodic sync interval",
                (
                    '<input id="archive-periodic-interval-input" type="text" '
                    'name="periodic_interval_seconds" '
                    f'value="{config.archive_sync.periodic_interval_seconds}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text=(
                    "Run a history sync after this many seconds since the latest archive row."
                ),
            )
            + settings_control_row(
                "Reconnect backfill threshold",
                (
                    '<input id="archive-reconnect-gap-input" type="text" '
                    'name="reconnect_min_gap_seconds" '
                    f'value="{config.archive_sync.reconnect_min_gap_seconds}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text=(
                    "When a device returns after at least this many seconds offline, backfill "
                    "the missed interval."
                ),
            )
            + settings_control_row(
                "Safety margin",
                (
                    '<input id="archive-safety-margin-input" type="text" '
                    'name="safety_margin_seconds" '
                    f'value="{config.archive_sync.safety_margin_seconds}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text="Add this many seconds of overlap to avoid gaps at page boundaries.",
            )
            + settings_control_row(
                "BM200 pages per sync",
                (
                    '<input id="archive-bm200-pages-input" type="text" '
                    'name="bm200_max_pages_per_sync" '
                    f'value="{config.archive_sync.bm200_max_pages_per_sync}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text=(
                    "Caps each automatic or manual BM200/BM6 history sync. One page is about "
                    "8 hours and 32 minutes."
                ),
            )
            + settings_control_row(
                "BM300 Pro history import",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="bm300_enabled"'
                    f"{shared._checked_attr(config.archive_sync.bm300_enabled)}>"
                    "<span>Enable BM300 Pro/BM7 history import</span></label>"
                ),
                help_text="Keep BM300 Pro/BM7 archive imports separately gated.",
            )
            + settings_control_row(
                "BM300 pages per sync",
                (
                    '<input id="archive-bm300-pages-input" type="text" '
                    'name="bm300_max_pages_per_sync" '
                    f'value="{config.archive_sync.bm300_max_pages_per_sync}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text=(
                    "Caps each automatic or manual BM300 Pro/BM7 history sync. The configured "
                    "maximum is based on the observed 883-record selector window and the "
                    "advertised 72-day retention."
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save archive sync settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
        usb_otg_section_body = (
            '<form method="post" action="/settings/usb-otg">'
            + usb_otg_install_warning
            + usb_otg_warning
            + _usb_otg_refresh_interval_warning(config)
            + settings_control_row(
                "USB OTG image export",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="usb_otg_enabled"'
                    f"{shared._checked_attr(config.usb_otg.enabled)}"
                    f"{' disabled' if not installed_usb_otg_support else ''}>"
                    "<span>Enable USB OTG image export</span></label>"
                ),
                help_text=(
                    "Expose generated frame images through a Raspberry Pi USB gadget mass "
                    "storage drive. This remains inactive until the USB gadget hardware path "
                    "is available."
                ),
            )
            + _settings_markup_row("USB OTG support", usb_otg_support_badge)
            + _settings_markup_row("USB OTG device controller", usb_otg_controller_badge)
            + settings_control_row(
                "Image width",
                (
                    f'<input id="usb-otg-width-input" type="text" name="image_width_px" '
                    f'value="{config.usb_otg.image_width_px}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text="Set the exported frame image width in pixels.",
            )
            + settings_control_row(
                "Image height",
                (
                    f'<input id="usb-otg-height-input" type="text" name="image_height_px" '
                    f'value="{config.usb_otg.image_height_px}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text="Set the exported frame image height in pixels.",
            )
            + settings_control_row(
                "Image format",
                (
                    '<select id="usb-otg-format-input" name="image_format" autocomplete="off">'
                    f"{usb_otg_format_options}</select>"
                ),
                help_text="JPEG is the safest format for most digital picture frames.",
            )
            + settings_control_row(
                "Frame appearance",
                (
                    '<select id="usb-otg-appearance-input" name="appearance" autocomplete="off">'
                    f"{usb_otg_appearance_options}</select>"
                ),
                help_text="Choose the light or dark visual style for generated frame images.",
            )
            + settings_control_row(
                "Export interval",
                (
                    '<input id="usb-otg-refresh-input" type="text" '
                    'name="refresh_interval_seconds" '
                    f'value="{config.usb_otg.refresh_interval_seconds}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text=(
                    "Use 0 to export after each gateway poll, or set a custom interval in seconds."
                ),
            )
            + settings_control_row(
                "Devices per overview image",
                (
                    '<select id="usb-otg-overview-count-input" '
                    'name="overview_devices_per_image" autocomplete="off">'
                    f"{usb_otg_devices_per_image_options}</select>"
                ),
                help_text="Choose how many batteries can appear on one overview image.",
            )
            + settings_control_row(
                "Battery overview image",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="export_battery_overview"'
                    f"{shared._checked_attr(config.usb_otg.export_battery_overview)}>"
                    "<span>Export battery overview pages</span></label>"
                ),
                help_text="Generate one or more overview images sized for the picture frame.",
            )
            + settings_control_row(
                "Fleet trend image",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="export_fleet_trend"'
                    f"{shared._checked_attr(config.usb_otg.export_fleet_trend)}>"
                    "<span>Export fleet trend chart</span></label>"
                ),
                help_text="Generate a compact fleet trend chart using stored battery history.",
            )
            + settings_control_row(
                "Fleet Trend metrics",
                f'<div class="chip-grid">{usb_otg_fleet_metric_controls}</div>',
                help_text="Choose which chart images the frame export should generate.",
            )
            + settings_control_row(
                "Fleet Trend range",
                (
                    '<select id="usb-otg-fleet-range-input" '
                    'name="fleet_trend_range" autocomplete="off">'
                    f"{usb_otg_fleet_range_options}</select>"
                ),
                help_text="Apply this history window to every selected Fleet Trend chart.",
            )
            + settings_control_row(
                "Frame devices",
                f'<div class="chip-grid">{usb_otg_fleet_device_controls}</div>',
                help_text="Select at least one device to include in generated frame images.",
            )
            + settings_row("Backing disk image", config.usb_otg.image_path)
            + settings_row("Image size", f"{config.usb_otg.size_mb} MB")
            + settings_row("Gadget name", config.usb_otg.gadget_name)
            + '<div style="margin-top:1rem">'
            + f"{button('Save USB OTG settings', kind='primary')}"
            + "</div>"
            + "</form>"
            + '<div class="inline-actions" style="margin-top:1rem">'
            + (
                '<form method="post" action="/actions/restore-usb-host-mode" '
                "onsubmit=\"return confirm('Restore Raspberry Pi USB host boot mode? "
                "A reboot will be required.')\">"
                f"{button('Restore USB Host Mode', kind='secondary')}"
                "</form>"
                if prepared_usb_otg_boot_mode
                else (
                    '<form method="post" action="/actions/prepare-usb-otg-mode" '
                    "onsubmit=\"return confirm('Prepare Raspberry Pi USB OTG peripheral "
                    "boot mode? A reboot will be required.')\">"
                    f"{button('Prepare USB OTG Mode', kind='secondary')}"
                    "</form>"
                    if installed_usb_otg_support
                    else ""
                )
            )
            + "</div>"
        )
        bluetooth_section_body = (
            '<form method="post" action="/settings/bluetooth">'
            + settings_control_row(
                "Adapter",
                (
                    '<select id="bluetooth-adapter-input" name="bluetooth_adapter" '
                    'autocomplete="off">'
                    f"{bluetooth_adapter_options}" + "</select>"
                ),
                help_text=(
                    "No Bluetooth adapters detected on this host."
                    if not detected_adapter_names
                    else (
                        f"Configured adapter {config.bluetooth.adapter} is not currently present."
                        if not configured_adapter_present
                        else f"Detected adapters: {detected_adapter_summary}."
                    )
                ),
            )
            + settings_control_row(
                "Scan timeout",
                (
                    f'<input id="scan-timeout-input" type="text" name="scan_timeout_seconds" '
                    f'value="{config.bluetooth.scan_timeout_seconds}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
                help_text=(
                    "Controls how long the gateway searches for each Bluetooth device before "
                    "giving up."
                ),
            )
            + settings_control_row(
                "Connect timeout",
                (
                    f'<input id="connect-timeout-input" type="text" '
                    f'name="connect_timeout_seconds" '
                    f'value="{config.bluetooth.connect_timeout_seconds}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
                help_text=(
                    "Controls how long the gateway waits for a Bluetooth connection to complete."
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save bluetooth settings', kind='primary')}"
            + "</div>"
            + "</form>"
        )
    body = (
        top_header(
            title="Settings",
            eyebrow="Settings",
            right=(
                '<div class="hero-actions">'
                + (
                    '<a class="secondary-button" href="/settings">Done</a>'
                    if edit_mode
                    else (
                        '<a class="secondary-button" href="/diagnostics">Diagnostics</a>'
                        '<a class="primary-button" href="/settings?edit=1">Edit settings</a>'
                    )
                )
                + "</div>"
            ),
        )
        + banner
        + (
            ""
            if edit_mode
            else section_card(
                title="Gateway Overview",
                body=overview_cards,
            )
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Actions",
                body=actions_body,
            )
        )
        + section_card(
            title="Gateway Settings",
            body=gateway_section_body,
        )
        + section_card(
            title="MQTT Settings",
            body=mqtt_section_body,
        )
        + section_card(
            title="Home Assistant Settings",
            body=home_assistant_section_body,
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Home Assistant MQTT Discovery",
                body=(
                    settings_row("Gateway state topic", gateway_state_topic)
                    + settings_row("Gateway discovery topic", gateway_discovery_topic)
                    + settings_row("Device discovery payloads", str(device_contract_count))
                ),
            )
        )
        + section_card(
            title="Web Service",
            body=web_section_body,
        )
        + section_card(
            title="Display Settings",
            body=display_section_body,
        )
        + section_card(
            title="Archive History Import",
            body=archive_sync_section_body,
        )
        + section_card(
            title="USB OTG Image Export",
            body=usb_otg_section_body,
        )
        + section_card(
            title="Bluetooth",
            body=bluetooth_section_body,
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Storage Summary",
                body=(
                    '<div class="table-shell"><table><thead><tr><th>Device</th><th>Raw samples</th>'
                    "<th>Raw first</th><th>Raw last</th>"
                    "<th>Daily days</th><th>Daily first</th><th>Daily last</th></tr></thead>"
                    "<tbody>"
                    f"{shared._storage_rows(storage_summary, device_ids=configured_device_ids)}"
                    "</tbody></table></div>"
                ),
            )
        )
    )
    if not edit_mode:
        body += section_card(
            title="Configuration Files",
            body=(
                settings_row("Config path", str(config.source_path))
                + settings_row("Device registry path", str(config.device_registry_path))
                + '<div class="config-grid">'
                + (
                    '<div><label class="settings-label" '
                    'for="config-toml-readonly">config.toml</label>'
                )
                + '<textarea id="config-toml-readonly" readonly spellcheck="false">'
                + f"{html.escape(config_text or '')}</textarea></div>"
                + (
                    '<div><label class="settings-label" '
                    'for="devices-toml-readonly">devices.toml</label>'
                )
                + '<textarea id="devices-toml-readonly" readonly spellcheck="false">'
                + f"{html.escape(devices_text or '')}</textarea></div>"
                + "</div>"
            ),
        )
    return app_document(
        title="BMGateway Settings",
        body=body,
        active_nav="settings",
        primary_device_id=primary_device_id,
        version_label=version_label,
        theme_preference=theme_preference,
        language=resolved_language,
    )


def _option_html(value: str, label: str, selected_value: str) -> str:
    safe_value = html.escape(value)
    safe_label = html.escape(label)
    return (
        f'<option value="{safe_value}"'
        f"{shared._selected_attr(value == selected_value)}>"
        f"{safe_label}</option>"
    )


def render_reboot_pending_html(*, theme_preference: str = "system", language: str = "en") -> str:
    polling_script = """
<script>
(() => {
  const startedAt = Date.now();
  const elapsedValue = document.getElementById("reboot-elapsed-seconds");
  const statusValue = document.getElementById("reboot-status-text");
  const detailValue = document.getElementById("reboot-detail-text");
  const updateElapsed = () => {
    if (!elapsedValue) {
      return;
    }
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    elapsedValue.textContent = String(elapsedSeconds);
  };
  const markWaiting = () => {
    if (statusValue) {
      statusValue.textContent = "Gateway is restarting";
    }
    if (detailValue) {
      detailValue.textContent = "Waiting for the Raspberry Pi to come back online...";
    }
  };
  const checkGateway = async () => {
    updateElapsed();
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (response.ok) {
        const message = encodeURIComponent("Raspberry Pi is back online");
        window.location.replace("/settings?message=" + message);
        return;
      }
      markWaiting();
    } catch (_error) {
      markWaiting();
    }
    window.setTimeout(checkGateway, 2500);
  };
  updateElapsed();
  window.setInterval(updateElapsed, 1000);
  window.setTimeout(checkGateway, 1200);
})();
</script>
"""
    body = top_header(
        title="Reboot In Progress",
    ) + section_card(
        title="Gateway Restart",
        body=(
            '<div class="metrics-grid compact-overview-grid">'
            + summary_card(
                "Status",
                "Reboot scheduled",
                subvalue="The reboot command was accepted by the gateway.",
                classes="compact-summary",
            )
            + (
                '<div class="summary-card compact-summary">'
                '<div class="label">Elapsed</div>'
                '<div class="value"><span id="reboot-elapsed-seconds">0</span> s</div>'
                '<div class="subvalue">Updated automatically while waiting.</div>'
                "</div>"
            )
            + "</div>"
            + (
                '<div class="settings-row" style="margin-top:1rem">'
                '<div class="settings-label">Current state</div>'
                '<div class="settings-value" id="reboot-status-text">'
                "Waiting for the reboot to begin"
                "</div>"
                "</div>"
            )
            + ('<div class="section-subtitle" id="reboot-detail-text" style="margin-top:0.75rem">')
            + (
                "This page keeps checking the web interface and redirects "
                "when the gateway is online again."
            )
            + "</div>"
        ),
    )
    return app_document(
        title="BMGateway Reboot",
        body=body,
        active_nav="settings",
        version_label=display_version(),
        theme_preference=theme_preference,
        language=language,
        script=polling_script,
    )


def render_usb_otg_export_pending_html(
    *, theme_preference: str = "system", language: str = "en"
) -> str:
    polling_script = """
<script>
(() => {
  const bar = document.getElementById("usb-otg-export-progress-bar");
  const percentValue = document.getElementById("usb-otg-export-percent");
  const statusValue = document.getElementById("usb-otg-export-status-text");
  const detailValue = document.getElementById("usb-otg-export-detail-text");
  const completedValue = document.getElementById("usb-otg-export-completed");
  const totalValue = document.getElementById("usb-otg-export-total");
  const update = (payload) => {
    const percent = Math.max(0, Math.min(100, Number(payload.percent || 0)));
    if (bar) {
      bar.style.width = `${percent}%`;
      bar.setAttribute("aria-valuenow", String(Math.round(percent)));
    }
    if (percentValue) {
      percentValue.textContent = `${Math.round(percent)}%`;
    }
    if (statusValue && payload.message) {
      statusValue.textContent = payload.message;
    }
    if (detailValue && payload.detail) {
      detailValue.textContent = payload.detail;
    }
    if (completedValue) {
      completedValue.textContent = String(payload.completed || 0);
    }
    if (totalValue) {
      totalValue.textContent = String(payload.total || 0);
    }
  };
  const poll = async () => {
    try {
      const response = await fetch("/api/usb-otg-export/status", { cache: "no-store" });
      if (response.ok) {
        const payload = await response.json();
        update(payload);
        if (payload.status === "completed" || payload.status === "failed") {
          const message = encodeURIComponent(payload.redirect_message || payload.message || "");
          window.setTimeout(() => {
            window.location.replace("/settings?message=" + message);
          }, 900);
          return;
        }
      }
    } catch (_error) {
    }
    window.setTimeout(poll, 900);
  };
  poll();
})();
</script>
"""
    progress_bar = (
        '<div class="soc-progress" style="margin-top:1rem">'
        '<div class="soc-progress-header">'
        '<span class="settings-label">Progress</span>'
        '<span class="soc-progress-value" id="usb-otg-export-percent">0%</span>'
        "</div>"
        '<div class="soc-progress-track" role="progressbar" aria-valuemin="0" '
        'aria-valuemax="100" aria-valuenow="0">'
        '<div class="soc-progress-fill" id="usb-otg-export-progress-bar" '
        'style="width:0%; background:var(--accent-green)"></div>'
        "</div>"
        "</div>"
    )
    body = top_header(title="Frame Image Export") + section_card(
        title="USB OTG image export",
        body=(
            '<div class="metrics-grid compact-overview-grid">'
            + summary_card(
                "Status",
                "Preparing USB OTG frame image export",
                subvalue="Frame images are being generated for the picture frame.",
                classes="compact-summary",
            )
            + (
                '<div class="summary-card compact-summary">'
                '<div class="label">Completed</div>'
                '<div class="value"><span id="usb-otg-export-completed">0</span> / '
                '<span id="usb-otg-export-total">0</span></div>'
                '<div class="subvalue">Updated automatically while waiting.</div>'
                "</div>"
            )
            + "</div>"
            + progress_bar
            + (
                '<div class="settings-row" style="margin-top:1rem">'
                '<div class="settings-label">Export status</div>'
                '<div class="settings-value" id="usb-otg-export-status-text">'
                "Preparing USB OTG frame image export"
                "</div>"
                "</div>"
            )
            + '<div class="section-subtitle" id="usb-otg-export-detail-text" '
            'style="margin-top:0.75rem">'
            + "This page updates automatically and returns to settings when the export finishes."
            + "</div>"
        ),
    )
    return app_document(
        title="Frame Image Export",
        body=body,
        active_nav="settings",
        version_label=display_version(),
        theme_preference=theme_preference,
        language=language,
        script=polling_script,
    )


def render_shutdown_pending_html(*, theme_preference: str = "system", language: str = "en") -> str:
    body = top_header(
        title="Shutdown In Progress",
    ) + section_card(
        title="Gateway Shutdown",
        body=(
            '<div class="metrics-grid compact-overview-grid">'
            + summary_card(
                "Status",
                "Shutdown scheduled",
                subvalue="The shutdown command was accepted by the gateway.",
                classes="compact-summary",
            )
            + "</div>"
            + (
                '<div class="settings-row" style="margin-top:1rem">'
                '<div class="settings-label">Next step</div>'
                '<div class="settings-value">'
                "Wait for the Raspberry Pi activity LED to stop blinking before unplugging power."
                "</div>"
                "</div>"
            )
            + '<div class="section-subtitle" style="margin-top:0.75rem">'
            + (
                "The web interface will stop responding once the host powers off. "
                "Start it again by reconnecting power."
            )
            + "</div>"
        ),
    )
    return app_document(
        title="BMGateway Shutdown",
        body=body,
        active_nav="settings",
        version_label=display_version(),
        theme_preference=theme_preference,
        language=language,
    )
