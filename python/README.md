# Python Component

This directory contains the packaged Python CLI and service code for
`BMGateway`.

## Layout

- `src/bm_gateway/` contains importable application code
- `tests/` contains Python test coverage
- `config/` contains example config and schema artifacts

## Current Commands

- `bm-gateway config show`
- `bm-gateway config validate`
- `bm-gateway devices list`
- `bm-gateway ha contract`
- `bm-gateway ha discovery`
- `bm-gateway run --once --dry-run`
- `bm-gateway history daily --device-id <id>`
- `bm-gateway history monthly --device-id <id>`
- `bm-gateway history yearly --device-id <id>`
- `bm-gateway history compare --device-id <id>`
- `bm-gateway history stats`
- `bm-gateway history prune`
- `bm-gateway web render --snapshot-file <path>`
- `bm-gateway web serve --snapshot-file <path>`
- `bm-gateway web manage`

## Runtime Modes

- `gateway.reader_mode = "fake"` keeps the deterministic development reader
- `gateway.reader_mode = "live"` enables explicit BLE polling for `bm200`
  devices
- `gateway.poll_interval_seconds = 300` is the intended default baseline
  because battery monitoring should normally run every few minutes, not every
  few seconds
- `bluetooth.scan_timeout_seconds = 15` and
  `bluetooth.connect_timeout_seconds = 45` are the tuned defaults for
  BM6-family devices that do not advertise consistently on every short scan
  window
- `bm300pro` remains unsupported in live mode and will be reported as
  `unsupported`

## Persisted Artifacts

Each runtime cycle writes:

- `runtime/latest_snapshot.json` for the latest rendered state
- `runtime/gateway.db` for SQLite-backed gateway and device readings

Device readings also carry:

- `state`
- `error_code`
- `error_detail`

The database also keeps daily rollups so long-term comparisons can survive raw
retention pruning, and monthly summaries are derived from those rollups.

The device registry now also supports battery metadata that mirrors the
official BM200/BM300 app flow:

- lead-acid vs lithium family
- lead-acid profile selection: regular, AGM, EFB, GEL, custom
- lithium profile selection: lithium or custom
- custom battery mode: intelligent algorithm or voltage-to-SoC curve
- built-in icon selection for the battery overview cards, including car,
  motorcycle, chemistry-specific, and custom battery monitor visuals
- `installed_in_vehicle = true|false` to separate battery chemistry from
  installation context
- `vehicle_type` for vehicle-installed batteries, including car, motorcycle,
  van, camper, truck, bus, boat, tractor, ATV, and machinery profiles
- optional battery metadata for `brand`, `model`, `capacity_ah`, and
  `production_year`

The CLI can inspect raw history, daily rollups, monthly summaries, and storage
retention stats directly, and it now exposes yearly summaries plus degradation
comparison windows.

The web UI now defaults to:

- `web.port = 80`
- `web.show_chart_markers = false`

The gateway/admin surface lives under `/gateway`, while `/devices/edit` is the
dedicated device-configuration flow.

## Notes

- The packaging metadata lives in the repository root `pyproject.toml`.
- The installed CLI name remains `bm-gateway`.
- The root `Makefile` is the supported entry point for linting, testing, and
  installation.
- Host bootstrap should use `../scripts/bootstrap-install.sh`, which ultimately
  runs `make install` for a standalone runtime instead of `make install-dev`.
- The runtime supports both fake and live `bm200` polling paths.
- Live `bm200` history retrieval is not wired yet, so long-term history is
  still built from per-cycle state snapshots.
- End-to-end subprocess coverage now exercises:
  `bm-gateway`, `python -m bm_gateway`, `web serve`, and `web manage`.
- MQTT publishing now includes availability topics and richer device
  availability semantics in the state payloads.
