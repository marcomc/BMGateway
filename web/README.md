# Web Component

## Table of Contents

- [Purpose](#purpose)
- [Current Product Surface](#current-product-surface)
- [Configuration Knobs](#configuration-knobs)
- [Canonical References](#canonical-references)

## Purpose

This document describes the product boundary of the shipped local web
application.

It does not repeat installation steps or architecture detail. For those, use:

- root overview: [../README.md](../README.md)
- Raspberry Pi install: [../rpi-setup/manual-setup.md](../rpi-setup/manual-setup.md)
- architecture: [../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- Python implementation: [../python/README.md](../python/README.md)

## Current Product Surface

The shipped web application provides:

- Home
- History
- Device Detail
- Devices
- Settings

The implementation lives in the shared Python package:

- web service entrypoint: `python/src/bm_gateway/web.py`
- page-family renderers: `python/src/bm_gateway/web_pages_*.py`
- shared web actions: `python/src/bm_gateway/web_actions.py`
- shared UI primitives: `python/src/bm_gateway/web_ui.py`
- packaged web assets: `python/src/bm_gateway/assets/`

## Configuration Knobs

Web-facing config under `[web]` currently includes:

- `appearance`
- `show_chart_markers`
- `visible_device_limit`
- `default_chart_range`
- `default_chart_metric`

The appliance-level `[usb_otg]` section is also visible in Settings for the
disabled-by-default USB OTG image-export option.

## Canonical References

- Project overview: [../README.md](../README.md)
- Python contributor guide: [../python/README.md](../python/README.md)
- Architecture plan:
  [../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- BM6/BM200 notes:
  [../docs/2026-04-19-bm6-bm200-integration-notes.md](../docs/2026-04-19-bm6-bm200-integration-notes.md)
