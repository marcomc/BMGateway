"""Reusable server-rendered UI primitives for the BMGateway web interface."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
from typing import Iterable


def _join_classes(*values: str) -> str:
    return " ".join(value for value in values if value)


def app_document(
    *,
    title: str,
    body: str,
    active_nav: str = "battery",
    primary_device_id: str = "",
    head_extra: str = "",
    script: str = "",
) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    <style>
{base_css()}
    </style>
    {head_extra}
  </head>
  <body>
    <div class="app-shell">
      <a class="skip-link" href="#main-content">Skip to main content</a>
      <main class="page-shell" id="main-content">
        {body}
      </main>
      {bottom_nav(active_nav, primary_device_id=primary_device_id)}
    </div>
    {script}
  </body>
</html>
"""


def base_css() -> str:
    return """
:root {
  --bg-app: #e9edf3;
  --bg-header-start: #dfeaf5;
  --bg-header-end: #eef7ef;
  --bg-surface: #ffffff;
  --bg-surface-soft: #f6f9fd;
  --bg-elevated: #fbfdff;
  --bg-chart: #f7f9fc;
  --bg-muted: #dde4ee;
  --text-primary: #111827;
  --text-secondary: #526071;
  --text-soft: #8995a6;
  --accent-green: #17c45a;
  --accent-green-soft: #c8f0cb;
  --accent-blue: #4f8df7;
  --accent-blue-soft: #d4e4fb;
  --accent-purple: #9a57f5;
  --accent-purple-soft: #e5d3fb;
  --accent-orange: #f4a340;
  --accent-orange-soft: #f8e2d5;
  --accent-mint: #7ee3c9;
  --accent-yellow-soft: #efe3b8;
  --accent-red: #ff4d57;
  --state-ok: #17c45a;
  --state-warning: #f59e0b;
  --state-error: #ef4444;
  --state-offline: #95a3b8;
  --border-soft: #d7e0ea;
  --border-muted: #c6d0dc;
  --shadow-card: 0 8px 24px rgba(33, 48, 73, 0.06);
  --shadow-elevated: 0 14px 36px rgba(33, 48, 73, 0.1);
  --shadow-glow: 0 0 34px rgba(23, 196, 90, 0.25);
  --radius-sm: 10px;
  --radius-md: 14px;
  --radius-lg: 18px;
  --radius-xl: 24px;
  --radius-pill: 999px;
}

* { box-sizing: border-box; }
html, body { min-height: 100%; }
body {
  margin: 0;
  background: var(--bg-app);
  color: var(--text-primary);
  font-family: Inter, "SF Pro Display", "SF Pro Text", ui-sans-serif, system-ui, sans-serif;
}
a { color: var(--accent-blue); text-decoration: none; }
a:hover { text-decoration: underline; }
button, input, select, textarea { font: inherit; }
button { cursor: pointer; }
a,
button,
summary,
input,
select,
textarea {
  touch-action: manipulation;
}
a:focus-visible,
button:focus-visible,
summary:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible {
  outline: 3px solid rgba(79, 141, 247, 0.9);
  outline-offset: 3px;
}
.skip-link {
  position: absolute;
  top: 1rem;
  left: 1rem;
  z-index: 40;
  padding: 0.75rem 1rem;
  border-radius: var(--radius-md);
  background: var(--text-primary);
  color: #fff;
  transform: translateY(-200%);
  transition: transform 120ms ease;
}
.skip-link:hover {
  text-decoration: none;
}
.skip-link:focus-visible {
  transform: translateY(0);
}
code {
  background: var(--bg-surface-soft);
  padding: 0.14rem 0.38rem;
  border-radius: 7px;
  font-size: 0.92rem;
}
textarea,
input[type="text"],
select {
  width: 100%;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  color: var(--text-primary);
}
textarea {
  min-height: 22rem;
  padding: 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.45;
}
input[type="text"], select {
  padding: 0.82rem 0.9rem;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: transparent;
}
th, td {
  padding: 0.9rem 0.85rem;
  border-bottom: 1px solid var(--border-soft);
  text-align: left;
  vertical-align: top;
}
thead th {
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
tbody tr:hover { background: rgba(79, 141, 247, 0.045); }
details summary {
  cursor: pointer;
  list-style: none;
}
details summary::-webkit-details-marker { display: none; }
.app-shell {
  min-height: 100vh;
  background:
    radial-gradient(circle at top left, rgba(126, 227, 201, 0.16), transparent 32%),
    linear-gradient(180deg, var(--bg-app) 0%, #eef2f7 100%);
}
.page-shell {
  margin: 0 auto;
  max-width: 1280px;
  padding: 1.4rem 1rem 5.7rem;
}
.top-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.1rem;
  padding: 1.45rem;
  border-radius: var(--radius-xl);
  background: linear-gradient(135deg, var(--bg-header-start) 0%, var(--bg-header-end) 100%);
  box-shadow: var(--shadow-card);
}
.top-header h1 {
  margin: 0;
  font-size: clamp(2rem, 4vw, 2.8rem);
  line-height: 1.02;
}
.top-header p {
  margin: 0.4rem 0 0;
  color: var(--text-secondary);
  line-height: 1.5;
}
.eyebrow {
  display: inline-block;
  margin-bottom: 0.65rem;
  color: var(--accent-green);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.hero-actions,
.inline-actions,
.tab-strip,
.range-strip,
.chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.hero-actions > *,
.inline-actions > *,
.tab-strip > *,
.range-strip > *,
.chip-grid > *,
.footer-row > *,
.top-header > *,
.section-title-row > *,
.settings-row > *,
.history-controls > * {
  min-width: 0;
}
.panel,
.section-card {
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.95);
  box-shadow: var(--shadow-card);
}
.section-card {
  padding: 1.2rem;
  margin-bottom: 1rem;
}
.section-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.section-title {
  margin: 0;
  font-size: 1.28rem;
}
.section-subtitle {
  margin-top: 0.35rem;
  color: var(--text-secondary);
  line-height: 1.45;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 1rem;
}
.summary-card,
.metric-tile,
.device-card,
.tone-card {
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.summary-card {
  padding: 1rem 1.05rem;
  background: var(--bg-surface);
  border: 1px solid var(--border-soft);
}
.summary-card .label,
.metric-tile .label {
  color: var(--text-secondary);
  font-size: 0.88rem;
  font-weight: 600;
}
.summary-card .value {
  margin-top: 0.35rem;
  font-size: clamp(1.8rem, 5vw, 2.5rem);
  font-weight: 800;
  line-height: 1;
}
.summary-card .subvalue,
.metric-tile .subvalue {
  margin-top: 0.55rem;
  color: var(--text-soft);
  font-size: 0.86rem;
}
.metric-tile {
  min-height: 148px;
  padding: 1.1rem 1.1rem 1rem;
}
.metric-tile .value {
  margin-top: 0.5rem;
  font-size: clamp(1.7rem, 4vw, 2.4rem);
  font-weight: 800;
  line-height: 1.05;
}
.metric-tile.blue { background: var(--accent-blue-soft); }
.metric-tile.green { background: #d9f4e8; }
.metric-tile.purple { background: #eddcfb; }
.metric-tile.orange { background: var(--accent-orange-soft); }
.metric-tile.yellow { background: var(--accent-yellow-soft); }
.control-plane {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1.45fr 1fr;
}
.control-plane .panel {
  padding: 1.3rem;
}
.device-grid,
.two-column-grid,
.config-grid {
  display: grid;
  gap: 1rem;
}
.device-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.two-column-grid { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.config-grid { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.device-card,
.tone-card {
  position: relative;
  overflow: hidden;
  padding: 1rem;
  border: 1px solid rgba(255, 255, 255, 0.5);
}
.tone-card.green { background: var(--accent-green-soft); }
.tone-card.purple { background: var(--accent-purple-soft); }
.tone-card.blue { background: var(--accent-blue-soft); }
.tone-card.orange { background: var(--accent-yellow-soft); }
.device-card h3,
.tone-card h3 {
  margin: 0;
  font-size: 1.15rem;
}
.device-card .hero-soc {
  margin: 0.7rem 0 0.4rem;
  font-size: clamp(2.5rem, 6vw, 3.5rem);
  font-weight: 800;
}
.device-card .meta {
  color: var(--text-secondary);
  font-size: 0.95rem;
}
.device-card .footer-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem 1rem;
  margin-top: 0.8rem;
  color: var(--text-secondary);
}
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.34rem 0.75rem;
  border-radius: var(--radius-pill);
  font-size: 0.86rem;
  font-weight: 700;
}
.status-badge.ok { background: rgba(23, 196, 90, 0.12); color: var(--state-ok); }
.status-badge.warning { background: rgba(245, 158, 11, 0.12); color: var(--state-warning); }
.status-badge.error { background: rgba(239, 68, 68, 0.12); color: var(--state-error); }
.status-badge.offline { background: rgba(149, 163, 184, 0.18); color: var(--state-offline); }
.banner-strip {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.95rem 1rem;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(246,249,253,0.95));
}
.banner-strip.warning {
  border-color: rgba(245, 158, 11, 0.3);
  background: linear-gradient(180deg, rgba(255,248,235,0.98), rgba(255,252,245,0.95));
}
.api-chip,
.pill-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.52rem 0.8rem;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  background: var(--bg-surface-soft);
  color: var(--text-secondary);
}
.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.9rem 0;
  border-bottom: 1px solid var(--border-soft);
}
.settings-row:last-child { border-bottom: 0; }
.settings-label {
  font-weight: 700;
}
.settings-value {
  color: var(--text-secondary);
  text-align: right;
}
.primary-button,
.secondary-button,
.ghost-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 46px;
  padding: 0.78rem 1rem;
  border-radius: var(--radius-md);
  border: 0;
  font-weight: 700;
  text-decoration: none;
  transition:
    background-color 120ms ease,
    border-color 120ms ease,
    box-shadow 120ms ease,
    color 120ms ease,
    transform 120ms ease;
}
.primary-button {
  background: var(--accent-green);
  color: #fff;
  box-shadow: var(--shadow-card);
}
.primary-button:hover {
  background: #12ad4f;
  text-decoration: none;
  transform: translateY(-1px);
}
.secondary-button {
  background: var(--bg-surface-soft);
  color: var(--text-primary);
  border: 1px solid var(--border-soft);
}
.secondary-button:hover {
  background: #edf3fa;
  text-decoration: none;
  transform: translateY(-1px);
}
.ghost-button {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-soft);
}
.ghost-button:hover {
  background: rgba(255, 255, 255, 0.72);
  color: var(--text-primary);
  text-decoration: none;
}
.control-segment {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding: 0.28rem;
  border-radius: var(--radius-pill);
  background: rgba(221, 229, 240, 0.95);
}
.control-segment button {
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-primary);
  padding: 0.6rem 0.95rem;
  font-weight: 700;
}
.control-segment button.active {
  background: var(--accent-green);
  color: #fff;
  box-shadow: var(--shadow-card);
}
.history-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.chart-card {
  padding: 1rem;
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--shadow-card);
}
.chart-frame {
  min-height: 320px;
  padding: 1rem;
  border-radius: var(--radius-lg);
  background: var(--bg-chart);
}
.chart-empty {
  display: flex;
  min-height: 280px;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem 1rem;
  margin-bottom: 0.9rem;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--text-secondary);
  font-size: 0.92rem;
  font-weight: 600;
}
.legend-swatch {
  width: 12px;
  height: 12px;
  border-radius: 999px;
}
.chart-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem 1rem;
  margin-top: 0.85rem;
  color: var(--text-secondary);
  font-size: 0.92rem;
}
.hero-shell {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1.1fr 0.95fr;
}
.soc-gauge-card {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360px;
  padding: 1.4rem;
}
.soc-gauge {
  position: relative;
  width: min(100%, 360px);
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  box-shadow: var(--shadow-glow);
}
.soc-gauge::after {
  content: "";
  position: absolute;
  inset: 11%;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, #ffffff 0%, #ffffff 56%, #eff8f1 57%, #f8fbff 100%);
}
.soc-gauge-content {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.soc-gauge-label {
  color: var(--text-secondary);
  font-size: 1.55rem;
}
.soc-gauge-value {
  font-size: clamp(3.4rem, 8vw, 5.4rem);
  font-weight: 800;
  line-height: 1;
}
.hero-aside {
  display: grid;
  gap: 1rem;
}
.table-shell {
  overflow-x: auto;
}
.table-caption {
  margin-bottom: 0.75rem;
  color: var(--text-secondary);
}
.raw-table-shell details > div {
  margin-top: 0.8rem;
}
.error-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.52rem;
  border-radius: var(--radius-pill);
  background: rgba(239, 68, 68, 0.12);
  color: var(--state-error);
  font-size: 0.8rem;
  font-weight: 700;
}
.muted-note {
  color: var(--text-secondary);
  line-height: 1.5;
}
.bottom-nav {
  position: fixed;
  inset-inline: 0;
  bottom: 0;
  z-index: 20;
  border-top: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
}
.bottom-nav-inner {
  display: flex;
  align-items: center;
  justify-content: space-around;
  gap: 0.75rem;
  max-width: 780px;
  margin: 0 auto;
  padding: 0.75rem 1rem;
}
.nav-link {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 0.28rem;
  min-width: 88px;
  color: var(--text-soft);
  font-size: 0.82rem;
  font-weight: 700;
}
.nav-link.active { color: var(--accent-green); }
.nav-link:hover { text-decoration: none; color: var(--text-primary); }
@media (prefers-reduced-motion: reduce) {
  .skip-link,
  .primary-button,
  .secondary-button,
  .ghost-button {
    transition: none;
  }
  html:focus-within {
    scroll-behavior: auto;
  }
}
@media (max-width: 960px) {
  .control-plane,
  .hero-shell {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .page-shell { padding: 1rem 0.8rem 5.8rem; }
  .top-header { padding: 1.1rem; }
  .section-card { padding: 1rem; }
}
"""


