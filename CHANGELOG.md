# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Dedicated `bm-gateway-web` executable for the optional management UI.
- Initial project scaffold generated from `python-cli-template`.
- Mono-repo layout with first-class `python/`, `home-assistant/`,
  `rpi-setup/`, and `web/` components.
- Foundation spec and implementation plan for the first delivery slice.
- Real Python CLI commands for config inspection, validation, device listing,
  and Home Assistant contract rendering.
- Home Assistant discovery payload export through `bm-gateway ha discovery`.
- Example gateway and device registry TOML files.
- Home Assistant MQTT contract documentation, exported discovery examples,
  package helpers, and a starter dashboard.
- Fake-reader runtime, snapshot persistence, MQTT publishing, and web
  rendering/serving commands.
- BM200 live BLE protocol support with AES decryption, packet parsing, and
  runtime integration behind `gateway.reader_mode = "live"`.
- SQLite persistence for gateway snapshots and device readings, plus explicit
  `error_code` and `error_detail` fields in runtime payloads.
- Raw-retention pruning and daily SQLite rollups for longer-term history on
  Raspberry Pi storage.
- CLI history inspection commands for raw, daily, and monthly summaries.
- Storage summary and manual retention-pruning commands under `history`.
- Yearly history summaries and degradation-comparison analytics from persisted
  rollups.
- Built-in SVG icon selection for battery overview cards, wired into the
  device registry and add-device flow without uploads or external assets.
- Host-run Python management web interface with config/device TOML editing,
  history views, and one-shot run triggering.
- Expanded management web interface coverage for configured devices, Home
  Assistant contract/discovery views, storage summary, manual history pruning,
  device analytics pages, and trend charts.
- End-to-end subprocess regression coverage for `bm-gateway`,
  `python -m bm_gateway`, `web serve`, and `web manage`.
- MQTT availability topics and richer device availability/error payload
  semantics.
- macOS Raspberry Pi Imager CLI guide, wrapper script, and first-run bootstrap
  example for SD-card provisioning.
- Runtime persistence now survives MQTT publish failures instead of aborting the
  collection cycle.
- Source-backed Raspberry Pi 3B / Raspberry Pi OS 32-bit / Docker viability
  research under `docs/research/`.
- Raspberry Pi 3B manual setup guide, systemd service assets, install/update
  scripts, and an initial Ansible playbook.
- Separate `bm-gateway-web.service` host process for the management UI.
- Host bootstrap install script that installs apt prerequisites, `uv`,
  clone-or-update checkout state, and the standalone `make install` runtime in
  one step.
- Full appliance bootstrap that now installs and starts the runtime and web
  services, prints management URLs, and accepts `--disable-web` /
  `--disable-home-assistant` options.
- Web-based device-add flow that normalizes compact BM200 serials into MAC
  format and enables live polling when the first device is added.
- Standalone install now reuses an existing runtime venv on upgrade instead of
  failing on repeated installs.
- BM300-inspired premium redesign for the server-rendered management, history,
  and device pages, including reusable UI primitives, calmer operational
  hierarchy, and interactive metric/range charts backed by live gateway data.
- BM300-style battery landing page plus dedicated devices and settings routes,
  giving the web app a full product journey instead of only admin-centric
  pages.
- Remote development deployment now supports
  `make dev-deploy TARGET=admin@host` for syncing the current checkout to an
  already bootstrapped host and refreshing the runtime/web services.
- Developer integration notes under `docs/` for verified BM6/BM200 live
  behavior, separating upstream knowledge from BMGateway-specific findings.
- Device registry battery metadata for lead-acid/lithium profiles, custom
  algorithm selection, and editable voltage-to-SoC curves in the web add-device
  flow.
- Dedicated device-edit flow with editable device type, battery profile,
  installation context, and icon selection.
- Richer device registry metadata for vehicle type plus battery brand, model,
  capacity, and production year, exposed through both add-device and
  edit-device web flows.
- Optional `glances-web.service` install flow plus Raspberry Pi runbook
  coverage for exposing a Home Assistant-compatible Glances API on the
  gateway host.
