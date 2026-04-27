"""History and device detail page rendering for the BMGateway web interface."""

from __future__ import annotations

import html
from typing import cast
from urllib.parse import quote

from . import display_version
from . import web_pages as shared
from .web_ui import (
    app_document,
    banner_strip,
    button,
    chart_card,
    chart_script,
    section_card,
    summary_card,
    top_header,
)


def render_history_sync_pending_html(
    *, theme_preference: str = "system", language: str = "en"
) -> str:
    polling_script = """
<script>
(() => {
  const bar = document.getElementById("history-sync-progress-bar");
  const percentValue = document.getElementById("history-sync-percent");
  const statusValue = document.getElementById("history-sync-status-text");
  const detailValue = document.getElementById("history-sync-detail-text");
  const completedValue = document.getElementById("history-sync-completed");
  const totalValue = document.getElementById("history-sync-total");
  const update = (payload) => {
    const total = Number(payload.total || 0);
    const completed = Number(payload.completed || 0);
    const percent = total > 0 ? Math.max(0, Math.min(100, Number(payload.percent || 0))) : 0;
    if (bar) {
      bar.style.width = `${percent}%`;
      bar.setAttribute("aria-valuenow", String(Math.round(percent)));
    }
    if (percentValue) {
      percentValue.textContent = total > 0 ? `${Math.round(percent)}%` : "0%";
    }
    if (statusValue && payload.message) {
      statusValue.textContent = payload.message;
    }
    if (detailValue && payload.detail) {
      detailValue.textContent = payload.detail;
    }
    if (completedValue) {
      completedValue.textContent = String(completed);
    }
    if (totalValue) {
      totalValue.textContent = String(total);
    }
  };
  const poll = async () => {
    try {
      const response = await fetch("/api/history-sync/status", { cache: "no-store" });
      if (response.ok) {
        const payload = await response.json();
        update(payload);
        if (payload.status === "completed" || payload.status === "failed") {
          const params = new URLSearchParams();
          if (payload.device_id) {
            params.set("device_id", payload.device_id);
          }
          params.set("message", payload.redirect_message || payload.message || "");
          window.setTimeout(() => {
            window.location.replace("/history?" + params.toString());
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
        '<span class="soc-progress-value" id="history-sync-percent">0%</span>'
        "</div>"
        '<div class="soc-progress-track" role="progressbar" aria-valuemin="0" '
        'aria-valuemax="100" aria-valuenow="0">'
        '<div class="soc-progress-fill" id="history-sync-progress-bar" '
        'style="width:0%; background:var(--accent-green)"></div>'
        "</div>"
        "</div>"
    )
    body = top_header(title="History Sync") + section_card(
        title="History import",
        body=(
            '<div class="metrics-grid compact-overview-grid">'
            + summary_card(
                "Status",
                "Preparing history download",
                subvalue="History records are being downloaded from the selected monitor.",
                classes="compact-summary",
            )
            + (
                '<div class="summary-card compact-summary">'
                '<div class="label">Records</div>'
                '<div class="value"><span id="history-sync-completed">0</span> / '
                '<span id="history-sync-total">0</span></div>'
                '<div class="subvalue">Updated automatically while waiting.</div>'
                "</div>"
            )
            + "</div>"
            + progress_bar
            + (
                '<div class="settings-row" style="margin-top:1rem">'
                '<div class="settings-label">History import status</div>'
                '<div class="settings-value" id="history-sync-status-text">'
                "Preparing history download"
                "</div>"
                "</div>"
            )
            + '<div class="section-subtitle" id="history-sync-detail-text" '
            'style="margin-top:0.75rem">'
            + "This page updates automatically and returns to history when the import finishes."
            + "</div>"
        ),
    )
    return app_document(
        title="History Sync",
        body=body,
        active_nav="history",
        version_label=display_version(),
        theme_preference=theme_preference,
        language=language,
        script=polling_script,
    )


def render_device_html(
    *,
    device_id: str,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
    yearly_history: list[dict[str, object]],
    analytics: dict[str, object],
    device_summary: dict[str, object] | None = None,
    show_chart_markers: bool = False,
    theme_preference: str = "system",
    default_chart_range: str = "7",
    default_chart_metric: str = "soc",
    language: str = "en",
) -> str:
    version_label = display_version()
    resolved_default_chart_range = shared._sanitize_default_chart_range(default_chart_range)
    summary = shared._device_summary_from_history(
        device_id=device_id,
        raw_history=raw_history,
        daily_history=daily_history,
        device_summary=device_summary,
    )
    trend_rows = "\n".join(
        (
            "<tr>"
            f"<td>{window['days']}</td>"
            f"<td>{window['current_avg_voltage']}</td>"
            f"<td>{window['previous_avg_voltage']}</td>"
            f"<td>{window['delta_avg_voltage']}</td>"
            f"<td>{window['current_avg_soc']}</td>"
            f"<td>{window['previous_avg_soc']}</td>"
            f"<td>{window['delta_avg_soc']}</td>"
            "</tr>"
        )
        for window in cast(list[dict[str, object]], analytics.get("windows", []))
    )
    yearly_rows = "\n".join(
        (
            "<tr>"
            f"<td>{row['year']}</td><td>{row['samples']}</td>"
            f"<td>{row['avg_voltage']}</td><td>{row['avg_soc']}</td>"
            f"<td>{row['error_count']}</td>"
            "</tr>"
        )
        for row in yearly_history
    )
    trend_rows_html = trend_rows or "<tr><td colspan='7'>No comparison windows</td></tr>"
    yearly_rows_html = yearly_rows or "<tr><td colspan='5'>No yearly data</td></tr>"
    history_sections = _render_history_sections(
        raw_history=raw_history,
        daily_history=daily_history,
        monthly_history=monthly_history,
    )
    vehicle_text = html.escape(shared._vehicle_summary(summary))
    battery_meta_text = html.escape(shared._battery_metadata_summary(summary).replace(" · ", " "))
    chart_id = f"device-chart-{quote(device_id)}".replace("%", "")
    device_name = str(summary.get("name", device_id))
    device_color = shared._device_accent_color(summary)
    battery_meta_summary = shared._battery_metadata_summary(summary).replace(" · ", " ")
    vehicle_summary = shared._vehicle_summary(summary)
    subtitle_lines: list[str] = []
    if battery_meta_summary and battery_meta_summary != "Battery details not set":
        subtitle_lines.append(battery_meta_summary)
    if vehicle_summary and vehicle_summary != "Not set":
        subtitle_lines.append(vehicle_summary)
    body = (
        top_header(
            title=device_name,
            subtitle_lines=subtitle_lines,
            right=(
                '<div class="hero-actions">'
                f'<a class="secondary-button" href="/devices/edit?device_id={quote(device_id)}">'
                "Edit device</a></div>"
            ),
        )
        + section_card(
            title="Battery Status",
            body=shared._device_status_explainer(summary, accent_css=device_color),
        )
        + section_card(
            title="Runtime Status",
            body=(
                '<div class="metrics-grid">'
                + summary_card(
                    "Last Seen",
                    shared._display_timestamp(summary.get("last_seen", "unknown")),
                    classes="timestamp-summary",
                )
                + summary_card("Vehicle", vehicle_text)
                + summary_card(
                    "Battery Metadata",
                    battery_meta_text,
                    classes="timestamp-summary metadata-summary",
                )
                + summary_card(
                    "Error Code",
                    html.escape(str(summary.get("error_code", "None"))),
                    subvalue=html.escape(
                        str(summary.get("error_detail", "No current driver/runtime error"))
                    ),
                )
                + summary_card("Connection", "Connected" if summary.get("connected") else "Offline")
                + "</div>"
            ),
        )
        + chart_card(
            chart_id=chart_id,
            title="Historical Chart",
            subtitle="",
            points=shared._chart_points(
                raw_history,
                daily_history,
                series=device_name,
                series_color=device_color,
            ),
            range_options=shared._visible_chart_range_options(),
            default_range=resolved_default_chart_range,
            default_metric=default_chart_metric,
            legend=[(device_name, device_color)],
            show_markers=show_chart_markers,
        )
        + section_card(
            title="Trend Windows",
            body=(
                '<div class="table-shell"><table><thead><tr><th>Days</th><th>Current Avg V</th>'
                "<th>Previous Avg V</th><th>Delta V</th>"
                "<th>Current Avg SoC</th><th>Previous Avg SoC</th><th>Delta SoC</th></tr></thead>"
                f"<tbody>{trend_rows_html}</tbody></table></div>"
            ),
        )
        + section_card(
            title="Yearly Summary",
            body=(
                '<div class="table-shell"><table><thead><tr><th>Year</th><th>Samples</th>'
                "<th>Avg V</th><th>Avg SoC</th><th>Error Count</th></tr></thead>"
                f"<tbody>{yearly_rows_html}</tbody></table></div>"
            ),
        )
        + history_sections
    )
    return app_document(
        title=f"{device_name} Device",
        body=body,
        active_nav="home",
        version_label=version_label,
        theme_preference=theme_preference,
        language=language,
        script=chart_script(chart_id, language=language or "en"),
    )


def render_history_html(
    *,
    device_id: str,
    configured_devices: list[dict[str, object]],
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
    show_chart_markers: bool = False,
    theme_preference: str = "system",
    default_chart_range: str = "7",
    default_chart_metric: str = "soc",
    language: str = "en",
    message: str = "",
) -> str:
    version_label = display_version()
    resolved_default_chart_range = shared._sanitize_default_chart_range(default_chart_range)
    sections = _render_history_sections(
        raw_history=raw_history,
        daily_history=daily_history,
        monthly_history=monthly_history,
    )
    escaped_device_id = html.escape(device_id)
    summary = shared._history_summary(raw_history)
    chart_id = f"history-chart-{quote(device_id)}".replace("%", "")
    selected_device = cast(
        dict[str, object],
        next(
            (device for device in configured_devices if str(device.get("id", "")) == device_id),
            {"id": device_id},
        ),
    )
    history_color = shared._device_accent_color(selected_device)
    history_series = str(selected_device.get("name") or device_id)
    escaped_device_id_value = html.escape(device_id, quote=True)
    history_sync_action = (
        '<form method="post" action="/actions/sync-device-history">'
        f'<input type="hidden" name="device_id" value="{escaped_device_id_value}">'
        f"{button('Download History', kind='secondary')}"
        "</form>"
        if device_id
        else ""
    )
    banner = banner_strip(html.escape(message), kind="warning") if message else ""
    body = (
        top_header(
            title="History",
            eyebrow="History",
        )
        + banner
        + shared._history_device_selector_html(
            configured_devices=configured_devices,
            selected_device_id=device_id,
        )
        + section_card(
            title="Summary",
            body=(
                '<div class="metrics-grid">'
                + summary_card("Valid samples", summary["valid_samples"])
                + summary_card("Error count", summary["error_count"])
                + summary_card("Average voltage", summary["avg_voltage"])
                + summary_card("Average SoC", summary["avg_soc"])
                + "</div>"
            ),
        )
        + chart_card(
            chart_id=chart_id,
            title="History Chart",
            subtitle="",
            points=shared._chart_points(
                raw_history,
                daily_history,
                series=history_series,
                series_color=history_color,
            ),
            range_options=shared._visible_chart_range_options(),
            default_range=resolved_default_chart_range,
            default_metric=default_chart_metric,
            legend=[(history_series, history_color)],
            show_markers=show_chart_markers,
            actions_html=history_sync_action,
        )
        + sections
    )
    return app_document(
        title=f"{escaped_device_id} History",
        body=body,
        active_nav="history",
        version_label=version_label,
        theme_preference=theme_preference,
        language=language,
        script=chart_script(chart_id, language=language or "en")
        + shared._history_device_selector_script(),
    )


def _render_history_sections(
    *,
    raw_history: list[dict[str, object]],
    daily_history: list[dict[str, object]],
    monthly_history: list[dict[str, object]],
) -> str:
    visible_raw_history = raw_history[:300]
    raw_rows = "\n".join(
        "<tr>"
        f"<td>{shared._escape_cell(row['ts'])}</td>"
        f"<td>{shared._escape_cell(row['voltage'])}</td>"
        f"<td>{shared._escape_cell(row['soc'])}</td>"
        f"<td>{shared._escape_cell(row.get('temperature', '-'))}</td>"
        f"<td>{shared._escape_cell(row['state'])}</td>"
        f"<td>{_error_cell(row)}</td>"
        "</tr>"
        for row in visible_raw_history
    )
    daily_rows = "\n".join(
        "<tr>"
        f"<td>{shared._escape_cell(row['day'])}</td>"
        f"<td>{shared._escape_cell(row['samples'])}</td>"
        f"<td>{shared._escape_cell(row['min_voltage'])}</td>"
        f"<td>{shared._escape_cell(row['max_voltage'])}</td>"
        f"<td>{shared._escape_cell(row['avg_voltage'])}</td>"
        f"<td>{shared._escape_cell(row['avg_soc'])}</td>"
        f"<td>{shared._escape_cell(row.get('avg_temperature', '-'))}</td>"
        f"<td>{shared._escape_cell(row['error_count'])}</td>"
        "</tr>"
        for row in daily_history
    )
    monthly_rows = "\n".join(
        "<tr>"
        f"<td>{shared._escape_cell(row['month'])}</td>"
        f"<td>{shared._escape_cell(row['samples'])}</td>"
        f"<td>{shared._escape_cell(row['min_voltage'])}</td>"
        f"<td>{shared._escape_cell(row['max_voltage'])}</td>"
        f"<td>{shared._escape_cell(row['avg_voltage'])}</td>"
        f"<td>{shared._escape_cell(row['avg_soc'])}</td>"
        f"<td>{shared._escape_cell(row.get('avg_temperature', '-'))}</td>"
        f"<td>{shared._escape_cell(row['error_count'])}</td>"
        "</tr>"
        for row in monthly_history
    )
    raw_rows_html = raw_rows or "<tr><td colspan='6'>No data</td></tr>"
    daily_rows_html = daily_rows or "<tr><td colspan='8'>No data</td></tr>"
    monthly_rows_html = monthly_rows or "<tr><td colspan='8'>No data</td></tr>"
    return (
        section_card(
            title="Recent Raw Readings",
            subtitle=(
                "Raw rows stay available, but tucked behind a lower-priority "
                "operational panel so chart insight leads the page."
            ),
            body=(
                '<div class="raw-table-shell"><details open><summary class="settings-label">'
                "Raw readings table</summary>"
                '<div class="table-shell raw-readings-scroll">'
                '<table class="raw-readings-table"><thead><tr><th>Time</th><th>V</th>'
                "<th>SoC</th><th>Temp</th><th>State</th><th>Err</th></tr></thead>"
                f"<tbody>{raw_rows_html}</tbody></table></div></details></div>"
            ),
        )
        + section_card(
            title="Daily Rollups",
            body=(
                '<div class="table-shell"><table><thead><tr><th>Day</th><th>Samples</th>'
                "<th>Min V</th><th>Max V</th>"
                "<th>Avg V</th><th>Avg SoC</th><th>Avg Temp</th><th>Error count</th></tr></thead>"
                f"<tbody>{daily_rows_html}</tbody></table></div>"
            ),
        )
        + section_card(
            title="Monthly Summaries",
            body=(
                '<div class="table-shell"><table><thead><tr><th>Month</th><th>Samples</th>'
                "<th>Min V</th><th>Max V</th>"
                "<th>Avg V</th><th>Avg SoC</th><th>Avg Temp</th><th>Error count</th></tr></thead>"
                f"<tbody>{monthly_rows_html}</tbody></table></div>"
            ),
        )
    )


def _error_cell(row: dict[str, object]) -> str:
    error_code = row.get("error_code")
    return shared._escape_cell(error_code) if error_code is not None else "-"
