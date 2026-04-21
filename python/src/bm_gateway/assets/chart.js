<script>
(() => {{
  const chartIds = {ids};
  const themeStyles = window.getComputedStyle(document.body);
  const themeValue = (name, fallback) => themeStyles.getPropertyValue(name).trim() || fallback;
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
    const chartSurface = themeValue("--chart-svg-surface", "#f7f9fc");
    const chartGrid = themeValue("--chart-grid", "rgba(196, 207, 220, 0.88)");
    const chartAxis = themeValue("--chart-axis", "#708094");
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
      return `\n<line x1="${{padLeft}}" y1="${{y.toFixed(1)}}" x2="${{width - padRight}}" y2="${{y.toFixed(1)}}" stroke="${{chartGrid}}" stroke-width="1"/>\n<text x="10" y="${{(y + 4).toFixed(1)}}" fill="${{chartAxis}}" font-size="12">${{labelValue.toFixed(metric === 'soc' ? 0 : 1)}}</text>`;
    }}).join("");
    const xIndexes = new Set([0, Math.floor(coords.length / 3), Math.floor((coords.length * 2) / 3), coords.length - 1]);
    const xGuides = coords.filter((_, index) => xIndexes.has(index)).map((point) => `\n<line x1="${{point.x.toFixed(1)}}" y1="${{padTop}}" x2="${{point.x.toFixed(1)}}" y2="${{height - padBottom}}" stroke="${{chartGrid}}" stroke-dasharray="4 8" stroke-width="1"/>`).join("");
    const xLabels = coords.filter((_, index) => xIndexes.has(index)).map((point) => {{
      const timestamp = parseTime(point.ts) ?? start;
      return `\n<text x="${{point.x.toFixed(1)}}" y="${{height - 12}}" text-anchor="middle" fill="${{chartAxis}}" font-size="12">${{formatAxisLabel(timestamp, xSpan)}}</text>`;
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
          ? segment.map((point) => `<circle cx="${{point.x.toFixed(1)}}" cy="${{point.y.toFixed(1)}}" r="4.5" fill="${{chartSurface}}" stroke="${{series.color}}" stroke-width="3" />`).join("")
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
      svg: `<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="${{METRICS[metric].label}} chart">\n<defs>${{seriesLayers.map((series) => series.defs).join("")}}\n</defs>\n<rect x="0" y="0" width="${{width}}" height="${{height}}" rx="22" fill="${{chartSurface}}"/>\n${{yGuides}}\n${{xGuides}}\n${{seriesLayers.map((series) => series.body).join("")}}\n${{xLabels}}\n<line class="chart-crosshair" x1="${{coords[coords.length - 1].x.toFixed(1)}}" y1="${{padTop}}" x2="${{coords[coords.length - 1].x.toFixed(1)}}" y2="${{height - padBottom}}" stroke="${{coords[coords.length - 1].seriesColor}}" stroke-opacity="0.35" stroke-width="2" stroke-dasharray="4 8" />\n<rect id="${{overlayId}}" class="chart-overlay" x="${{padLeft}}" y="${{padTop}}" width="${{plotWidth}}" height="${{plotHeight}}" fill="transparent" />\n</svg>`,
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
  function centerButtonInRail(button, behavior = "auto") {{
    if (!button) {{
      return;
    }}
    const rail = button.closest(".control-rail");
    if (!rail) {{
      return;
    }}
    const railRect = rail.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    const buttonCenter = (buttonRect.left - railRect.left) + rail.scrollLeft + (buttonRect.width / 2);
    const maxScrollLeft = Math.max(0, rail.scrollWidth - rail.clientWidth);
    const targetLeft = Math.min(
      maxScrollLeft,
      Math.max(0, buttonCenter - (rail.clientWidth / 2)),
    );
    rail.scrollTo({{
      left: targetLeft,
      behavior,
    }});
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
        centerButtonInRail(button, "smooth");
        render();
      }});
    }}
    for (const button of metricButtons) {{
      button.addEventListener("click", () => {{
        currentMetric = button.dataset.metric || currentMetric;
        for (const candidate of metricButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        centerButtonInRail(button, "smooth");
        render();
      }});
    }}
    render();
    const centerActiveControls = (behavior = "auto") => {{
      centerButtonInRail(
        rangeButtons.find((button) => button.classList.contains("active")),
        behavior,
      );
      centerButtonInRail(
        metricButtons.find((button) => button.classList.contains("active")),
        behavior,
      );
    }};
    requestAnimationFrame(() => {{
      centerActiveControls();
      setTimeout(() => centerActiveControls(), 80);
    }});
    window.addEventListener("load", () => {{
      centerActiveControls();
    }}, {{ once: true }});
    window.addEventListener("resize", () => {{
      centerActiveControls();
    }});
  }}
  for (const chartId of chartIds) {{
    initChart(chartId);
  }}
}})();
</script>