def top_header(
    *,
    title: str,
    subtitle: str = "",
    eyebrow: str = "",
    right: str = "",
) -> str:
    eyebrow_html = f'<div class="eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else ""
    subtitle_html = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    return (
        '<header class="top-header">'
        "<div>"
        f"{eyebrow_html}"
        f"<h1>{html.escape(title)}</h1>"
        f"{subtitle_html}"
        "</div>"
        f"{right}"
        "</header>"
    )


def section_card(
    *,
    title: str = "",
    subtitle: str = "",
    body: str,
    right: str = "",
    classes: str = "",
) -> str:
    if title:
        header = (
            '<div class="section-title-row">'
            "<div>"
            f'<h2 class="section-title">{html.escape(title)}</h2>'
            f'<div class="section-subtitle">{html.escape(subtitle)}</div>'
            if subtitle
            else ""
        )
        if subtitle:
            header += "</div>"
        else:
            header += "</div>"
        header += f"{right}</div>"
    else:
        header = ""
    return f'<section class="{_join_classes("section-card", classes)}">{header}{body}</section>'


def summary_card(label: str, value: str, *, subvalue: str = "", classes: str = "") -> str:
    subvalue_html = f'<div class="subvalue">{html.escape(subvalue)}</div>' if subvalue else ""
    return (
        f'<div class="{_join_classes("summary-card", classes)}">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        f"{subvalue_html}"
        "</div>"
    )


