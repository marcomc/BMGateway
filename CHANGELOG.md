# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Added structured JSONL audit logs under the runtime state directory for
  automatic polling, per-device poll outcomes, archive sync activity, manual
  history sync requests, and key web-managed configuration or device changes,
  with automatic 90-day retention pruning for Raspberry Pi diagnostics.
- Added explicit archive-backfill trigger reasons (`periodic`, `reconnect`, or
  both) to runtime and archive-sync audit events so gateway diagnostics can
  show why a supported-device history import was or was not scheduled.
- Added a bounded `bm-gateway protocol probe-history` diagnostic command for
  safe BM6/BM7 live, version, and `d15505` history-candidate BLE probes with
  JSONL output.
- Added a controlled BM200/BM6 `d15505` byte-matrix probe mode around the
  verified byte-7 selector, including per-command history summaries for JSONL
  triage without importing data into SQLite.
- Added a BM200/BM6 `d15505` sweep mode for controlled full-range byte-value
  probes when matrix or deepen results identify a candidate selector byte.
- Added an offline `bm-gateway protocol analyze-history-captures` report for
  saved protocol-probe JSONL files, including decoded history-field profiling,
  marker counts, sequence overlap checks, and stitch recommendations.
- Added an experimental `bm-gateway protocol bm300-multipage-import` command
  for controlled BM300 Pro/BM7 byte-7 history validation and import. It fetches
  selectors `b7=01`, `02`, and `03`, requires at least 128 consecutive
  identical raw records between consecutive depths, fails explicitly without
  writing when overlap is not strong enough, and writes only to an explicitly
  supplied SQLite path instead of the normal runtime database.
- Added BM200/BM6 archive-history import through
  `bm-gateway history sync-device`, including decoded voltage, SoC,
  temperature, raw record storage, and a `--page-count` option for cumulative
  `d15505` history pages.
- Added automatic BM200/BM6 archive-history backfill for visible devices,
  driven by configurable periodic and reconnect thresholds, plus a per-device
  History page action that requests the full 30-day BM200 retention window on
  demand.
- Added a History sync progress page for manual archive imports, with live
  status, fetched-record totals, imported-record progress, and automatic return
  to the selected History page.
- Added gated BM300 Pro/BM7 archive-history import using the verified
  `d15505` byte-6 selector and the shared `vvv ss tt p` record layout, with a
  separate opt-in setting and page cap for future 72-day retention validation.

### Changed

- Switched the standard BM300 Pro/BM7 archive-history path from the older
  byte-6 selector candidate to the validated byte-7 depth path. Standard
  BM300 imports now request selectors `b7=01`, `02`, and `03`, require exact
  raw-record overlap of 256 then 512 records on `doc_fb12899`, and import a
  validated 769-record window of about 25 hours 38 minutes.
- Enabled BM300 Pro/BM7 automatic archive sync by default for new configs and
  service installs, with the standard path capped to the currently validated
  depth-3 import window until deeper selectors are proven.

- Aligned the History `Batteries` selector pagination with the Home Battery
  Overview responsive two-row pagination logic.
- Reduced initial layout shifts in the Home Battery Overview and History
  `Batteries` pagers, and made small History battery sets render as one row
  when the available width supports it without browser-specific row stretching.

### Fixed

- Serialized BLE access across runtime polling, web-triggered run-once polls,
  and BM200/BM300 archive imports with a shared cross-process lock so
  concurrent gateway operations no longer collide and leave BlueZ or `bleak`
  in `NotReady`-style failure states.
- Fixed fatal BLE/D-Bus runtime failures so the gateway no longer stays alive in
  a broken state after `bleak` or `dbus_fast` transport errors. The runtime now
  treats those failures as unrecoverable, requests Bluetooth service recovery,
  and exits so `systemd` can restart a clean polling process.
- Hardened Raspberry Pi bootstrap dependency installation so fresh installs,
  Raspberry Pi Imager first-run setup, direct service refreshes, and Ansible
  provisioning install the documented runtime, web, Bluetooth, and USB OTG
  system packages consistently.
- Fixed Home Battery Overview status rendering so monitor-reported `low`
  battery states show red status, percentage, and battery-badge accents instead
  of `Battery OK`.
