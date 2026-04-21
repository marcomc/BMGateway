"""Management and settings page rendering for the BMGateway web interface."""

from __future__ import annotations

import html
from typing import cast

from . import display_version
from . import web_pages as shared
from .config import AppConfig
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
    theme_preference: str = "system",
) -> str:
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
    contract = contract or {}
    detected_bluetooth_adapters = (
        shared._discover_bluetooth_adapters()
        if detected_bluetooth_adapters is None
        else detected_bluetooth_adapters
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
        '<form method="post" action="/actions/restart-runtime">'
        f"{button('Restart bm-gateway service', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/restart-bluetooth-service">'
        f"{button('Restart Bluetooth service', kind='secondary')}"
        "</form>"
        '<form method="post" action="/actions/reboot-host">'
        f"{button('Reboot Raspberry Pi', kind='secondary')}"
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
        + settings_row("Visible overview cards", str(config.web.visible_device_limit))
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
    )
    bluetooth_section_body = (
        settings_row("Adapter", config.bluetooth.adapter)
        + settings_row("Detected adapters", detected_adapter_summary)
        + settings_row("Adapter status", adapter_status)
        + settings_row("Scan timeout", f"{config.bluetooth.scan_timeout_seconds} seconds")
        + settings_row("Connect timeout", f"{config.bluetooth.connect_timeout_seconds} seconds")
    )
    gateway_section_body = (
        f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
        + settings_row("Gateway name", config.gateway.name)
        + settings_row("Timezone", config.gateway.timezone)
        + settings_row("Live polling", config.gateway.reader_mode)
        + settings_row("Poll interval", f"{config.gateway.poll_interval_seconds} seconds")
        + settings_row("MQTT", "Enabled" if config.mqtt.enabled else "Disabled")
        + settings_row(
            "Home Assistant",
            "Enabled" if config.home_assistant.enabled else "Disabled",
        )
        + settings_row("Raw retention", f"{config.retention.raw_retention_days} days")
        + settings_row("Daily rollup retention", daily_retention)
    )
    if edit_mode:
        reader_mode_options = "".join(
            _option_html(value, value, config.gateway.reader_mode) for value in ("fake", "live")
        )
        visible_device_limit_options = "".join(
            _option_html(str(value), str(value), str(config.web.visible_device_limit))
            for value in (2, 4, 6, 8)
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
            + f'<div class="chip-grid" style="margin-bottom:1rem">{device_tabs}</div>'
            + settings_control_row(
                "Gateway name",
                (
                    f'<input id="gateway-name-input" type="text" name="gateway_name" '
                    f'value="{html.escape(config.gateway.name)}" autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Timezone",
                (
                    f'<input id="timezone-input" type="text" name="timezone" '
                    f'value="{html.escape(config.gateway.timezone)}" autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Live polling",
                (
                    '<select id="reader-mode-input" name="reader_mode" autocomplete="off">'
                    f"{reader_mode_options}"
                    "</select>"
                ),
            )
            + settings_control_row(
                "Poll interval",
                (
                    f'<input id="poll-interval-input" type="text" name="poll_interval_seconds" '
                    f'value="{config.gateway.poll_interval_seconds}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + settings_control_row(
                "MQTT",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    f'<input type="checkbox" name="mqtt_enabled"'
                    f"{shared._checked_attr(config.mqtt.enabled)}>"
                    "<span>Enable MQTT publishing</span></label>"
                ),
            )
            + settings_control_row(
                "Home Assistant",
                (
                    f'<label class="settings-value" style="{shared.TOGGLE_LABEL_STYLE}">'
                    '<input type="checkbox" name="home_assistant_enabled"'
                    f"{shared._checked_attr(config.home_assistant.enabled)}>"
                    "<span>Enable Home Assistant contract</span></label>"
                ),
            )
            + settings_control_row(
                "Raw retention",
                (
                    f'<input id="raw-retention-input" type="text" name="raw_retention_days" '
                    f'value="{config.retention.raw_retention_days}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Daily rollup retention",
                (
                    f'<input id="daily-retention-input" type="text" name="daily_retention_days" '
                    f'value="{config.retention.daily_retention_days}" inputmode="numeric" '
                    'autocomplete="off">'
                ),
            )
            + '<div style="margin-top:1rem">'
            + f"{button('Save gateway settings', kind='primary')}"
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
            )
            + settings_control_row(
                "Host",
                (
                    f'<input id="web-host-input" type="text" name="web_host" '
                    f'value="{html.escape(config.web.host)}" autocomplete="off">'
                ),
            )
            + settings_control_row(
                "Port",
                (
                    f'<input id="web-port-input" type="text" name="web_port" '
                    f'value="{config.web.port}" '
                    'inputmode="numeric" autocomplete="off">'
                ),
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
                "Visible overview cards",
                (
                    '<select id="visible-device-limit-input" name="visible_device_limit" '
                    'autocomplete="off">'
                    f"{visible_device_limit_options}"
                    "</select>"
                ),
                help_text=(
                    "Choose how many monitored batteries stay visible before the "
                    "overview pages horizontally on larger fleets."
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
            + '<div style="margin-top:1rem">'
            + f"{button('Save display settings', kind='primary')}"
            + "</div>"
            + "</form>"
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
            )
            + settings_control_row(
                "Connect timeout",
                (
                    f'<input id="connect-timeout-input" type="text" '
                    f'name="connect_timeout_seconds" '
                    f'value="{config.bluetooth.connect_timeout_seconds}" '
                    'inputmode="numeric" autocomplete="off">'
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
            subtitle=(
                "Read the current gateway configuration first, then unlock the "
                "same page when you want to edit it."
            ),
            eyebrow="Settings",
            right=(
                '<div class="hero-actions">'
                + (
                    '<a class="secondary-button" href="/settings">Done</a>'
                    if edit_mode
                    else '<a class="primary-button" href="/settings?edit=1">Edit settings</a>'
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
                subtitle="Operational Surfaces",
                body=overview_cards,
            )
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Actions",
                subtitle=(
                    "Run the collector, prune retained history, and inspect the live JSON APIs."
                ),
                body=actions_body,
            )
        )
        + section_card(
            title="Gateway Settings",
            subtitle="Current runtime and integration summary",
            body=gateway_section_body,
        )
        + section_card(
            title="Web Service",
            subtitle="Current management UI binding",
            body=web_section_body,
        )
        + section_card(
            title="Display Settings",
            subtitle="Current chart rendering preferences",
            body=display_section_body,
        )
        + section_card(
            title="Bluetooth",
            subtitle="Adapter selection and BLE timeout tuning.",
            body=bluetooth_section_body,
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Home Assistant Contract",
                subtitle=(
                    "Keep the MQTT surface easy to scan without losing the exact "
                    "state and discovery topics."
                ),
                body=(
                    settings_row("Gateway state topic", gateway_state_topic)
                    + settings_row("Gateway discovery topic", gateway_discovery_topic)
                    + settings_row("Device discovery payloads", str(device_contract_count))
                ),
            )
        )
        + (
            ""
            if edit_mode
            else section_card(
                title="Storage Summary",
                subtitle=(
                    "Recent raw samples and long-term rollups stay available, but "
                    "the page emphasizes storage posture first."
                ),
                body=(
                    '<div class="table-shell"><table><thead><tr><th>Device</th><th>Raw samples</th>'
                    "<th>Raw first</th><th>Raw last</th>"
                    "<th>Daily days</th><th>Daily first</th><th>Daily last</th></tr></thead>"
                    f"<tbody>{shared._storage_rows(storage_summary)}</tbody></table></div>"
                ),
            )
        )
    )
    if not edit_mode:
        body += section_card(
            title="Configuration Files",
            subtitle="Reference paths and raw configuration snapshots.",
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
    )


def _option_html(value: str, label: str, selected_value: str) -> str:
    safe_value = html.escape(value)
    safe_label = html.escape(label)
    return (
        f'<option value="{safe_value}"'
        f"{shared._selected_attr(value == selected_value)}>"
        f"{safe_label}</option>"
    )


def render_reboot_pending_html(*, theme_preference: str = "system") -> str:
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
        eyebrow="Settings",
        title="Reboot In Progress",
        subtitle=(
            "The Raspberry Pi is restarting. Keep this page open and it will return "
            "to Settings automatically when the gateway responds again."
        ),
    ) + section_card(
        title="Gateway Restart",
        subtitle="Automatic status checks run every few seconds.",
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
        script=polling_script,
    )
