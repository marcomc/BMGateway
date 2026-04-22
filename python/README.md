# Python Component

This directory contains the packaged Python implementation for `BMGateway`.

## Layout

- `src/bm_gateway/` contains shared core, runtime CLI, and web executable code
- `src/bm_gateway/web.py` is the HTTP/service entrypoint for the web process
- `src/bm_gateway/web_pages.py` is the compatibility surface for shared web
  rendering helpers plus page-render dispatch
- `src/bm_gateway/web_pages_home.py` contains Home overview rendering
- `src/bm_gateway/web_pages_devices.py` contains Devices and device-form rendering
- `src/bm_gateway/web_pages_history.py` contains History and Device Detail rendering
- `src/bm_gateway/web_pages_settings.py` contains Settings and Gateway-management rendering
- `src/bm_gateway/web_pages_snapshot.py` contains snapshot-only rendering
- `src/bm_gateway/web_actions.py` contains web-driven config and registry updates
- `src/bm_gateway/web_ui.py` contains reusable server-rendered UI primitives
- `src/bm_gateway/web_assets.py` loads packaged CSS/JS assets from `src/bm_gateway/assets/`
- `tests/` contains Python test coverage
- `config/` contains example config and schema artifacts

## Executables

### Runtime CLI

`bm-gateway` is the main executable for:

- `config show`
- `config validate`
- `devices list`
- `ha contract`
- `ha discovery`
- `run --once --dry-run`
- `history daily --device-id <id>`
- `history monthly --device-id <id>`
- `history yearly --device-id <id>`
- `history compare --device-id <id>`
- `history stats`
- `history prune`

### Web Executable

`bm-gateway-web` is the dedicated optional web process for:

- default management UI launch with no explicit subcommand
- `serve --snapshot-file <path>`
- `render --snapshot-file <path>`

## Runtime Modes

- `gateway.reader_mode = "fake"` keeps the deterministic development reader
- `gateway.reader_mode = "live"` enables explicit BLE polling for `bm200`
  devices
- `gateway.poll_interval_seconds = 300` is the intended default baseline
- `bluetooth.scan_timeout_seconds = 15` and
  `bluetooth.connect_timeout_seconds = 45` are the tuned defaults for
  BM6-family devices
- `bm300pro` remains unsupported in live mode and is reported as
  `unsupported`

## Persisted Artifacts

Each runtime cycle writes:

- `runtime/latest_snapshot.json` for the latest rendered state
- `runtime/gateway.db` for SQLite-backed gateway and device readings

Device readings also carry:

- `state`
- `error_code`
- `error_detail`

The database keeps daily rollups so long-term comparisons can survive raw
retention pruning, and monthly summaries are derived from those rollups.

## Device Registry Coverage

The device registry supports:

- lead-acid vs lithium family
- lead-acid profile selection: regular, AGM, EFB, GEL, custom
- lithium profile selection: lithium or custom
- custom battery mode: intelligent algorithm or voltage-to-SoC curve
- built-in icon selection for the battery overview cards
- `installed_in_vehicle = true|false`
- `vehicle_type`
- optional battery metadata for `brand`, `model`, `capacity_ah`, and
  `production_year`

## Notes

- Packaging metadata lives in the repository root `pyproject.toml`
- `python -m bm_gateway` remains supported
- the root `Makefile` is the supported entry point for linting, testing, and
  installation
- host bootstrap uses `../scripts/bootstrap-install.sh`
- the runtime supports both fake and live `bm200` polling paths
- imported archive rows are merged into chart queries without duplicating
  matching live timestamps, and the runtime can now plan reconnect backfill
  attempts for the existing BM200 history path
- BM6-family live archive retrieval is still incomplete on real hardware; the
  current devices poll correctly but do not yet answer the shipped BM200
  history commands
- subprocess coverage exercises `bm-gateway`, `bm-gateway-web`, and
  `python -m bm_gateway`
