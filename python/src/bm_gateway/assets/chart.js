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
  function rangeDurationMs(rangeValue) {{
    if (rangeValue === "all" || rangeValue === "raw") {{
      return null;
    }}
    const days = parseInt(rangeValue, 10);
    if (Number.isNaN(days)) {{
      return null;
    }}
    return days * 24 * 60 * 60 * 1000;
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
  function clampWindowEnd(requestedEnd, {{ earliest, latest, duration }}) {{
    if (duration === null || latest === null || earliest === null) {{
      return latest;
    }}
    if ((latest - earliest) <= duration) {{
      return latest;
    }}
    const minEnd = earliest + duration;
    return Math.min(latest, Math.max(minEnd, requestedEnd));
  }}
  function pickRange(points, rangeValue, requestedWindowEnd = null) {{
    if (rangeValue === "raw") {{
      const rawPoints = points.filter((point) => point.kind === "raw");
      const rawTimes = rawPoints.map((point) => parseTime(point.ts)).filter((point) => point !== null);
      return {{
        points: rawPoints,
        earliest: rawTimes.length > 0 ? Math.min(...rawTimes) : null,
        latest: rawTimes.length > 0 ? Math.max(...rawTimes) : null,
        duration: null,
        effectiveStart: rawTimes.length > 0 ? Math.min(...rawTimes) : null,
        effectiveEnd: rawTimes.length > 0 ? Math.max(...rawTimes) : null,
        pageable: false,
        canPrevious: false,
        canNext: false,
      }};
    }}
    if (rangeValue === "all") {{
      const timestamps = points.map((point) => parseTime(point.ts)).filter((point) => point !== null);
      return {{
        points,
        earliest: timestamps.length > 0 ? Math.min(...timestamps) : null,
        latest: timestamps.length > 0 ? Math.max(...timestamps) : null,
        duration: null,
        effectiveStart: timestamps.length > 0 ? Math.min(...timestamps) : null,
        effectiveEnd: timestamps.length > 0 ? Math.max(...timestamps) : null,
        pageable: false,
        canPrevious: false,
        canNext: false,
      }};
    }}
    const duration = rangeDurationMs(rangeValue);
    if (duration === null) {{
      return {{
        points,
        earliest: null,
        latest: null,
        duration: null,
        effectiveStart: null,
        effectiveEnd: null,
        pageable: false,
        canPrevious: false,
        canNext: false,
      }};
    }}
    const timestamps = points.map((point) => parseTime(point.ts)).filter((point) => point !== null);
    const latest = timestamps.length > 0 ? Math.max(...timestamps) : null;
    const earliest = timestamps.length > 0 ? Math.min(...timestamps) : null;
    if (latest === null) {{
      return {{
        points,
        earliest: null,
        latest: null,
        duration,
        effectiveStart: null,
        effectiveEnd: null,
        pageable: false,
        canPrevious: false,
        canNext: false,
      }};
    }}
    const effectiveEnd = clampWindowEnd(
      requestedWindowEnd ?? latest,
      {{ earliest, latest, duration }},
    );
    const effectiveStart = Math.max(earliest ?? effectiveEnd, effectiveEnd - duration);
    const visiblePoints = points.filter((point) => {{
      const parsed = parseTime(point.ts);
      return parsed !== null && parsed >= effectiveStart && parsed <= effectiveEnd;
    }});
    const pageable = earliest !== null && latest !== null && (latest - earliest) > duration;
    return {{
      points: visiblePoints,
      earliest,
      latest,
      duration,
      effectiveStart,
      effectiveEnd,
      pageable,
      canPrevious: pageable && effectiveEnd > ((earliest ?? effectiveEnd) + duration + 1000),
      canNext: pageable && effectiveEnd < ((latest ?? effectiveEnd) - 1000),
    }};
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
    const isCompact = document.getElementById(chartId)?.dataset.chartCompact === "true";
    const padLeft = isCompact ? 30 : 68;
    const padRight = isCompact ? 14 : 18;
    const padTop = isCompact ? 4 : 18;
    const padBottom = isCompact ? 20 : 44;
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
      const bucket = seriesBuckets.get(key) || {{
        label: point.series,
        color: point.seriesColor,
        points: [],
        order: seriesBuckets.size,
      }};
      bucket.points.push(point);
      seriesBuckets.set(key, bucket);
    }});
    const yGuides = Array.from({{ length: 5 }}, (_, index) => {{
      const y = padTop + ((plotHeight / 4) * index);
      const labelValue = maxValue - ((span / 4) * index);
      return `\n<line x1="${{padLeft}}" y1="${{y.toFixed(1)}}" x2="${{width - padRight}}" y2="${{y.toFixed(1)}}" stroke="${{chartGrid}}" stroke-width="1"/>\n<text x="${{isCompact ? 2 : 10}}" y="${{(y + 4).toFixed(1)}}" fill="${{chartAxis}}" font-size="${{isCompact ? 10 : 12}}">${{labelValue.toFixed(metric === 'soc' ? 0 : 1)}}</text>`;
    }}).join("");
    const xIndexes = new Set([0, Math.floor(coords.length / 3), Math.floor((coords.length * 2) / 3), coords.length - 1]);
    const xGuides = coords.filter((_, index) => xIndexes.has(index)).map((point) => `\n<line x1="${{point.x.toFixed(1)}}" y1="${{padTop}}" x2="${{point.x.toFixed(1)}}" y2="${{height - padBottom}}" stroke="${{chartGrid}}" stroke-dasharray="4 8" stroke-width="1"/>`).join("");
    const xLabels = coords.filter((_, index) => xIndexes.has(index)).map((point) => {{
      const timestamp = parseTime(point.ts) ?? start;
      return `\n<text x="${{point.x.toFixed(1)}}" y="${{height - (isCompact ? 5 : 12)}}" text-anchor="middle" fill="${{chartAxis}}" font-size="${{isCompact ? 10 : 12}}">${{formatAxisLabel(timestamp, xSpan)}}</text>`;
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
    const bucketList = Array.from(seriesBuckets.values());
    const seriesLayers = bucketList.map((series, seriesIndex) => {{
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
    const crosshairSvg = isCompact
      ? ""
      : `\n<line class="chart-crosshair" x1="${{coords[coords.length - 1].x.toFixed(1)}}" y1="${{padTop}}" x2="${{coords[coords.length - 1].x.toFixed(1)}}" y2="${{height - padBottom}}" stroke="${{coords[coords.length - 1].seriesColor}}" stroke-opacity="0.35" stroke-width="2" stroke-dasharray="4 8" />`;
    return {{
      svg: `<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="${{METRICS[metric].label}} chart">\n<defs>${{seriesLayers.map((series) => series.defs).join("")}}\n</defs>\n<rect x="0" y="0" width="${{width}}" height="${{height}}" rx="${{isCompact ? 12 : 22}}" fill="${{chartSurface}}"/>\n${{yGuides}}\n${{xGuides}}\n${{seriesLayers.map((series) => series.body).join("")}}\n${{xLabels}}${{crosshairSvg}}\n<rect id="${{overlayId}}" class="chart-overlay" x="${{padLeft}}" y="${{padTop}}" width="${{plotWidth}}" height="${{plotHeight}}" fill="transparent" />\n</svg>`,
      coords,
      seriesBuckets: bucketList,
      metric,
      width,
      height,
      padLeft,
      padRight,
      overlayId,
    }};
  }}
  function tooltipEntriesForX(chart, targetX) {{
    const threshold = Math.max(
      18,
      ((chart.width - chart.padLeft - chart.padRight) * 0.04),
    );
    const entries = chart.seriesBuckets.map((series) => {{
      let bestPoint = null;
      let bestDistance = Infinity;
      for (const point of series.points) {{
        const distance = Math.abs(point.x - targetX);
        if (distance < bestDistance) {{
          bestDistance = distance;
          bestPoint = point;
        }}
      }}
      if (!bestPoint || bestDistance > threshold) {{
        return null;
      }}
      return {{
        series: series.label,
        color: series.color,
        order: series.order,
        point: bestPoint,
        distance: bestDistance,
      }};
    }}).filter((entry) => entry !== null);
    if (entries.length > 0) {{
      return entries.sort((left, right) => left.order - right.order);
    }}
    if (chart.coords.length === 0) {{
      return [];
    }}
    let fallback = chart.coords[0];
    let fallbackDistance = Infinity;
    for (const point of chart.coords) {{
      const distance = Math.abs(point.x - targetX);
      if (distance < fallbackDistance) {{
        fallback = point;
        fallbackDistance = distance;
      }}
    }}
    return [{{
      series: fallback.series,
      color: fallback.seriesColor,
      order: 0,
      point: fallback,
      distance: fallbackDistance,
    }}];
  }}
  function showTooltip(frame, chart, targetX) {{
    const tooltip = frame.querySelector(".chart-tooltip");
    const crosshair = frame.querySelector(".chart-crosshair");
    if (!tooltip || !crosshair || chart.coords.length === 0) {{
      return;
    }}
    const entries = tooltipEntriesForX(chart, targetX);
    if (entries.length === 0) {{
      return;
    }}
    const primary = entries.reduce((best, current) => (
      current.distance < best.distance ? current : best
    ));
    const timestamp = parseTime(primary.point.ts) ?? 0;
    crosshair.setAttribute("x1", primary.point.x.toFixed(1));
    crosshair.setAttribute("x2", primary.point.x.toFixed(1));
    crosshair.setAttribute("stroke", primary.color || METRICS[chart.metric].color);
    const rows = entries.map((entry) => (
      `<div class="tooltip-series-row">`
      + `<span class="tooltip-series-label">`
      + `<span class="tooltip-series-swatch" style="background:${{entry.color}}"></span>`
      + `${{entry.series}}`
      + `</span>`
      + `<span class="tooltip-series-value">${{METRICS[chart.metric].format(entry.point.value)}}</span>`
      + `</div>`
    )).join("");
    tooltip.innerHTML = (
      `<div class="tooltip-detail">${{formatDetailLabel(timestamp)}}</div>`
      + `<div class="tooltip-series-list">${{rows}}</div>`
    );
    tooltip.classList.add("visible");
    const svg = frame.querySelector("svg");
    if (!svg) {{
      return;
    }}
    const frameRect = frame.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const pointX = (primary.point.x / chart.width) * svgRect.width + (svgRect.left - frameRect.left);
    const pointY = (
      (Math.min(...entries.map((entry) => entry.point.y)) / chart.height) * svgRect.height
    ) + (svgRect.top - frameRect.top);
    const margin = 8;
    const desiredLeft = pointX - (tooltipRect.width / 2);
    const clampedLeft = Math.max(
      margin,
      Math.min(desiredLeft, frame.clientWidth - tooltipRect.width - margin),
    );
    const preferredTop = pointY - tooltipRect.height - 16;
    const fallbackBelow = pointY + 16;
    const clampedTop = preferredTop < margin
      ? Math.min(fallbackBelow, frame.clientHeight - tooltipRect.height - margin)
      : Math.max(margin, Math.min(preferredTop, frame.clientHeight - tooltipRect.height - margin));
    tooltip.style.left = `${{clampedLeft}}px`;
    tooltip.style.top = `${{clampedTop}}px`;
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
    const canvas = frame.querySelector(".chart-canvas");
    const previousButton = document.querySelector(`[data-chart-id="${{id}}"][data-chart-nav="previous"]`);
    const nextButton = document.querySelector(`[data-chart-id="${{id}}"][data-chart-nav="next"]`);
    if (!canvas) {{
      return;
    }}
    const allPoints = JSON.parse(frame.dataset.chartPoints || "[]");
    const card = frame.closest(".chart-card");
    if (!card) {{
      return;
    }}
    const rangeButtons = Array.from(card.querySelectorAll("[data-range]"));
    const metricButtons = Array.from(card.querySelectorAll("[data-metric]"));
    const legendButtons = Array.from(card.querySelectorAll("[data-series-label]"));
    const showMarkers = frame.dataset.showMarkers === "true";
    let currentRange = rangeButtons.find((button) => button.classList.contains("active"))?.dataset.range || "30";
    let currentMetric = metricButtons.find((button) => button.classList.contains("active"))?.dataset.metric || "voltage";
    let visibleSeries = new Set(
      legendButtons.map((button) => button.dataset.seriesLabel).filter((label) => Boolean(label))
    );
    let currentWindowEnd = null;
    let currentChart = null;
    let currentWindow = null;
    let isDragging = false;
    let dragPointerId = null;
    let dragStartX = 0;
    let dragStartEnd = null;
    let pendingRender = false;
    let pendingFocusClientX = null;
    function overlayBounds() {{
      const overlay = frame.querySelector(".chart-overlay");
      return overlay ? overlay.getBoundingClientRect() : null;
    }}
    function targetXFromClientX(clientX) {{
      if (!currentChart) {{
        return null;
      }}
      const bounds = overlayBounds();
      if (!bounds || bounds.width <= 0) {{
        return null;
      }}
      const relativeX = Math.max(0, Math.min(clientX - bounds.left, bounds.width));
      return currentChart.padLeft + (
        (relativeX / bounds.width) * (currentChart.width - currentChart.padLeft - currentChart.padRight)
      );
    }}
    function updateNavigationState() {{
      const pageable = Boolean(currentWindow && currentWindow.pageable);
      frame.classList.toggle("is-pannable", pageable);
      if (previousButton) {{
        previousButton.hidden = !pageable;
        previousButton.disabled = !currentWindow?.canPrevious;
      }}
      if (nextButton) {{
        nextButton.hidden = !pageable;
        nextButton.disabled = !currentWindow?.canNext;
      }}
    }}
    function updateLegendState() {{
      for (const button of legendButtons) {{
        const label = button.dataset.seriesLabel || "";
        const isVisible = visibleSeries.has(label);
        button.classList.toggle("active", isVisible);
        button.classList.toggle("inactive", !isVisible);
        button.setAttribute("aria-pressed", String(isVisible));
      }}
    }}
    function render(focusClientX = null) {{
      const filteredPoints = allPoints.filter((point) => visibleSeries.has(point.series || "Series"));
      const windowState = pickRange(filteredPoints, currentRange, currentWindowEnd);
      currentWindow = windowState;
      currentWindowEnd = windowState.effectiveEnd;
      const points = windowState.points;
      const activeRangeButton = rangeButtons.find((button) => button.dataset.range === currentRange);
      const rangeLabel = activeRangeButton?.dataset.rangeLabel || currentRange;
      const windowLabel = describeWindow(currentRange, rangeLabel);
      const chart = buildSvg(points, currentMetric, id, showMarkers, windowLabel);
      currentChart = chart;
      canvas.innerHTML = chart.svg;
      updateNavigationState();
      const usable = points.filter((point) => typeof point[currentMetric] === "number");
      const allUsable = filteredPoints.filter((point) => typeof point[currentMetric] === "number");
      const coverageLabel = summarizeCoverage(filteredPoints, currentMetric);
      const visibleCount = visibleSeries.size;
      if (usable.length === 0) {{
        meta.innerHTML = [
          `<span>Window: ${{windowLabel}}</span>`,
          `<span>Visible devices: ${{visibleCount}}</span>`,
          `<span>No usable ${{METRICS[currentMetric].label.toLowerCase()}} samples in this range</span>`,
          `<span>${{coverageLabel}}</span>`
        ].join("");
        hideTooltip(frame);
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
        `<span>Visible devices: ${{visibleCount}}</span>`,
        `<span>${{METRICS[currentMetric].label}} samples: ${{usable.length}}</span>`,
        `<span>Average: ${{METRICS[currentMetric].format(average)}}</span>`,
        `<span>Range: ${{METRICS[currentMetric].format(Math.min(...values))}} - ${{METRICS[currentMetric].format(Math.max(...values))}}</span>`,
        `<span>${{coverageSummary}}</span>`
      ].join("");
      if (chart.coords.length > 0) {{
        if (focusClientX !== null) {{
          const targetX = targetXFromClientX(focusClientX);
          if (targetX !== null) {{
            showTooltip(frame, chart, targetX);
            return;
          }}
        }}
        showTooltip(frame, chart, chart.coords[chart.coords.length - 1].x);
      }}
    }}
    function requestRender(focusClientX = null) {{
      pendingFocusClientX = focusClientX;
      if (pendingRender) {{
        return;
      }}
      pendingRender = true;
      requestAnimationFrame(() => {{
        pendingRender = false;
        render(pendingFocusClientX);
        pendingFocusClientX = null;
      }});
    }}
    function pageRange(direction) {{
      if (!currentWindow || !currentWindow.pageable || currentWindow.duration === null) {{
        return;
      }}
      currentWindowEnd = (currentWindow.effectiveEnd ?? 0) + (direction * currentWindow.duration);
      requestRender();
    }}
    for (const button of rangeButtons) {{
      button.addEventListener("click", () => {{
        currentRange = button.dataset.range || currentRange;
        currentWindowEnd = null;
        for (const candidate of rangeButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        centerButtonInRail(button, "smooth");
        requestRender();
      }});
    }}
    for (const button of metricButtons) {{
      button.addEventListener("click", () => {{
        currentMetric = button.dataset.metric || currentMetric;
        for (const candidate of metricButtons) {{
          candidate.classList.toggle("active", candidate === button);
        }}
        centerButtonInRail(button, "smooth");
        requestRender();
      }});
    }}
    for (const button of legendButtons) {{
      button.addEventListener("click", () => {{
        const label = button.dataset.seriesLabel || "";
        if (!label) {{
          return;
        }}
        const isVisible = visibleSeries.has(label);
        if (isVisible && visibleSeries.size === 1) {{
          return;
        }}
        if (isVisible) {{
          visibleSeries.delete(label);
        }} else {{
          visibleSeries.add(label);
        }}
        updateLegendState();
        requestRender();
      }});
    }}
    if (previousButton) {{
      previousButton.addEventListener("click", () => pageRange(-1));
    }}
    if (nextButton) {{
      nextButton.addEventListener("click", () => pageRange(1));
    }}
    frame.addEventListener("pointerdown", (event) => {{
      if (event.button !== undefined && event.button !== 0) {{
        return;
      }}
      if (!currentWindow || !currentWindow.pageable || currentWindow.duration === null) {{
        return;
      }}
      const bounds = overlayBounds();
      if (!bounds) {{
        return;
      }}
      if (
        event.clientX < bounds.left
        || event.clientX > bounds.right
        || event.clientY < bounds.top
        || event.clientY > bounds.bottom
      ) {{
        return;
      }}
      isDragging = true;
      dragPointerId = event.pointerId;
      dragStartX = event.clientX;
      dragStartEnd = currentWindow.effectiveEnd;
      frame.classList.add("is-panning");
      frame.setPointerCapture?.(event.pointerId);
      const targetX = targetXFromClientX(event.clientX);
      if (targetX !== null && currentChart) {{
        showTooltip(frame, currentChart, targetX);
      }}
      event.preventDefault();
    }});
    frame.addEventListener("pointermove", (event) => {{
      if (isDragging && dragPointerId === event.pointerId && currentWindow && currentWindow.duration !== null) {{
        const bounds = overlayBounds();
        if (!bounds || bounds.width <= 0) {{
          return;
        }}
        const deltaX = event.clientX - dragStartX;
        const deltaMs = (deltaX / bounds.width) * currentWindow.duration;
        currentWindowEnd = dragStartEnd - deltaMs;
        requestRender(event.clientX);
        event.preventDefault();
        return;
      }}
      const bounds = overlayBounds();
      if (
        !bounds
        || event.clientX < bounds.left
        || event.clientX > bounds.right
        || event.clientY < bounds.top
        || event.clientY > bounds.bottom
      ) {{
        if (!isDragging) {{
          hideTooltip(frame);
        }}
        return;
      }}
      const targetX = targetXFromClientX(event.clientX);
      if (targetX !== null && currentChart) {{
        showTooltip(frame, currentChart, targetX);
      }}
    }});
    const endDrag = (event) => {{
      if (!isDragging) {{
        return;
      }}
      if (dragPointerId !== null && event.pointerId !== undefined && dragPointerId !== event.pointerId) {{
        return;
      }}
      isDragging = false;
      dragPointerId = null;
      frame.classList.remove("is-panning");
      if (event.pointerId !== undefined) {{
        frame.releasePointerCapture?.(event.pointerId);
      }}
      const targetX = targetXFromClientX(event.clientX);
      if (targetX !== null && currentChart) {{
        showTooltip(frame, currentChart, targetX);
      }} else {{
        hideTooltip(frame);
      }}
    }};
    frame.addEventListener("pointerup", endDrag);
    frame.addEventListener("pointercancel", endDrag);
    frame.addEventListener("pointerleave", () => {{
      if (!isDragging) {{
        hideTooltip(frame);
      }}
    }});
    updateLegendState();
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
