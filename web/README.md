# Web Component

This directory documents the web product boundary for `BMGateway`.

## Current Role

- the shipped web executable is `bm-gateway-web`
- the HTTP/service entrypoint lives in `python/src/bm_gateway/web.py`
- page composition lives in `python/src/bm_gateway/web_pages.py`
- settings/device mutation helpers live in `python/src/bm_gateway/web_actions.py`
- reusable HTML primitives live in `python/src/bm_gateway/web_ui.py`
- packaged web assets live in `python/src/bm_gateway/assets/`
- the shared-core decision avoids a second Python codebase with duplicated
  config, runtime, and persistence logic

## Management Surface

The optional web process serves:

- `/` for the battery-first landing page
- `/settings` for the unified settings surface, with `?edit=1` enabling edit
  mode
- `/history`, `/device`, `/devices`, and `/devices/new` for the main product
  flow
- `/management` and `/gateway` as compatibility aliases that currently open the
  editable settings mode

The current UI contract also includes:

- appearance theming with `light`, `dark`, and `system` modes
- mobile-first battery overview cards with automatic battery and vehicle
  badges, compact multi-card mobile rows, and a SoC-first gauge
- compact history battery selectors that prioritize battery identity over
  installation context while reusing the same badge language as the battery and
  device pages
- persistent per-device accent colors shared between the battery overview,
  history selectors, and charts
- responsive single-device and small-fleet layouts that avoid stretched
  desktop cards and rebalance the battery gauge for narrow mobile screens
- device registry cards and add/edit device forms that share the same themed
  surface system instead of mixing light-only panels into dark mode
- add/edit device flows that generate the device ID automatically from the
  device name and derive badges from battery and vehicle metadata instead of
  exposing manual icon picking
- Bluetooth/add-device warning banners that keep the add-device CTA outside the
  overview grid instead of consuming a fake battery slot

Primary launch command:

```bash
bm-gateway-web --config /etc/bm-gateway/config.toml --port 8080
```

Notable web-facing config under `[web]` includes:

- `appearance`
- `show_chart_markers`
- `visible_device_limit` (`2`, `4`, `6`, or `8`)
- `default_chart_range`
- `default_chart_metric`

Authoritative references:

- [Architecture plan](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- [Python component guide](../python/README.md)
- [Pi 3B web and OS research](../docs/research/2026-04-17-pi3b-web-and-os-research.md)