- Reduced History, Fleet Trend, Device Detail, and frame-chart render cost by
  compressing management responses, moving chart datasets out of heavy HTML
  attributes, compacting dense chart ranges before SVG rendering, limiting the
  History diagnostic raw table, and adding chronological history indexes.
- Corrected BM6-family live state code `2` to display as `charging`, matching
  public BM6 integration code, official-app behavior, and local BM200 probes.

## [0.2.0] - 2026-04-25

### Added

- Added modular web localization with packaged locale catalogs, a Settings
  language selector, persisted `web.language` config, automatic browser/system
  language detection by default, and initial support for English, Simplified
  Chinese, Hindi, Spanish, Arabic, French, Bengali, Portuguese, Russian, Urdu,
  German, and Italian.
- Added a Raspberry Pi USB-OTG image-export hardware test helper and
  Samsung `SPF-71E` compatibility image generator for validating a
  read-only mass-storage gadget before implementing automated exports.
- Added a disabled-by-default USB OTG image-export setting with device
  controller detection, warning text when the gadget path is unavailable, and
  installer support for USB-OTG helper packages.
- Added reversible USB OTG boot-mode preparation and restore actions for the
  Settings page, backed by a root-scoped helper that edits Raspberry Pi boot
  config with timestamped backups.
- Added automated USB OTG frame-image export for battery overview pages and a
  Fleet Trend chart, including configurable output size, format, light/dark
  appearance, refresh cadence, overview density, and a manual export action.
- Added USB OTG-specific Fleet Trend frame settings for metric selection,
  history range, and included devices, independent of the web UI display
  defaults.
- Switched USB OTG frame image generation to Chromium screenshots of the hidden
  frame-render pages so Diagnostics preview and exported drive images share the
  same renderer.
- Start USB OTG frame-image regeneration in the background after saving USB OTG
  image-export settings when export is enabled, so Settings redirects without
  waiting for screenshots and drive reattachment to finish.
- Added a USB OTG drive refresh action that reattaches the existing backing
  disk image without regenerating frame images.
- Added Settings warnings for aggressive gateway polling intervals below
  300 seconds and for USB OTG exports that run faster than gateway polling,
  plus clearer USB OTG `Backing disk image` wording.
- Added a Settings action to shut down the Raspberry Pi safely from the web UI,
  plus installer-managed scoped sudo permissions for restart, reboot, and
  shutdown host-control actions.
- Added a dedicated BM300 Pro/BM7 live polling driver, selected from the
  configured device type, with voltage, state-of-charge, temperature, RSSI, and
  device-state support kept separate from the existing BM200/BM6 driver.
- Added commercial device type choices for BM6, BM7, BM300, BM300 Pro, BM900,
  and BM900 Pro while keeping them mapped to the existing isolated driver
  families.
- Added freeform overview colors with a native color picker, while preserving
  the existing color presets for quick selection.

### Fixed

- Fixed Raspberry Pi service refreshes so deployments preserve USB OTG Fleet
  Trend metric, range, and device-selection settings instead of dropping them
  from `config.toml`.
- Fixed USB OTG Battery Overview frame captures so overview cards fit inside
  the exported image and added a latest-sample timestamp to the frame title.
- Tightened USB OTG Fleet Trend frame captures by removing the outer chart
  wrapper gap and expanding the plot to the frame edges.
- Fixed USB OTG Chromium screenshot sizing by compensating for Raspberry Pi
  headless Chromium's outer-window inset before cropping to the configured
  frame dimensions.
- Fixed USB OTG Fleet Trend frame title clipping by giving the compact title
  line enough vertical room and lowering the frame header while retaining
  horizontal ellipsis.
- Constrained the root USB OTG drive helper to safe backing-image and gadget
  name policies, and removed unnecessary Linux capabilities from the web
  service unit.
- Fixed USB OTG settings validation so bad numeric form values return an
  in-page validation error instead of disconnecting the web request.
- Fixed manual USB OTG frame exports so the explicit export action can force a
  one-off image generation even when automatic USB OTG exports are disabled.
- Fixed web-triggered background USB OTG frame exports so saving settings
  reuses the last stored snapshot instead of starting a concurrent polling run.
