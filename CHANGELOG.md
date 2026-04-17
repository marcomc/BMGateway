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
- Host-run Python management web interface with config/device TOML editing,
  history views, and one-shot run triggering.
- Source-backed Raspberry Pi 3B / Raspberry Pi OS 32-bit / Docker viability
  research under `docs/research/`.
- Raspberry Pi 3B manual setup guide, systemd service assets, install/update
  scripts, and an initial Ansible playbook.
- Separate `bm-gateway-web.service` host process for the management UI.
