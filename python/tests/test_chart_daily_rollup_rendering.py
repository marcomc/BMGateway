from __future__ import annotations

import json
import re
import subprocess

from bm_gateway.web_ui import chart_script


def test_daily_rollup_only_chart_renders_a_visible_line() -> None:
    rendered_script = chart_script("history-chart")
    source = re.search(r"<script>(.*)</script>", rendered_script, re.DOTALL)
    assert source is not None
    daily_points = [
        {
            "ts": f"2026-04-{day:02d}T23:58:00+02:00",
            "kind": "daily",
            "voltage": 13.2 + (day * 0.01),
            "soc": 80,
            "temperature": 20.0,
            "series": "Liberty LD13CZT",
            "series_color": "#17c45a",
        }
        for day in range(1, 8)
    ]
    harness = f"""
class ClassList {{
  constructor(...values) {{ this.values = new Set(values.filter(Boolean)); }}
  contains(value) {{ return this.values.has(value); }}
  add(value) {{ this.values.add(value); }}
  remove(value) {{ this.values.delete(value); }}
  toggle(value, enabled) {{
    const next = enabled === undefined ? !this.values.has(value) : Boolean(enabled);
    if (next) this.values.add(value); else this.values.delete(value);
    return next;
  }}
}}
const element = ({{ dataset = {{}}, classes = [] }} = {{}}) => ({{
  dataset,
  classList: new ClassList(...classes),
  style: {{ setProperty() {{}} }},
  hidden: false,
  disabled: false,
  textContent: "",
  innerHTML: "",
  clientWidth: 960,
  clientHeight: 360,
  addEventListener() {{}},
  setAttribute() {{}},
  closest() {{ return null; }},
  getBoundingClientRect() {{
    return {{ left: 0, top: 0, right: 960, bottom: 360, width: 960, height: 360 }};
  }},
  setPointerCapture() {{}},
  releasePointerCapture() {{}},
}});
const canvas = element();
const meta = element();
const previous = element();
const next = element();
const range = element({{ dataset: {{ range: "7", rangeLabel: "7 days" }}, classes: ["active"] }});
const metric = element({{ dataset: {{ metric: "voltage" }}, classes: ["active"] }});
const legend = element({{ dataset: {{ seriesLabel: "Liberty LD13CZT" }}, classes: ["active"] }});
const card = element();
card.querySelectorAll = (selector) => {{
  if (selector === "[data-range]") return [range];
  if (selector === "[data-metric]") return [metric];
  if (selector === "[data-series-label]") return [legend];
  return [];
}};
const frame = element({{ dataset: {{ showMarkers: "false" }} }});
frame.querySelector = (selector) => selector === ".chart-canvas" ? canvas : null;
frame.closest = () => card;
const data = element();
data.textContent = {json.dumps(json.dumps(daily_points))};
global.document = {{
  body: element(),
  getElementById(id) {{
    if (id === "history-chart") return frame;
    if (id === "history-chart-meta") return meta;
    if (id === "history-chart-data") return data;
    return null;
  }},
  querySelector(selector) {{
    return selector.includes('previous') ? previous : next;
  }},
}};
global.window = {{
  getComputedStyle: () => ({{ getPropertyValue: () => "" }}),
  matchMedia: () => ({{ matches: false }}),
  addEventListener() {{}},
}};
global.requestAnimationFrame = (callback) => callback();
global.setTimeout = (callback) => callback();
{source.group(1)}
process.stdout.write(canvas.innerHTML.includes("<polyline") ? "line" : "empty");
"""

    completed = subprocess.run(
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == "line"