def metric_tile(
    *,
    label: str,
    value: str,
    tone: str = "blue",
    subvalue: str = "",
) -> str:
    subvalue_html = f'<div class="subvalue">{html.escape(subvalue)}</div>' if subvalue else ""
    return (
        f'<div class="metric-tile {html.escape(tone)}">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        f"{subvalue_html}"
        "</div>"
    )


def status_badge(label: str, *, kind: str) -> str:
    return f'<span class="status-badge {html.escape(kind)}">{html.escape(label)}</span>'


def api_chip(label: str) -> str:
    return f'<span class="api-chip">{html.escape(label)}</span>'


def button(label: str, *, kind: str = "primary", button_type: str = "submit") -> str:
    class_name = {
        "primary": "primary-button",
        "secondary": "secondary-button",
        "ghost": "ghost-button",
    }[kind]
    return f'<button class="{class_name}" type="{html.escape(button_type)}">{html.escape(label)}</button>'


def settings_row(label: str, value: str) -> str:
    return (
        '<div class="settings-row">'
        f'<div class="settings-label">{html.escape(label)}</div>'
        f'<div class="settings-value">{html.escape(value)}</div>'
        "</div>"
    )


def banner_strip(message: str, *, kind: str = "warning", trailing: str = "") -> str:
    return (
        f'<div class="banner-strip {html.escape(kind)}" role="status" aria-live="polite">'
        f"<div>{message}</div>{trailing}</div>"
    )


