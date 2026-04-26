# Python Component

## Table of Contents

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
use [../docs/README.md](../docs/README.md).

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
- Home Assistant contract and discovery export
- runtime execution
- history inspection and pruning
- bounded BM6/BM7 protocol probes for live debugging

### `bm-gateway-web`

Optional web executable for:

- full management UI
- standalone snapshot serving
- snapshot HTML rendering

## Key Runtime Capabilities

- shared config/runtime/web core in one package
- fake and live reader modes
- BM200/BM6-family live polling
- BM300 Pro/BM7-family live polling
- MQTT publishing and Home Assistant discovery support
- service-friendly Raspberry Pi deployment shape
- modular web UI localization selected through `web.language`

BM300 Pro live support is implemented through a separate driver selected by the
configured device type.

## History and Persistence

Runtime persistence uses:

- `runtime/latest_snapshot.json`
- `runtime/gateway.db`

History surfaces include:

- raw readings
- daily rollups
- monthly rollups
- yearly summaries

Archive-history merge/backfill plumbing exists, but BM6-family onboard archive
retrieval is still incomplete on real hardware.

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
