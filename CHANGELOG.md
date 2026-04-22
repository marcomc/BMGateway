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
- Archive-history plumbing now merges imported device-memory voltage rows into
  the Battery/History/Device charts without duplicate timestamps, and the
  runtime can plan reconnect backfill attempts for the BM200 history path.
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
- Fleet and history chart hover tooltips now show all device values present at
  the hovered point, and Battery overview cards now prefer saved registry names
  over stale runtime snapshot names.
- Battery overview cards now use a tighter square layout with smaller badge
  frames, denser typography, and gauge text that stays inside the SoC ring on
  compact screens.
- Battery overview cards now use a more compact identity stack by removing the
  duplicate temperature line from the description, compressing battery brand /
  model / capacity onto one line, and scaling the SoC ring up again for better
  mobile readability.
- Web display settings now control the default chart range and chart metric for
  Battery, History, and Device Detail pages, with `7 days` as the shipped
  default range.
- Battery overview display settings now use visible-card limits of `2`, `4`,
  `6`, or `8` to match the current overview layout model.
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

### Changed

- Daily chart rollups now use their real `last_seen` timestamp when available,
  so the latest visible point can align to the right edge of Battery, History,
  and Device Detail charts instead of being pushed left by a synthetic noon
  timestamp.
- Fleet Trend, History, and Device Detail chart selectors now expose visible
  day ranges of `1`, `3`, `5`, `7`, `30`, `90`, `1 year`, `2 years`, and
  `All`, and no longer show the `Recent raw` selector in the UI.
- Settings summary `Actions` now includes recovery controls for restarting
  `bm-gateway.service`, restarting `bluetooth.service`, and scheduling a
  Raspberry Pi reboot.
- Settings `Actions` now execute service restarts and host reboot through
  non-interactive `sudo`, and Raspberry Pi reboot now redirects to a waiting
  page that keeps checking the gateway until it comes back online.
- The packaged `bm-gateway-web.service` unit now keeps the minimum additional
  capabilities needed for those maintenance actions to invoke `sudo -n`
  successfully, instead of failing inside the systemd service sandbox.
- Fleet Trend, History, and Device Detail charts now support previous/next
  range paging plus direct drag/pan interaction with mouse or touch, so the
  current day window can be moved backward or forward naturally.
- Fleet Trend legends are now clickable, so each device series can be toggled
  on or off while comparing historical overlays.
- Fixed a chart-script regression that could leave Fleet Trend and History
  chart frames blank by shipping invalid JavaScript to the browser.
- Battery overview cards now show a clear red `Unable to connect` state when
  the live snapshot reports `device_not_found`, instead of the softer
  `No recent sample` wording, while Fleet Trend continues to show retained
  historical data separately from live connectivity.
- Battery overview cards now render at a smaller scale, with tighter
  proportions and larger icon glyphs inside the device badges.
- Battery overview cards now scale down more uniformly, including the card
  shell, gauge block, badge stack, button, and text sizing, so the shorter
  layout stays proportional instead of only shrinking a few inner elements.
- Battery overview badges now use smaller square frames with larger glyph fill,
  the SoC ring is sized to keep `100%` and status text inside the circle, and
  the Add Device `+` icon is larger for touch visibility.
- Battery overview cards are now whole-card links, with larger one-line
  identity text, temperature shown inside the SoC ring, and the old
  `Device Details` footer button removed to free space on compact layouts.
- Device add/edit now accepts non-MAC serial-style identifiers in the `MAC or
  serial` field instead of rejecting them as invalid Bluetooth addresses.
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
- The History page now uses a simpler product-style header, card-based battery
  switching instead of redundant dropdown controls, and the battery overview
  cards now use tappable `Device Details` buttons plus an inline SoC gauge.
- Fleet, device, and history charts now include an `All` range and clearer
  window/coverage messaging, so longer ranges explain when they are simply
  showing all retained history instead of appearing broken or unchanged.
- The battery overview now supports a configurable visible-card limit, paged
  horizontal navigation for larger fleets, and a larger integrated battery
  tile design with the SoC gauge, icon, and device identity combined into one
  primary mobile-style surface.
- Web appearance preferences now support `light`, `dark`, and `system` modes,
  and the settings page exposes the current appearance choice alongside the
  existing display controls.
- Persistent per-device overview colors with uniqueness enforcement in the
  registry and add/edit device flows, so each battery now keeps the same color
  across overview cards, history selectors, and charts.
- Devices page cards and the add/edit device flows now share the same dark and
  light theme surface system, with more compact registry cards and battery
  setup panels that no longer mix light-only blocks into dark mode.
- Add/edit device flows now derive visual badges automatically from battery
  and vehicle metadata, remove manual icon picking from the web UI, and
  generate device IDs automatically from the device name.
- Battery overview cards now place stacked automatic badges beside the device
  identity, keep the SoC circle clear of badge overlap, and use stronger dark
  mode gauge contrast on both the battery overview and device detail pages.
- The web implementation is now split more cleanly into a service entrypoint,
  page-rendering module, mutation/actions module, and packaged CSS/JS assets,
  reducing duplication between request handling and HTML generation while
  making the shipped web layer lighter to maintain.
- Battery overview paging now honors the full `2 / 4 / 6 / 8` visible-card
  model by using a `4x2` layout for eight-card pages, and configured devices
  that are missing from the latest runtime snapshot still remain visible on
  the Battery page instead of disappearing until the next collection cycle.
- Overview color selection now shows a live color preview beside the control,
  and the vehicle taxonomy now includes scooter and electric-bike installs.

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
- The mobile battery overview now uses compact two-card rows instead of a
  single oversized card, the add-device entry moved into the Bluetooth warning
  banner, and the history selector now uses smaller non-overlapping cards.
- Light and dark icon badges now use stronger theme-specific fills and chart
  surfaces now follow the active theme instead of keeping a white plot in dark
  mode.
- Settings summary cards are more compact, and mobile settings edit rows now
  keep labels and controls on the same row to avoid large vertical gaps.
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
  falling back to `No recent sample` after successful polls.
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
- Battery overview cards now pin a high-contrast icon badge in the card corner
  and keep the SoC gauge focused on percentage, status, and voltage, while the
  History selector uses compact battery-identity cards instead of larger
  status-heavy tiles.
- The responsive web UI now rebalances one-card and small-fleet layouts across
  Battery, History, and Devices, enlarges the battery gauge on both desktop and
  mobile, and uses a darker Apple-style surface hierarchy with higher-contrast
  controls when dark mode is active.

### Documented

- The currently tested CSR USB Bluetooth dongle (`0a12:0001`) exposes only
  classic BR/EDR and cannot provide the BLE central role required by BM200
  monitoring.
- The Battery landing surface is now internally treated as `Home`, and the
  Devices page now renders configured hardware as a compact color-coded list
  with small badges and direct edit actions instead of large status cards.
- Home Assistant MQTT discovery now publishes richer entity metadata, including
  binary sensors for gateway/device connectivity plus proper units, device
  classes, and diagnostic categories, and the repository now includes a full
  Home Assistant setup guide without requiring a custom integration.
