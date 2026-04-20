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
    version_label: str = "",
    head_extra: str = "",
    script: str = "",
) -> str:
    version_badge = (
        f'<div class="app-version-badge" translate="no">{html.escape(version_label)}</div>'
        if version_label
        else ""
    )
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
      {version_badge}
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
.app-version-badge {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 30;
  padding: 0.42rem 0.72rem;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: var(--shadow-card);
  color: var(--text-secondary);
  font-size: 0.8rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  backdrop-filter: blur(10px);
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
  text-wrap: balance;
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
  text-wrap: balance;
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
  font-variant-numeric: tabular-nums;
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
  font-variant-numeric: tabular-nums;
}
.metric-detail-stack {
  display: grid;
  gap: 0.32rem;
  margin-top: 0.6rem;
}
.signal-quality-row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  color: var(--text-secondary);
  font-size: 0.92rem;
  font-weight: 700;
}
.signal-bars {
  display: inline-flex;
  align-items: flex-end;
  gap: 0.2rem;
  height: 1rem;
}
.signal-bars span {
  width: 0.28rem;
  border-radius: 999px;
  background: rgba(82, 96, 113, 0.24);
}
.signal-bars span.active {
  background: var(--accent-green);
}
.signal-bars span:nth-child(1) { height: 0.34rem; }
.signal-bars span:nth-child(2) { height: 0.52rem; }
.signal-bars span:nth-child(3) { height: 0.72rem; }
.signal-bars span:nth-child(4) { height: 0.9rem; }
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
.device-card-head {
  display: flex;
  align-items: flex-start;
  gap: 0.9rem;
}
.battery-card-head {
  gap: 1rem;
  align-items: flex-start;
}
.history-device-card {
  display: block;
  min-height: 170px;
  color: inherit;
  text-decoration: none;
}
.history-device-card:hover {
  text-decoration: none;
}
.history-device-card.selected {
  box-shadow: var(--shadow-elevated);
}
.history-device-current {
  margin-top: 0.7rem;
  font-weight: 700;
  color: var(--text-primary);
}
.device-card-copy {
  min-width: 0;
  flex: 1 1 auto;
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
  font-variant-numeric: tabular-nums;
}
.battery-overview-card {
  min-height: 300px;
  padding: 1.15rem;
}
.battery-card-gauge {
  position: relative;
  flex: 0 0 112px;
  width: 112px;
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  box-shadow: var(--shadow-glow);
}
.battery-card-gauge::after {
  content: "";
  position: absolute;
  inset: 12%;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, #ffffff 0%, #ffffff 56%, #eff8f1 57%, #f8fbff 100%);
}
.battery-card-gauge-content {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.battery-card-gauge-label {
  color: var(--text-secondary);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.battery-card-gauge-value {
  font-size: clamp(1.8rem, 5vw, 2.5rem);
  font-weight: 800;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.battery-overview-card .meta-name {
  color: var(--text-primary);
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.08;
}
.battery-overview-card .meta-context {
  margin-top: 0.15rem;
  font-size: 0.88rem;
}
.battery-overview-card .battery-card-reading {
  margin-top: 0.55rem;
  color: var(--text-primary);
  font-size: 1.05rem;
  font-weight: 600;
}
.battery-overview-card .battery-card-meta-extra {
  margin-top: 0.24rem;
  font-size: 0.84rem;
}
.battery-card-status {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.55rem;
  color: var(--text-secondary);
  font-size: 0.96rem;
  font-weight: 700;
}
.battery-card-status.ok { color: var(--state-ok); }
.battery-card-status.charging { color: var(--accent-blue); }
.battery-card-status.warning { color: var(--state-warning); }
.battery-card-status.error { color: var(--state-error); }
.battery-card-status.offline { color: var(--state-offline); }
.battery-card-status-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}
.hero-device-icon {
  flex: 0 0 clamp(88px, 18vw, 112px);
  width: clamp(88px, 18vw, 112px);
  height: clamp(88px, 18vw, 112px);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.62);
}
.hero-device-icon .device-icon-svg {
  width: clamp(58px, 12vw, 76px);
  height: clamp(58px, 12vw, 76px);
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
.device-icon-frame {
  display: grid;
  place-items: center;
  flex: 0 0 72px;
  width: 72px;
  height: 72px;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  background: rgba(255, 255, 255, 0.52);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72), var(--shadow-card);
}
.device-icon-svg {
  width: 48px;
  height: 48px;
  color: rgba(17, 24, 39, 0.78);
}
.device-icon-svg .fill-soft {
  fill: rgba(255, 255, 255, 0.45);
}
.device-icon-svg .stroke-main {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.6;
}
.device-icon-svg .stroke-accent {
  fill: none;
  stroke: rgba(23, 196, 90, 0.88);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.6;
}
.device-icon-svg .fill-accent {
  fill: rgba(23, 196, 90, 0.16);
  stroke: rgba(23, 196, 90, 0.88);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.2;
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
.status-explainer {
  margin-bottom: 1rem;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,253,0.95));
  box-shadow: var(--shadow-card);
}
.status-explainer-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
}
.status-explainer-value {
  margin-top: 0.2rem;
  font-size: 1.35rem;
  font-weight: 800;
}
.status-explainer-body {
  display: grid;
  gap: 0.9rem;
  padding: 0 1rem 1rem;
}
.status-explainer-copy {
  margin: 0;
  color: var(--text-secondary);
}
.status-chip-grid {
  gap: 0.7rem;
}
.status-scale {
  display: grid;
  gap: 0.75rem;
}
.status-scale-track {
  position: relative;
  min-height: 22px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: rgba(221, 229, 240, 0.55);
}
.status-scale-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: var(--radius-pill);
  opacity: 0.85;
}
.status-scale-fill.tone-ok { background: linear-gradient(90deg, rgba(23, 196, 90, 0.72), rgba(23, 196, 90, 0.9)); }
.status-scale-fill.tone-warning { background: linear-gradient(90deg, rgba(245, 158, 11, 0.72), rgba(245, 158, 11, 0.9)); }
.status-scale-fill.tone-error { background: linear-gradient(90deg, rgba(239, 68, 68, 0.72), rgba(239, 68, 68, 0.9)); }
.status-scale-fill.tone-info { background: linear-gradient(90deg, rgba(79, 141, 247, 0.72), rgba(79, 141, 247, 0.9)); }
.status-scale-fill.tone-purple { background: linear-gradient(90deg, rgba(155, 120, 255, 0.72), rgba(155, 120, 255, 0.9)); }
.status-scale-marker {
  position: absolute;
  top: 50%;
  width: 16px;
  height: 16px;
  border: 3px solid #fff;
  border-radius: 999px;
  box-shadow: var(--shadow-card);
  transform: translate(-50%, -50%);
}
.status-scale-marker.tone-ok { background: var(--accent-green); }
.status-scale-marker.tone-warning { background: #f59e0b; }
.status-scale-marker.tone-error { background: #ef4444; }
.status-scale-marker.tone-info { background: #4f8df7; }
.status-scale-marker.tone-purple { background: #9b78ff; }
.status-scale-labels {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.55rem;
}
.status-scale-segment {
  display: grid;
  gap: 0.3rem;
  justify-items: center;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.78rem;
  font-weight: 700;
}
.status-scale-segment span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  width: 100%;
  border-radius: 999px;
  padding: 0.4rem 0.45rem;
  border: 1px solid rgba(215, 224, 234, 0.95);
  background: rgba(255, 255, 255, 0.9);
}
.status-scale-segment.reached span {
  color: var(--text-primary);
}
.status-scale-segment.active span {
  box-shadow: var(--shadow-card);
  transform: translateY(-1px);
}
.status-scale-segment.tone-ok span { background: rgba(23, 196, 90, 0.1); }
.status-scale-segment.tone-warning span { background: rgba(245, 158, 11, 0.12); }
.status-scale-segment.tone-error span { background: rgba(239, 68, 68, 0.12); }
.status-scale-segment.tone-info span { background: rgba(79, 141, 247, 0.12); }
.status-scale-segment.tone-purple span { background: rgba(155, 120, 255, 0.14); }
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
.settings-control {
  flex: 0 1 360px;
  width: min(100%, 360px);
}
.settings-control .settings-value {
  text-align: left;
}
.settings-control .inline-field-help {
  margin-top: 0.4rem;
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
  flex-wrap: nowrap;
  gap: 0.35rem;
  padding: 0.28rem;
  border-radius: var(--radius-pill);
  background: rgba(221, 229, 240, 0.95);
}
.control-rail {
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 0.1rem;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}
.control-rail::-webkit-scrollbar {
  display: none;
}
.control-segment button {
  flex: 0 0 auto;
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-primary);
  padding: 0.6rem 0.95rem;
  font-weight: 700;
  white-space: nowrap;
}
.control-segment button.active {
  background: var(--accent-green);
  color: #fff;
  box-shadow: var(--shadow-card);
}
.history-controls {
  display: grid;
  justify-items: end;
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
  position: relative;
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
  font-variant-numeric: tabular-nums;
}
.chart-tooltip {
  position: absolute;
  z-index: 2;
  min-width: 170px;
  padding: 0.75rem 0.85rem;
  border: 1px solid rgba(215, 224, 234, 0.95);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--shadow-elevated);
  color: var(--text-primary);
  font-size: 0.88rem;
  line-height: 1.4;
  pointer-events: none;
  opacity: 0;
  transform: translate(-50%, calc(-100% - 16px));
  transition: opacity 120ms ease;
  backdrop-filter: blur(14px);
}
.chart-tooltip.visible {
  opacity: 1;
}
.chart-tooltip .tooltip-label {
  color: var(--text-secondary);
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.chart-tooltip .tooltip-value {
  margin-top: 0.25rem;
  font-size: 1.15rem;
  font-weight: 800;
}
.chart-tooltip .tooltip-detail {
  margin-top: 0.2rem;
  color: var(--text-secondary);
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
  font-variant-numeric: tabular-nums;
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
.battery-form-section {
  display: grid;
  gap: 0.9rem;
  padding: 1rem;
  border-radius: var(--radius-lg);
  background: rgba(244, 248, 252, 0.9);
  border: 1px solid var(--border-soft);
}
.battery-form-grid {
  display: grid;
  gap: 0.7rem;
}
.icon-picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 0.75rem;
}
.icon-picker-card {
  position: relative;
  display: block;
}
.icon-picker-card input {
  position: absolute;
  inset: 0;
  opacity: 0;
}
.icon-picker-surface {
  display: grid;
  gap: 0.55rem;
  justify-items: center;
  min-height: 148px;
  padding: 0.85rem 0.75rem;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-soft);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: var(--shadow-card);
  transition:
    border-color 120ms ease,
    background-color 120ms ease,
    box-shadow 120ms ease,
    transform 120ms ease;
}
.icon-picker-card:hover .icon-picker-surface {
  transform: translateY(-1px);
}
.icon-picker-card input:checked + .icon-picker-surface {
  border-color: rgba(23, 196, 90, 0.5);
  background: linear-gradient(180deg, rgba(245, 255, 247, 0.98), rgba(233, 250, 238, 0.95));
  box-shadow: var(--shadow-glow);
}
.icon-picker-card input:focus-visible + .icon-picker-surface {
  outline: 3px solid rgba(79, 141, 247, 0.9);
  outline-offset: 3px;
}
.icon-picker-label {
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-weight: 700;
  line-height: 1.3;
  text-align: center;
}
.curve-grid {
  display: grid;
  gap: 0.6rem;
}
.curve-grid-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 0.8rem;
  align-items: center;
}
.curve-grid-row .settings-label {
  margin: 0;
}
.inline-field-help {
  color: var(--text-secondary);
  font-size: 0.9rem;
  line-height: 1.5;
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
.nav-icon {
  width: 24px;
  height: 24px;
  color: currentColor;
}
.nav-icon .stroke-main {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.3;
}
.nav-icon .fill-main {
  fill: currentColor;
  fill-opacity: 0.14;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}
.nav-label {
  line-height: 1;
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
  .battery-overview-card {
    min-height: 272px;
  }
  .battery-card-gauge {
    flex-basis: 96px;
    width: 96px;
  }
  .status-explainer-summary {
    align-items: flex-start;
    flex-direction: column;
  }
  .status-scale-labels {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .history-controls {
    justify-items: stretch;
  }
  .control-rail {
    width: 100%;
  }
  .curve-grid-row {
    grid-template-columns: 72px minmax(0, 1fr);
    gap: 0.65rem;
  }
  .app-version-badge {
    top: 0.75rem;
    right: 0.75rem;
    max-width: calc(100vw - 1.5rem);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
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
    detail_html: str = "",
) -> str:
    subvalue_html = f'<div class="subvalue">{html.escape(subvalue)}</div>' if subvalue else ""
    return (
        f'<div class="metric-tile {html.escape(tone)}">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        f"{detail_html}"
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


def settings_control_row(label: str, control_html: str, *, help_text: str = "") -> str:
    help_markup = (
        f'<div class="inline-field-help">{html.escape(help_text)}</div>' if help_text else ""
    )
    return (
        '<div class="settings-row">'
        f'<div class="settings-label">{html.escape(label)}</div>'
        f'<div class="settings-control">{control_html}{help_markup}</div>'
        "</div>"
    )


def banner_strip(message: str, *, kind: str = "warning", trailing: str = "") -> str:
    return (
        f'<div class="banner-strip {html.escape(kind)}" role="status" aria-live="polite">'
        f"<div>{message}</div>{trailing}</div>"
    )


def tone_card(body: str, *, tone: str, extra_class: str = "") -> str:
    class_name = _join_classes("tone-card", html.escape(tone), extra_class)
    return f'<article class="{class_name}">{body}</article>'


def device_icon(icon_key: str, *, label: str, frame_class: str = "") -> str:
    safe_key = html.escape(icon_key)
    safe_label = html.escape(label)
    class_name = _join_classes("device-icon-frame", frame_class)
    return (
        f'<div class="{class_name}" data-icon-key="{safe_key}" aria-hidden="true">'
        f"{_device_icon_svg(icon_key, label=safe_label)}"
        "</div>"
    )


def icon_picker_option(icon_key: str, *, label: str, checked: bool = False) -> str:
    checked_attr = " checked" if checked else ""
    safe_key = html.escape(icon_key)
    safe_label = html.escape(label)
    return (
        '<label class="icon-picker-card">'
        f'<input type="radio" name="icon_key" value="{safe_key}"{checked_attr}>'
        '<span class="icon-picker-surface">'
        f"{device_icon(icon_key, label=label)}"
        f'<span class="icon-picker-label">{safe_label}</span>'
        "</span>"
        "</label>"
    )


def _device_icon_svg(icon_key: str, *, label: str) -> str:
    title = f"<title>{label}</title>"
    if icon_key == "car_12v":
        content = """
<path class="stroke-main" d="M14 38h36l-3-9c-.7-2.2-2.7-3.6-5-3.6H22c-2.3 0-4.3 1.4-5 3.6z"/>
<path class="stroke-main" d="M12 38h40v7H12z"/>
<circle class="fill-soft" cx="21" cy="45" r="4.5"/>
<circle class="fill-soft" cx="43" cy="45" r="4.5"/>
<path class="stroke-accent" d="M31 18v9m-4.5-4.5h9"/>
"""
    elif icon_key == "motorcycle_12v":
        content = """
<circle class="fill-soft" cx="20" cy="44" r="6"/>
<circle class="fill-soft" cx="45" cy="44" r="6"/>
<path class="stroke-main" d="M20 44h10l6-10h7"/>
<path class="stroke-main" d="M32 34h-6l-5-7h7l4 7"/>
<path class="stroke-main" d="M42 26h6"/>
<path class="stroke-accent" d="M46 18v8m-4-4h8"/>
"""
    elif icon_key == "lead_acid_battery":
        content = """
<rect class="fill-soft" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M22 33c3.5-4 6.5-4 10 0s6.5 4 10 0"/>
<path class="stroke-accent" d="M32 26v14"/>
"""
    elif icon_key == "agm_battery":
        content = """
<rect class="fill-soft" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M24 39l8-13 8 13h-16z"/>
<path class="stroke-accent" d="M32 29v6"/>
"""
    elif icon_key == "efb_battery":
        content = """
<rect class="fill-soft" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M22 29h20M22 35h20M22 41h20"/>
<path class="stroke-accent" d="M27 24v5"/>
"""
    elif icon_key == "gel_battery":
        content = """
<rect class="fill-soft" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="fill-accent" d="M32 25c-3 4-5 7-5 10.2A5 5 0 0037 35c0-3.2-2-6.2-5-10z"/>
"""
    elif icon_key == "lithium_battery":
        content = """
<rect class="fill-soft" x="20" y="12" width="24" height="40" rx="8"/>
<path class="stroke-main" d="M28 12V8h8v4"/>
<path class="stroke-accent" d="M34 22l-5 9h4l-3 10 8-12h-4l4-7z"/>
"""
    elif icon_key == "custom_battery":
        content = """
<rect class="fill-soft" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M21 39c5-7 8-5 11-8s5-4 11-4"/>
<circle class="fill-accent" cx="24" cy="35" r="2.5"/>
<circle class="fill-accent" cx="33" cy="31" r="2.5"/>
<circle class="fill-accent" cx="42" cy="27" r="2.5"/>
"""
    else:
        content = """
<rect class="fill-soft" x="15" y="18" width="34" height="30" rx="7"/>
<path class="stroke-main" d="M23 18v-4h6v4m6 0v-4h6v4"/>
<path class="stroke-main" d="M24 32h16"/>
<path class="stroke-accent" d="M32 24v16"/>
"""
    return (
        '<svg class="device-icon-svg" viewBox="0 0 64 64" fill="none" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="'
        f"{label}"
        '">'
        f"{title}{content}</svg>"
    )


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
        current = ' aria-current="page"' if active_nav == item_id else ""
        links.append(
            f'<a class="{classes}" href="{href}"{current}>'
            f"{_nav_icon(item_id, label=label)}"
            f'<span class="nav-label">{html.escape(label)}</span>'
            "</a>"
        )
    return (
        '<nav class="bottom-nav" aria-label="Primary">'
        f'<div class="bottom-nav-inner">{"".join(links)}</div></nav>'
    )


def _nav_icon(item_id: str, *, label: str) -> str:
    if item_id == "battery":
        body = """
<rect class="fill-main" x="6" y="8" width="12" height="10" rx="2.2"/>
<path class="stroke-main" d="M10 8V6h4v2m-2 2v6"/>
<path class="stroke-main" d="M15 10h4v6a2 2 0 01-2 2h-2"/>
"""
    elif item_id == "history":
        body = """
<path class="stroke-main" d="M5 18h14"/>
<path class="stroke-main" d="M7 18V7h10v11"/>
<path class="stroke-main" d="M9 14l2-2 2 1 3-4"/>
"""
    elif item_id == "devices":
        body = """
<rect class="stroke-main" x="5.5" y="6.5" width="14" height="3.5" rx="1.2"/>
<rect class="stroke-main" x="5.5" y="11.5" width="14" height="3.5" rx="1.2"/>
<rect class="stroke-main" x="5.5" y="16.5" width="14" height="3.5" rx="1.2"/>
"""
    else:
        body = """
<circle class="stroke-main" cx="12" cy="12" r="3.5"/>
<path class="stroke-main" d="M12 4.5v2.2m0 10.6v2.2M4.5 12h2.2m10.6 0h2.2M6.9 6.9l1.6 1.6m7 7l1.6 1.6m0-10.2l-1.6 1.6m-7 7l-1.6 1.6"/>
"""
    return (
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-hidden="true">'
        f"<title>{html.escape(label)}</title>{body}</svg>"
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
    show_markers: bool = False,
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
            f'data-range-label="{html.escape(label)}" '
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
        f'<div class="control-rail"><div class="control-segment range-strip">{range_buttons}</div></div>'
        f'<div class="control-rail"><div class="control-segment tab-strip">{metric_buttons}</div></div>'
        "</div>"
        "</div>"
        f'<div class="chart-legend">{legend_html}</div>'
        f'<div class="chart-frame" id="{html.escape(chart_id)}" '
        f'data-chart-points="{points_json}" '
        f'data-show-markers="{str(show_markers).lower()}">'
        '<div class="chart-tooltip" aria-hidden="true"></div>'
        "</div>"
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
  const AXIS_FORMATTERS = {{
    time: new Intl.DateTimeFormat(undefined, {{ hour: "2-digit", minute: "2-digit" }}),
    day: new Intl.DateTimeFormat(undefined, {{ month: "short", day: "numeric" }}),
    month: new Intl.DateTimeFormat(undefined, {{ month: "short", year: "2-digit" }}),
    detail: new Intl.DateTimeFormat(undefined, {{
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }}),
  }};
  function parseTime(value) {{
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
  }}
  function formatAxisLabel(timestamp, span) {{
    const date = new Date(timestamp);
    if (span <= 36 * 60 * 60 * 1000) {{
      return AXIS_FORMATTERS.time.format(date);
    }}
    if (span <= 120 * 24 * 60 * 60 * 1000) {{
      return AXIS_FORMATTERS.day.format(date);
    }}
    return AXIS_FORMATTERS.month.format(date);
  }}
  function formatDetailLabel(timestamp) {{
    return AXIS_FORMATTERS.detail.format(new Date(timestamp));
  }}
  function pickRange(points, rangeValue) {{
    if (rangeValue === "raw") {{
      return points.filter((point) => point.kind === "raw");
    }}
    if (rangeValue === "all") {{
      return points;
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
  function describeWindow(rangeValue, rangeLabel) {{
    if (rangeValue === "all") {{
      return "All retained history";
    }}
    if (rangeValue === "raw") {{
      return rangeLabel || "Recent raw";
    }}
    return rangeLabel || "Selected range";
  }}
  function summarizeCoverage(points, metric) {{
    const usable = points.filter((point) => typeof point[metric] === "number");
    const timestamps = usable.map((point) => parseTime(point.ts)).filter((point) => point !== null);
    if (timestamps.length === 0) {{
      return "No retained history for this metric";
    }}
    const earliest = Math.min(...timestamps);
    const latest = Math.max(...timestamps);
    const spanMs = Math.max(latest - earliest, 0);
    if (spanMs < 36 * 60 * 60 * 1000) {{
      return "Less than 1 day available";
    }}
    const spanDays = Math.max(1, Math.round(spanMs / (24 * 60 * 60 * 1000)));
    if (spanDays < 45) {{
      return `${{spanDays}} days available`;
    }}
    const spanMonths = Math.max(1, Math.round(spanDays / 30));
    if (spanMonths < 24) {{
      return `${{spanMonths}} months available`;
    }}
    const spanYears = Math.max(1, Math.round(spanDays / 365));
    return `${{spanYears}} years available`;
  }}
  function metricBounds(metric, values) {{
    if (metric === "soc") {{
      return {{ min: 0, max: 100 }};
    }}
    let minValue = Math.min(...values);
    let maxValue = Math.max(...values);
    if (minValue === maxValue) {{
      minValue -= metric === "voltage" ? 0.4 : 2.0;
      maxValue += metric === "voltage" ? 0.4 : 2.0;
    }}
    const padding = metric === "voltage"
      ? Math.max((maxValue - minValue) * 0.12, 0.18)
      : Math.max((maxValue - minValue) * 0.18, 1.5);
    return {{ min: minValue - padding, max: maxValue + padding }};
  }}
  function buildSvg(points, metric, chartId, showMarkers, windowLabel) {{
    const usable = points.filter((point) => typeof point[metric] === "number");
    if (usable.length === 0) {{
      return {{
        svg: '<div class="chart-empty">No ' + METRICS[metric].label + ' data available for ' + windowLabel + '.</div>',
        coords: [],
        width: 960,
        height: 360,
      }};
    }}
    const width = 960;
    const height = 360;
    const padLeft = 68;
    const padRight = 18;
    const padTop = 18;
    const padBottom = 44;
    const sortedUsable = [...usable].sort((left, right) => (parseTime(left.ts) ?? 0) - (parseTime(right.ts) ?? 0));
    const values = sortedUsable.map((point) => point[metric]);
    const bounds = metricBounds(metric, values);
    const minValue = bounds.min;
    const maxValue = bounds.max;
    const span = maxValue - minValue;
    const start = parseTime(sortedUsable[0].ts) ?? 0;
    const end = parseTime(sortedUsable[sortedUsable.length - 1].ts) ?? start + 1;
    const xSpan = Math.max(end - start, 1);
    const plotWidth = width - padLeft - padRight;
    const plotHeight = height - padTop - padBottom;
    const coords = sortedUsable.map((point, index) => {{
      const time = parseTime(point.ts) ?? (start + index);
      const x = padLeft + ((time - start) / xSpan) * plotWidth;
      const y = padTop + (1 - ((point[metric] - minValue) / span)) * plotHeight;
      return {{
        x,
        y,
        time,
        kind: point.kind || "raw",
        ts: point.ts,
        label: point.label || point.ts,
        value: point[metric],
        series: point.series || "Series",
        seriesColor: point.series_color || METRICS[metric].color,
      }};
    }});
    const seriesBuckets = new Map();
    coords.forEach((point) => {{
      const key = `${{point.series}}|${{point.seriesColor}}`;
      const bucket = seriesBuckets.get(key) || {{ label: point.series, color: point.seriesColor, points: [] }};
      bucket.points.push(point);
      seriesBuckets.set(key, bucket);
    }});
    const yGuides = Array.from({{ length: 5 }}, (_, index) => {{
      const y = padTop + ((plotHeight / 4) * index);
      const labelValue = maxValue - ((span / 4) * index);
      return `\n<line x1="${{padLeft}}" y1="${{y.toFixed(1)}}" x2="${{width - padRight}}" y2="${{y.toFixed(1)}}" stroke="#d2dbe7" stroke-width="1"/>\n<text x="10" y="${{(y + 4).toFixed(1)}}" fill="#7c8797" font-size="12">${{labelValue.toFixed(metric === 'soc' ? 0 : 1)}}</text>`;
    }}).join("");
    const xIndexes = new Set([0, Math.floor(coords.length / 3), Math.floor((coords.length * 2) / 3), coords.length - 1]);
    const xGuides = coords.filter((_, index) => xIndexes.has(index)).map((point) => `\n<line x1="${{point.x.toFixed(1)}}" y1="${{padTop}}" x2="${{point.x.toFixed(1)}}" y2="${{height - padBottom}}" stroke="rgba(201,210,224,0.82)" stroke-dasharray="4 8" stroke-width="1"/>`).join("");
    const xLabels = coords.filter((_, index) => xIndexes.has(index)).map((point) => {{
      const timestamp = parseTime(point.ts) ?? start;
      return `\n<text x="${{point.x.toFixed(1)}}" y="${{height - 12}}" text-anchor="middle" fill="#7c8797" font-size="12">${{formatAxisLabel(timestamp, xSpan)}}</text>`;
    }}).join("");
    const gapThreshold = Math.max(xSpan / 8, 6 * 60 * 60 * 1000);
    const segmentSeries = (points) => {{
      const segments = [];
      let current = [];
      for (const point of points) {{
        const previous = current[current.length - 1];
        const shouldBreak = previous && (
          point.kind !== previous.kind ||
          (point.time - previous.time) > gapThreshold
        );
        if (shouldBreak) {{
          segments.push(current);
          current = [];
        }}
        current.push(point);
      }}
      if (current.length > 0) {{
        segments.push(current);
      }}
      return segments;
    }};
    const seriesLayers = Array.from(seriesBuckets.values()).map((series, seriesIndex) => {{
      const segments = segmentSeries(series.points);
      const gradientId = `${{chartId}}-${{metric}}-gradient-${{seriesIndex}}`;
      const segmentSvg = segments.map((segment) => {{
        const line = segment.map((point) => `${{point.x.toFixed(1)}},${{point.y.toFixed(1)}}`).join(" ");
        const startX = segment[0].x.toFixed(1);
        const endX = segment[segment.length - 1].x.toFixed(1);
        const area = `${{startX}},${{height - padBottom}} ` + line + ` ${{endX}},${{height - padBottom}}`;
        const areaSvg = segment.length > 1
          ? `<polyline fill="url(#${{gradientId}})" stroke="none" points="${{area}}" />`
          : "";
        const lineSvg = segment.length > 1
          ? `<polyline fill="none" stroke="${{series.color}}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" points="${{line}}" />`
          : "";
        const dotsSvg = showMarkers
          ? segment.map((point) => `<circle cx="${{point.x.toFixed(1)}}" cy="${{point.y.toFixed(1)}}" r="4.5" fill="#ffffff" stroke="${{series.color}}" stroke-width="3" />`).join("")
          : "";
        return `${{areaSvg}}${{lineSvg}}${{dotsSvg}}`;
      }}).join("");
      return {{
        defs: `\n<linearGradient id="${{gradientId}}" x1="0" x2="0" y1="0" y2="1">\n<stop offset="0%" stop-color="${{series.color}}" stop-opacity="0.28"/>\n<stop offset="100%" stop-color="${{series.color}}" stop-opacity="0.03"/>\n</linearGradient>`,
        body: `\n${{segmentSvg}}`,
      }};
    }});
    const overlayId = `${{chartId}}-${{metric}}-overlay`;
    return {{
      svg: `<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="${{METRICS[metric].label}} chart">\n<defs>${{seriesLayers.map((series) => series.defs).join("")}}\n</defs>\n<rect x="0" y="0" width="${{width}}" height="${{height}}" rx="22" fill="#f7f9fc"/>\n${{yGuides}}\n${{xGuides}}\n${{seriesLayers.map((series) => series.body).join("")}}\n${{xLabels}}\n<line class="chart-crosshair" x1="${{coords[coords.length - 1].x.toFixed(1)}}" y1="${{padTop}}" x2="${{coords[coords.length - 1].x.toFixed(1)}}" y2="${{height - padBottom}}" stroke="${{coords[coords.length - 1].seriesColor}}" stroke-opacity="0.35" stroke-width="2" stroke-dasharray="4 8" />\n<rect id="${{overlayId}}" class="chart-overlay" x="${{padLeft}}" y="${{padTop}}" width="${{plotWidth}}" height="${{plotHeight}}" fill="transparent" />\n</svg>`,
      coords,
      metric,
      width,
      height,
      padLeft,
      padRight,
      overlayId,
    }};
  }}
  function showTooltip(frame, chart, index) {{
    const tooltip = frame.querySelector(".chart-tooltip");
    const crosshair = frame.querySelector(".chart-crosshair");
    if (!tooltip || !crosshair || chart.coords.length === 0) {{
      return;
    }}
    const point = chart.coords[Math.max(0, Math.min(index, chart.coords.length - 1))];
    const timestamp = parseTime(point.ts) ?? 0;
    crosshair.setAttribute("x1", point.x.toFixed(1));
    crosshair.setAttribute("x2", point.x.toFixed(1));
    crosshair.setAttribute("stroke", point.seriesColor || METRICS[chart.metric].color);
    tooltip.innerHTML = `<div class="tooltip-label">${{point.series}}</div><div class="tooltip-value">${{METRICS[chart.metric].format(point.value)}}</div><div class="tooltip-detail">${{formatDetailLabel(timestamp)}}</div>`;
    tooltip.classList.add("visible");
    tooltip.style.left = `${{(point.x / chart.width) * 100}}%`;
    tooltip.style.top = `${{(point.y / chart.height) * 100}}%`;
  }}
  function hideTooltip(frame) {{
    const tooltip = frame.querySelector(".chart-tooltip");
    if (tooltip) {{
      tooltip.classList.remove("visible");
    }}
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
    const showMarkers = frame.dataset.showMarkers === "true";
    let currentRange = rangeButtons.find((button) => button.classList.contains("active"))?.dataset.range || "30";
    let currentMetric = metricButtons.find((button) => button.classList.contains("active"))?.dataset.metric || "voltage";
    function render() {{
      const points = pickRange(allPoints, currentRange);
      const activeRangeButton = rangeButtons.find((button) => button.dataset.range === currentRange);
      const rangeLabel = activeRangeButton?.dataset.rangeLabel || currentRange;
      const windowLabel = describeWindow(currentRange, rangeLabel);
      const tooltip = frame.querySelector(".chart-tooltip");
      const chart = buildSvg(points, currentMetric, id, showMarkers, windowLabel);
      frame.innerHTML = chart.svg;
      if (tooltip) {{
        frame.appendChild(tooltip);
      }}
      const usable = points.filter((point) => typeof point[currentMetric] === "number");
      const allUsable = allPoints.filter((point) => typeof point[currentMetric] === "number");
      const coverageLabel = summarizeCoverage(allPoints, currentMetric);
      if (usable.length === 0) {{
        meta.innerHTML = [
          `<span>Window: ${{windowLabel}}</span>`,
          `<span>No usable ${{METRICS[currentMetric].label.toLowerCase()}} samples in this range</span>`,
          `<span>${{coverageLabel}}</span>`
        ].join("");
        return;
      }}
      const values = usable.map((point) => point[currentMetric]);
      const average = values.reduce((sum, value) => sum + value, 0) / values.length;
      const usesAllAvailable = currentRange !== "all" && currentRange !== "raw" && usable.length === allUsable.length;
      const coverageSummary = usesAllAvailable
        ? `Showing all available history (${{coverageLabel}})`
        : coverageLabel;
      meta.innerHTML = [
        `<span>Window: ${{windowLabel}}</span>`,
        `<span>${{METRICS[currentMetric].label}} samples: ${{usable.length}}</span>`,
        `<span>Average: ${{METRICS[currentMetric].format(average)}}</span>`,
        `<span>Range: ${{METRICS[currentMetric].format(Math.min(...values))}} - ${{METRICS[currentMetric].format(Math.max(...values))}}</span>`,
        `<span>${{coverageSummary}}</span>`
      ].join("");
      const overlay = frame.querySelector(".chart-overlay");
      if (overlay && chart.coords.length > 0) {{
        const pointIndexFromEvent = (event) => {{
          const bounds = overlay.getBoundingClientRect();
          const relativeX = Math.max(0, Math.min(event.clientX - bounds.left, bounds.width));
          const targetX = chart.padLeft + ((relativeX / bounds.width) * (chart.width - chart.padLeft - chart.padRight));
          let bestIndex = 0;
          let bestDistance = Infinity;
          chart.coords.forEach((point, index) => {{
            const distance = Math.abs(point.x - targetX);
            if (distance < bestDistance) {{
              bestDistance = distance;
              bestIndex = index;
            }}
          }});
          return bestIndex;
        }};
        const move = (event) => showTooltip(frame, chart, pointIndexFromEvent(event));
        overlay.addEventListener("mousemove", move);
        overlay.addEventListener("mouseenter", () => showTooltip(frame, chart, chart.coords.length - 1));
        overlay.addEventListener("mouseleave", () => hideTooltip(frame));
        overlay.addEventListener("touchstart", (event) => {{
          if (event.touches.length > 0) {{
            showTooltip(frame, chart, pointIndexFromEvent(event.touches[0]));
          }}
        }}, {{ passive: true }});
        overlay.addEventListener("touchmove", (event) => {{
          if (event.touches.length > 0) {{
            showTooltip(frame, chart, pointIndexFromEvent(event.touches[0]));
          }}
        }}, {{ passive: true }});
        overlay.addEventListener("touchend", () => hideTooltip(frame));
        showTooltip(frame, chart, chart.coords.length - 1);
      }}
    }}
    for (const button of rangeButtons) {{
      button.addEventListener("click", () => {{
        currentRange = button.dataset.range || currentRange;
        for (const candidate of rangeButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        button.scrollIntoView({{ behavior: "smooth", inline: "center", block: "nearest" }});
        render();
      }});
    }}
    for (const button of metricButtons) {{
      button.addEventListener("click", () => {{
        currentMetric = button.dataset.metric || currentMetric;
        for (const candidate of metricButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        button.scrollIntoView({{ behavior: "smooth", inline: "center", block: "nearest" }});
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
