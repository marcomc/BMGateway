# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2024-06-30

### Included

- Packaged Python runtime and web executables:
  - `bm-gateway`
  - `bm-gateway-web`
- Shared Python application core for:
  - configuration loading and validation
  - BLE polling
  - MQTT publishing
  - SQLite persistence
  - web rendering
- Live BM200/BM6-family polling path with:
  - device snapshots
  - connection/error reporting
  - signal-quality capture
  - temperature capture
- SQLite-backed history with:
  - raw readings
  - daily rollups
  - monthly rollups
  - yearly summaries
  - storage inspection and pruning commands
- History analytics including:
  - rolling comparison windows
  - yearly summaries
  - degradation-oriented reporting
- Optional Home Assistant integration through the built-in MQTT integration:
  - discovery payload export
  - documented MQTT contract
  - optional package helpers
  - optional starter dashboard
- Raspberry Pi appliance tooling:
  - standalone `make install`
  - bootstrap install script
  - `systemd` units for runtime and web UI
  - manual setup guidance
  - optional Glances and Cockpit guidance
- Battery-first local web application with:
  - Home landing page
  - History page
  - Device Detail page
  - Devices page
  - Settings page
- Mobile-oriented web features including:
  - light / dark / system theme modes
  - device color assignment across overview, history, and charts
  - icon and badge system derived from battery and vehicle metadata
  - chart range selectors and metric selectors
  - chart paging and drag navigation
  - multi-series hover tooltips
  - device and fleet charts
  - iPhone home-screen icon support
- Device registry and web device-management support for:
  - automatic device ID generation
  - MAC or serial entry
  - vehicle installation metadata
  - battery family/profile selection
  - custom battery curve support
  - battery brand, model, voltage, capacity, and production year
  - per-device overview color selection
- Service recovery and maintenance actions in Settings for:
  - restarting `bm-gateway.service`
  - restarting `bluetooth.service`
  - rebooting the Raspberry Pi
- Developer tooling and quality gates:
  - `make check`
  - pytest coverage
  - Ruff lint/format
  - mypy
  - Markdown linting
  - shell script linting
- Internal web modularization with separated:
  - service entrypoint
  - page-family renderers
  - web actions
  - packaged CSS/JS assets

### Known Limits

- BM6-family onboard archive-history download is not complete yet on live
  hardware, even though normal live polling works.
- BM300 Pro support is not implemented in the live reader path.