- Optional Cockpit install flow plus Raspberry Pi runbook coverage for a
  separate HTTPS host-administration console on port `9090`.
- Explicit device selection on the History page, including configured-device
  quick switching, first-device fallback for `/history`, and a no-devices
  empty state instead of an ambiguous blank history view.

### Changed

- Standalone and development installs now link both `bm-gateway` and
  `bm-gateway-web`, and the web `systemd` service now launches the dedicated
  web executable directly.
- Documentation now treats the root `README.md` as overview-only, with
  architecture, Raspberry Pi setup, and component details maintained in their
  canonical docs instead of repeated across files.
- Runtime appliance config now uses a live-ready empty device registry instead
  of shipping sample hardware into the installed user config.
- Raspberry Pi service install now renders units for the active user and
  installs a stable `/usr/local/bin/bm-gateway` symlink for systemd.
- The runtime now performs one bounded Bluetooth recovery and retry after
  `not found` / timeout-class BM200 live failures, and the management UI now
  exposes a manual Bluetooth recovery action.
- The shared chart renderer now uses richer time-axis formatting, interactive
  tooltips, calmer fills, and historical fleet overlays on the battery landing
  page.
- Daily rollups now exclude error snapshots from voltage/SoC averages, the
  history charts only plot valid samples, and repaired rollups can be rebuilt
  from raw readings so long-range history stays readable after BLE outages.
- BM200 discovery misses are now classified as `device_not_found` / offline
  instead of a generic `driver_error`, and the Devices page explains that the
  monitor was not advertising during the latest scan window.
- BM6-family live parsing now captures temperature, and daily/monthly history
  rollups retain temperature averages so long-range temperature charts work.
- History chart controls now use horizontally scrollable mobile rails with
  `Recent raw`, `1 day`, `7 days`, `30 days`, `90 days`, `1 year`, and `2 years`
  ranges instead of wrapping into overlapping pills on narrow screens.
- Web defaults now bind to port `80`, keep chart point markers disabled by
  default, and expose both options through config plus the Settings page.
- Gateway-level administration is now labeled and linked as `Gateway`, while
  `/devices` now opens a dedicated `/devices/edit` flow instead of redirecting
  device edits to the gateway page.
- Signal quality tiles now show a readable BLE grade, percentage, visual bar
  strength, and the latest RSSI instead of blank placeholder values.
- The web IA now separates read-only `/settings` from editable `/gateway`,
  keeps device creation under `/devices`, and replaces the confusing
  `Gateway` jump buttons with clearer settings-oriented navigation.
- Gateway web/display preference saves now preserve untouched values instead of
  resetting the other setting when one split form is submitted.
- `make dev-deploy` now preserves existing optional Glances and Cockpit host
  services instead of silently dropping them on a routine application refresh.
- Battery overview cards now use a stronger BM-style hierarchy with larger SoC
  numerals, larger battery/device icons, and explicit OK/charging status
  symbols instead of generic status chips.
- Live BM200/BM6 reads now preserve scan RSSI in the snapshot/runtime model, so
  device and devices pages show real BLE signal quality instead of incorrectly
  falling back to `Not visible` after successful polls.
- Device detail pages now expose an inline expandable reported-status explainer,
  showing that BM200/BM6 states are device-reported categories, surfacing the
  protocol code, and visualizing the discrete status scale in-page instead of
  only showing a bare `Normal` label.
- The devices flow now uses a dedicated `/devices/new` creation page, and the
  settings surface now merges summary and edit tasks into `/settings` with an
  explicit edit mode instead of splitting users between `/settings` and
  `/gateway`.
- Settings edit mode now uses inline row controls instead of stacked summary
  values plus separate forms, and it exposes editable gateway name/timezone,
  web host/enablement, and Bluetooth adapter/timeout settings directly in the
  web UI.
- The Bluetooth adapter selector now uses the host's detected adapters instead
  of a free-text field and highlights missing / absent adapters in the
  settings UI.

### Documented

- The currently tested CSR USB Bluetooth dongle (`0a12:0001`) exposes only
  classic BR/EDR and cannot provide the BLE central role required by BM200
  monitoring.
