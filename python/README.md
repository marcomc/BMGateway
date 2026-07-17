# Python Component

## Contents

- [Purpose](#purpose)
- [Layout](#layout)
- [Executables](#executables)
- [Key Runtime Capabilities](#key-runtime-capabilities)
- [History and Persistence](#history-and-persistence)
- [Device Registry Coverage](#device-registry-coverage)
- [Related Documents](#related-documents)

## Purpose

This directory contains the packaged Python implementation for `BMGateway`.

This is the contributor entry point for the application code. For the project
overview, use the root [README.md](../README.md). For architectural context,
use [../docs/README.md](../docs/README.md). For the runtime, CLI, web UI, and
Home Assistant surface map, use
[../docs/application-surfaces.md](../docs/application-surfaces.md).

## Layout

- `src/bm_gateway/` contains the shared application code
- `src/bm_gateway/web.py` is the web service entrypoint
- `src/bm_gateway/web_pages_*.py` contain the page-family renderers
- `src/bm_gateway/web_actions.py` contains web-driven mutations and actions
- `src/bm_gateway/web_ui.py` contains shared HTML primitives
- `src/bm_gateway/localization.py` loads packaged web localization catalogs
- `src/bm_gateway/web_assets.py` loads packaged web assets
- `src/bm_gateway/assets/` contains packaged CSS, JS, and web icons
- `src/bm_gateway/locales/` contains packaged locale JSON files
- `tests/` contains Python tests
- `config/` contains example config files and the schema

## Executables

### `bm-gateway`

Main runtime CLI for:

- config validation and inspection
- device listing
- Home Assistant MQTT contract and discovery export
- runtime execution
- history inspection and pruning
- bounded BM6/BM7 protocol probes for live debugging

The command reference is maintained in
[Application surfaces](../docs/application-surfaces.md#command-line).

### `bm-gateway-web`

Optional web executable for:

- full management UI
- standalone snapshot serving
- snapshot HTML rendering

The web UI route and API reference is maintained in
[Application surfaces](../docs/application-surfaces.md#web-ui).

## Key Runtime Capabilities

- shared config/runtime/web core in one package
- fake and live reader modes
- BM200/BM6-family live polling
- BM300 Pro/BM7-family live polling
- MQTT publishing and Home Assistant discovery support
- service-friendly Raspberry Pi deployment shape
- modular web UI localization selected through `web.language`
- optional self-healing for scheduled host reboots and Wi-Fi recovery
- live BLE backoff for devices that stop advertising and recovery after two
  fleet-wide timeout cycles

BM200/BM6-family and BM300 Pro/BM7-family live polling now share the same BLE
scan, connect, notify, retry, and cleanup control flow. The protocol-specific
drivers still own the request payloads, packet validation, and measurement
parsing selected by the configured device type.

## History and Persistence

Runtime persistence uses:

- `runtime/latest_snapshot.json`
- `runtime/gateway.db`
- `runtime/audit/YYYY-MM-DD.jsonl`

History surfaces include:

- raw readings
- daily rollups
- monthly rollups
- yearly summaries

Live polling and onboard archive imports write to the same canonical
`device_samples` table. Archive imports insert missing samples at their own
timestamps, so a later reimport can fill a gap between existing live samples
without overwriting the surrounding data.

`device_daily_rollups` is a derived cache rebuilt from `device_samples` for
daily, monthly, yearly, and degradation views. `archive_import_batches` records
whether an archive import is running, completed, or failed, but it is not an
intermediate measurement store.

Raw history retention defaults to two years and applies to `device_samples`.
Daily rollups are finalized from canonical samples before raw pruning and
default to no extra rollup-only pruning, so long-range charts remain available
after detailed samples expire.

The audit log is newline-delimited JSON intended for machine correlation during
operations debugging. It records automatic polling cycles, per-device poll
results, archive-sync activity, and key manual web-managed actions, and prunes
files older than 90 days automatically.

The detailed storage flow is documented in
[Unified history storage](../docs/architecture/2026-05-16-unified-history-storage.md).

## Device Registry Coverage

The device registry supports:

- battery family and profile selection
- custom SoC curve support
- vehicle installation metadata
- battery brand, model, voltage, capacity, and year
- per-device color selection

## Related Documents

Use these as the canonical references instead of repeating the same guidance:

- Architecture:
  [../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- Application surfaces:
  [../docs/application-surfaces.md](../docs/application-surfaces.md)
- Verified BM6/BM200 notes:
  [../docs/2026-04-19-bm6-bm200-integration-notes.md](../docs/2026-04-19-bm6-bm200-integration-notes.md)
- BM300 Pro/BM7 notes:
  [../docs/2026-04-25-bm300-bm7-integration-notes.md](../docs/2026-04-25-bm300-bm7-integration-notes.md)
- Protocol probe tools:
  [../docs/protocol-probe-tools.md](../docs/protocol-probe-tools.md)
- Raspberry Pi installation:
  [../rpi-setup/manual-setup.md](../rpi-setup/manual-setup.md)
- Home Assistant setup:
  [../home-assistant/setup.md](../home-assistant/setup.md)
- Web product boundary:
  [../web/README.md](../web/README.md)
