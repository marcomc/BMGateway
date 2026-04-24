# Web Component

## Table of Contents

- [Purpose](#purpose)
- [Current Product Surface](#current-product-surface)
- [Configuration Knobs](#configuration-knobs)
- [Adding Or Updating Locales](#adding-or-updating-locales)
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
- localization layer: `python/src/bm_gateway/localization.py`
- packaged locale catalogs: `python/src/bm_gateway/locales/`

## Configuration Knobs

Web-facing config under `[web]` currently includes:

- `appearance`
- `show_chart_markers`
- `default_chart_range`
- `default_chart_metric`
- `language`

`language` selects the packaged locale catalog used by the server-rendered web
UI. The default value is `auto`, which reads the browser `Accept-Language`
preference. Browsers usually derive that preference from the user's browser or
operating-system language settings, so this is the best default for a local web
application. If no supported language matches, the UI falls back to English.

The initial supported languages are English, Simplified Chinese, Hindi,
Spanish, Arabic, French, Bengali, Portuguese, Russian, Urdu, German, and
Italian. Arabic and Urdu pages are emitted with right-to-left document
direction.

The appliance-level `[usb_otg]` section is also visible in Settings for the
disabled-by-default USB OTG image-export option. The Settings card keeps the
runtime export checkbox separate from platform status and host-preparation
actions because preparing or restoring Raspberry Pi USB OTG boot mode edits
boot configuration and requires a reboot. The card shows only the action that
matches the current boot-mode state.

The same card reports whether USB OTG support was installed by the Raspberry Pi
installer. If `--skip-usb-otg-tools` was used, Settings shows that support is
not installed and hides the prepare/export actions until the installer is run
again without that skip option. When support is installed, Settings can also
configure generated frame image width, height, format, light/dark appearance,
refresh cadence, overview density, which image types are exported, and the
Fleet Trend frame metrics, history range, and included devices.
The exporter screenshots the same hidden frame-render pages used by
Diagnostics, so the preview and USB drive files share one rendering path.
Saving USB OTG image-export settings starts background regeneration for the
configured images when USB OTG export is enabled, then redirects Settings
without waiting for screenshots and drive reattachment to finish.
The non-editing Settings Actions panel exposes `Export Frame Images`, which
regenerates the images and reattaches the drive, and `Refresh USB OTG Drive`, which
only detaches and reattaches the existing backing disk image so a picture frame
can re-enumerate it.

Settings also exposes `Diagnostics` for internal validation pages. The
Diagnostics page contains a `Frame Preview` section that embeds hidden
frame-render routes such as `/frame/fleet-trend` and
`/frame/battery-overview?page=1` inside a simulated picture-frame viewport.
These routes remain clean screenshot targets with no normal application
navigation around them.

## Adding Or Updating Locales

Localization is intentionally centralized. Do not fork page templates for a
new language, and do not add translated strings inline beside every English UI
string.

To add another language:

1. Add the language to `SUPPORTED_LOCALES` in
   `python/src/bm_gateway/localization.py`.
   Use a stable language code such as `ja`, `ko`, or `nl`. For regional
   variants, add an alias in `_LANGUAGE_ALIASES` when the UI should reuse an
   existing catalog. Set `direction="rtl"` for right-to-left languages.
2. Leave `auto` as a preference mode, not a real catalog. Automatic detection
   resolves to one of the supported language catalogs at request time.
3. Add a catalog file at `python/src/bm_gateway/locales/<code>.json`.
   The JSON object maps the English source text used by the templates to the
   translated text:

   ```json
   {
     "Settings": "Translated settings label",
     "Battery Overview": "Translated battery overview label"
   }
   ```

4. Keep product names, protocol names, config keys, service names, MQTT topics,
   and device-provided values untranslated unless the UI label around them is
   the part being localized. Examples that usually stay unchanged include
   `BMGateway`, `MQTT`, `Home Assistant`, `bm-gateway.service`, and
   `web.language`.
5. Add or update tests in `python/tests/test_localization.py`.
   At minimum, assert that the new language appears in `SUPPORTED_LOCALES` and
   that a representative page renders one translated label.
6. Run:

   ```bash
   uv run pytest python/tests/test_localization.py -q
   markdownlint --config /Users/mmassari/.markdownlint.json web/README.md
   ```

7. Run `make check` before shipping.

The localizer translates exact text nodes and selected accessibility
attributes such as `aria-label`, `placeholder`, `title`, and `alt`. When adding
new UI copy, keep the source text clear and stable in English, then add the
same source string to each locale catalog. If a label includes dynamic data,
prefer keeping the fixed label and the dynamic value separate so the fixed
label can be translated reliably.

For right-to-left languages, verify the rendered page in a browser after adding
or expanding the catalog. The document direction is set centrally, but dense
tables, charts, and button groups may still need a visual pass.

## Canonical References

- Project overview: [../README.md](../README.md)
- Python contributor guide: [../python/README.md](../python/README.md)
- Architecture plan:
  [../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- BM6/BM200 notes:
  [../docs/2026-04-19-bm6-bm200-integration-notes.md](../docs/2026-04-19-bm6-bm200-integration-notes.md)
