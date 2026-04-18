# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

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