def tone_card(body: str, *, tone: str) -> str:
    return f'<article class="tone-card {html.escape(tone)}">{body}</article>'


def bottom_nav(active_nav: str, *, primary_device_id: str = "") -> str:
    history_href = "/history"
    if primary_device_id:
        history_href = f"/history?device_id={html.escape(primary_device_id)}"
    items = [
        ("battery", "/", "Battery"),
        ("history", history_href, "History"),
        ("devices", "/devices", "Devices"),
        ("settings", "/settings", "Settings"),
    ]
    links = []
    for item_id, href, label in items:
        classes = "nav-link active" if active_nav == item_id else "nav-link"
        links.append(f'<a class="{classes}" href="{href}"><span>{html.escape(label)}</span></a>')
    return (
        '<nav class="bottom-nav" aria-label="Primary">'
        f'<div class="bottom-nav-inner">{"".join(links)}</div></nav>'
    )


def chart_card(
    *,
    chart_id: str,
    title: str,
    subtitle: str,
    points: list[dict[str, object]],
    range_options: Iterable[tuple[str, str]],
    default_range: str,
    default_metric: str,
    legend: list[tuple[str, str]],
) -> str:
    points_json = html.escape(json.dumps(points, separators=(",", ":")))
    legend_html = "".join(
        '<span class="legend-item">'
        f'<span class="legend-swatch" style="background:{html.escape(color)}"></span>'
        f"{html.escape(label)}"
        "</span>"
        for label, color in legend
    )
    range_buttons = "".join(
        (
            f'<button type="button" data-range="{html.escape(value)}" '
            f'class="{"active" if value == default_range else ""}">'
            f"{html.escape(label)}</button>"
        )
        for value, label in range_options
    )
    metric_buttons = "".join(
        (
            f'<button type="button" data-metric="{html.escape(value)}" '
            f'class="{"active" if value == default_metric else ""}">'
            f"{html.escape(label)}"
            "</button>"
        )
        for value, label in (
            ("voltage", "Voltage"),
            ("soc", "SoC"),
            ("temperature", "Temperature"),
        )
    )
    return (
        '<section class="chart-card">'
        '<div class="section-title-row">'
        "<div>"
        f'<h2 class="section-title">{html.escape(title)}</h2>'
        f'<div class="section-subtitle">{html.escape(subtitle)}</div>'
        "</div>"
        '<div class="history-controls">'
        f'<div class="control-segment range-strip">{range_buttons}</div>'
        f'<div class="control-segment tab-strip">{metric_buttons}</div>'
        "</div>"
        "</div>"
        f'<div class="chart-legend">{legend_html}</div>'
        f'<div class="chart-frame" id="{html.escape(chart_id)}" data-chart-points="{points_json}"></div>'
        f'<div class="chart-meta" id="{html.escape(chart_id)}-meta"></div>'
        "</section>"
    )