- Fixed settings-triggered USB OTG frame exports so repeated saves do not start
  concurrent drive-update workers.
- Fixed Settings status text so repeated saves do not claim a new USB OTG frame
  export started while an existing export is already running.
- Fixed USB OTG frame device selection so Battery Overview frame images honor
  the selected frame devices instead of only Fleet Trend charts.
- Fixed USB OTG Battery Overview frame layout so three selected devices render
  in one row and larger selections paginate into balanced frame pages.
- Fixed USB OTG Battery Overview frame pagination so frame preview and export
  pages always contain at most three devices, even when older configs request a
  larger per-image count.
- Fixed Diagnostics frame preview links so every generated Battery Overview
  frame page is available when selected devices span multiple pages.
- Fixed USB OTG Battery Overview frame status rendering so battery state,
  offline, and error conditions match the Home Battery Overview.
- Fixed `bm-gateway run --dry-run --export-usb-otg-now` so dry-run mode skips
  USB OTG drive writes instead of forcing an export.
- Fixed USB OTG export scheduling so future-dated export markers are treated as
  stale and exports can resume immediately.
- Fixed USB OTG image-size validation so config values above the helper's
  4096 MB limit are rejected before export.
- Restored and documented USB OTG host-mode restore behavior so BMGateway
  removes any `[all]` peripheral-mode `dwc2` overlay when it owns the boot-mode
  setting.
- Fixed USB OTG Fleet Trend frame latest-value rows for duplicate device names
  by matching values with unique series identifiers.
- Updated the config schema for `web.language` and the `[usb_otg]` settings so
  packaged examples, runtime validation, and schema documentation stay aligned.
- Tightened the USB OTG root helper so sudo-launched drive exports copy only
  top-level readable files owned by the original sudo caller.
- Tightened installer privilege setup so `--disable-web` removes the web action
  sudoers policy instead of leaving passwordless web-service actions installed.
- Fixed device creation from the web UI so saving a new device redirects
  immediately while the first live polling cycle starts in the background.
- Reworked the Home Battery Overview so it uses responsive browser-measured
  pagination with at most two rows, instead of a user-configured visible-card
  limit.
- Refined History and Devices card lists with a clearer Batteries selector,
  responsive selector pagination, larger device badges, and shorter mobile edit
  actions.

## [0.1.1] - 2026-04-23

### Added

- Added a new architecture proposal documenting a dedicated service-account and
  privilege-hardening plan for `BMGateway`, including the current permission
  inventory, sudo scope, `systemd` hardening opportunities, and phased
  implementation guidance.
- Added a backlog proposition that references the service-account and
  privilege-hardening proposal so the investigation can be reused when the work
  is scheduled.
- Added editable gateway settings for MQTT broker and Home Assistant topic
  parameters, and updated the default MQTT username placeholder from
  `homeassistant` to `mqtt-user`.
- Documented Home Assistant auto-discovery in user-facing English, including
  the required MQTT broker path and a clearer explanation of
  `Home Assistant MQTT discovery`.
- Split editable settings into separate Gateway, MQTT, and Home Assistant
  sections and added inline help text for MQTT, Home Assistant, web, gateway,
  and Bluetooth options.
- Documented MQTT authentication behavior, retained discovery/state defaults,
  and why the Home Assistant discovery prefix defaults to `homeassistant`.
- Added a visible MQTT broker connection status row to the settings page.
- Added a Settings action to republish Home Assistant MQTT discovery and current
  device state to the configured broker on demand.
- Compacted the recent raw readings table on history pages with shorter column
  labels, smaller table text, non-wrapping cells, and a bounded scroll area.
- Made device IDs editable from the device edit form with validation, including
  stored-history ID collision checks and history-table renaming when an ID
  changes.
- Validated editable device IDs so MQTT topic paths stay limited to letters,
  numbers, underscores, and hyphens.
- Updated device ID renames to also normalize stored raw/archive metadata such
  as the device name, type, and MAC address so charts do not split old and new
  labels after a rename.
- Filtered the settings storage summary to configured devices so removed test
  devices no longer appear in the normal settings view.

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