def chart_script(*chart_ids: str) -> str:
    ids = json.dumps(list(chart_ids))
    return f"""
<script>
(() => {{
  const chartIds = {ids};
  const METRICS = {{
    voltage: {{ label: "Voltage", color: "#4f8df7", format: (value) => `${{value.toFixed(2)}} V` }},
    soc: {{ label: "SoC", color: "#17c45a", format: (value) => `${{value.toFixed(0)}}%` }},
    temperature: {{ label: "Temperature", color: "#9a57f5", format: (value) => `${{value.toFixed(1)}} C` }},
  }};
  function parseTime(value) {{
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
  }}
  function pickRange(points, rangeValue) {{
    if (rangeValue === "raw") {{
      return points.filter((point) => point.kind === "raw");
    }}
    const days = parseInt(rangeValue, 10);
    if (Number.isNaN(days)) {{
      return points;
    }}
    const timestamps = points.map((point) => parseTime(point.ts)).filter((point) => point !== null);
    const latest = timestamps.length > 0 ? Math.max(...timestamps) : null;
    if (latest === null) {{
      return points;
    }}
    const cutoff = latest - (days * 24 * 60 * 60 * 1000);
    return points.filter((point) => {{
      const parsed = parseTime(point.ts);
      return parsed !== null && parsed >= cutoff;
    }});
  }}
  function buildSvg(points, metric) {{
    const usable = points.filter((point) => typeof point[metric] === "number");
    if (usable.length === 0) {{
      return '<div class="chart-empty">No ' + METRICS[metric].label + ' data available in this range.</div>';
    }}
    const width = 960;
    const height = 320;
    const padLeft = 64;
    const padRight = 20;
    const padTop = 12;
    const padBottom = 36;
    const values = usable.map((point) => point[metric]);
    let minValue = Math.min(...values);
    let maxValue = Math.max(...values);
    if (minValue === maxValue) {{
      minValue -= 1;
      maxValue += 1;
    }}
    const span = maxValue - minValue;
    const start = parseTime(usable[0].ts) ?? 0;
    const end = parseTime(usable[usable.length - 1].ts) ?? start + 1;
    const xSpan = Math.max(end - start, 1);
    const plotWidth = width - padLeft - padRight;
    const plotHeight = height - padTop - padBottom;
    const coords = usable.map((point, index) => {{
      const time = parseTime(point.ts) ?? (start + index);
      const x = padLeft + ((time - start) / xSpan) * plotWidth;
      const y = padTop + (1 - ((point[metric] - minValue) / span)) * plotHeight;
      return {{
        x,
        y,
        label: point.label || point.ts,
        value: point[metric],
      }};
    }});
    const line = coords.map((point) => `${{point.x.toFixed(1)}},${{point.y.toFixed(1)}}`).join(" ");
    const area = `${{padLeft}},${{height - padBottom}} ` + line + ` ${{coords[coords.length - 1].x.toFixed(1)}},${{height - padBottom}}`;
    const grid = Array.from({{ length: 5 }}, (_, index) => {{
      const y = padTop + ((plotHeight / 4) * index);
      const labelValue = maxValue - ((span / 4) * index);
      return `\n<line x1="${{padLeft}}" y1="${{y.toFixed(1)}}" x2="${{width - padRight}}" y2="${{y.toFixed(1)}}" stroke="#c0cad7" stroke-width="1"/>\n<text x="8" y="${{(y + 4).toFixed(1)}}" fill="#7c8797" font-size="12">${{labelValue.toFixed(metric === 'soc' ? 0 : 1)}}</text>`;
    }}).join("");
    const xLabels = coords.filter((_, index) => index === 0 || index === coords.length - 1 || index === Math.floor(coords.length / 2)).map((point) => `\n<text x="${{point.x.toFixed(1)}}" y="${{height - 10}}" text-anchor="middle" fill="#7c8797" font-size="12">${{point.label}}</text>`).join("");
    const dots = coords.map((point) => `<circle cx="${{point.x.toFixed(1)}}" cy="${{point.y.toFixed(1)}}" r="4" fill="${{METRICS[metric].color}}" />`).join("");
    return `<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="${{METRICS[metric].label}} chart">\n<rect x="0" y="0" width="${{width}}" height="${{height}}" rx="20" fill="#f7f9fc"/>\n${{grid}}\n<polyline fill="${{METRICS[metric].color}}22" stroke="none" points="${{area}}" />\n<polyline fill="none" stroke="${{METRICS[metric].color}}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${{line}}" />\n${{dots}}\n${{xLabels}}\n</svg>`;
  }}
  function initChart(id) {{
    const frame = document.getElementById(id);
    const meta = document.getElementById(id + "-meta");
    if (!frame || !meta) {{
      return;
    }}
    const allPoints = JSON.parse(frame.dataset.chartPoints || "[]");
    const card = frame.closest(".chart-card");
    if (!card) {{
      return;
    }}
    const rangeButtons = Array.from(card.querySelectorAll("[data-range]"));
    const metricButtons = Array.from(card.querySelectorAll("[data-metric]"));
    let currentRange = rangeButtons.find((button) => button.classList.contains("active"))?.dataset.range || "30";
    let currentMetric = metricButtons.find((button) => button.classList.contains("active"))?.dataset.metric || "voltage";
    function render() {{
      const points = pickRange(allPoints, currentRange);
      frame.innerHTML = buildSvg(points, currentMetric);
      const usable = points.filter((point) => typeof point[currentMetric] === "number");
      if (usable.length === 0) {{
        meta.innerHTML = '<span>No usable samples</span>';
        return;
      }}
      const values = usable.map((point) => point[currentMetric]);
      const average = values.reduce((sum, value) => sum + value, 0) / values.length;
      meta.innerHTML = [
        `<span>${{METRICS[currentMetric].label}} samples: ${{usable.length}}</span>`,
        `<span>Average: ${{METRICS[currentMetric].format(average)}}</span>`,
        `<span>Range: ${{METRICS[currentMetric].format(Math.min(...values))}} - ${{METRICS[currentMetric].format(Math.max(...values))}}</span>`
      ].join("");
    }}
    for (const button of rangeButtons) {{
      button.addEventListener("click", () => {{
        currentRange = button.dataset.range || currentRange;
        for (const candidate of rangeButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        render();
      }});
    }}
    for (const button of metricButtons) {{
      button.addEventListener("click", () => {{
        currentMetric = button.dataset.metric || currentMetric;
        for (const candidate of metricButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        render();
      }});
    }}
    render();
  }}
  for (const chartId of chartIds) {{
    initChart(chartId);
  }}
}})();
</script>
"""
