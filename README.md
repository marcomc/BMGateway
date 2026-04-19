# BMGateway

## Table of Contents

- [Overview](#overview)
- [Repository Structure](#repository-structure)
- [Components](#components)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Development](#development)
- [Deployment](#deployment)
- [Roadmap](#roadmap)
- [License](#license)

## Overview

`BMGateway` is a mono-repo for a Raspberry Pi based battery monitor gateway.

The repository is scaffolded from the shared Python CLI template, then extended
into four first-class parts:

- a packaged Python CLI and service layer
- Home Assistant integration assets
- Raspberry Pi setup and operations guidance
- a web interface area for the local UI

The management UI now ships as a BM300-inspired premium control plane:

- a card-first management dashboard with gateway stats, actions, API surface,
  Home Assistant contract visibility, and config editing
- a battery-first landing page at `/` with live device cards and a fleet chart
- a built-in battery/device icon catalog for the landing-page cards, selected
  during device registration without uploads or extra assets
- richer historical fleet overlays and interactive chart tooltips across the
  landing, history, and device pages
- a richer add-device flow that captures the official battery taxonomy:
  lead-acid vs lithium, AGM/EFB/GEL/custom, and custom voltage-to-SoC curves
- dedicated `/devices` and `/settings` pages that repeat the mobile-app style
  journey with gateway-safe content
- a chart-first history page with segmented Voltage / SoC / Temperature views
- temperature-aware BM6 history rollups so long-range temperature charts do not
  disappear outside the recent raw window
- a richer device detail page with SoC hero, runtime health cards, and calmer
  raw data presentation
- a management action for manual Bluetooth adapter recovery when live BLE
  polling needs operator intervention

The earlier ChatGPT research informed the problem space, but this repository
structure follows the local project template standards rather than that
exploratory draft layout.

## Repository Structure

```text
.
├── AGENTS.md
├── CHANGELOG.md
├── Makefile
├── README.md
├── TODO.md
├── docs/
├── home-assistant/
├── pyproject.toml
├── python/
│   ├── config/
│   ├── src/
│   └── tests/
├── rpi-setup/
├── scripts/
└── web/
```

## Components

### `python/`

Contains the packaged Python application:

- `python/src/bm_gateway/` for importable code
- `python/tests/` for test coverage
- `python/config/` for example config and schema artifacts
- CLI commands for config validation, device inspection, and Home Assistant
  contract rendering
- fake-reader runtime, snapshot persistence, MQTT publishing, and a simple
  built-in web status layer
- live `bm200` BLE polling, SQLite persistence, and classified device errors
- history inspection, storage stats, and retention pruning commands
- yearly summaries, degradation comparison windows, and richer MQTT
  availability semantics

The CLI entry point remains `bm-gateway`, and `python -m bm_gateway` remains a
supported module entry point through the root packaging configuration.

### `home-assistant/`

Contains Home Assistant facing artifacts such as:

- the MQTT topic and entity contract
- exportable discovery payload examples
- package snippets and dashboard definitions

### `rpi-setup/`

Contains Raspberry Pi setup and deployment guidance:

- a manual setup guide for the currently used Raspberry Pi gateway hardware
- a macOS Raspberry Pi Imager CLI provisioning guide
- an Ansible area for later automation
- service installation and operational notes

### `web/`

Contains the host-run management web interface plan and assets.

The current Python component ships:

- a simple snapshot/status web server
- a separate host-run management web interface via `bm-gateway web manage`
- premium management, history, and device pages built on the existing live
  server-rendered routes and APIs

For Raspberry Pi deployment, the active recommendation is a separate Python
process under `systemd`, not Docker. See
`docs/research/2026-04-17-pi3b-web-and-os-research.md` for the earlier Pi 3B
research baseline.

## Requirements

For development:

- Python `3.11`
- `uv`
- `make`
- `markdownlint`
- `shellcheck`

For the runtime target:

- the currently audited hardware is a Raspberry Pi `Model B Rev 2` with USB
  Wi-Fi and USB Bluetooth dongles
- a Raspberry Pi `3B`, `3B+`, `Zero W`, `Zero 2 W`, `4`, `400`, or `5` is the
  preferred baseline if you want integrated Wi-Fi and Bluetooth
- a Bluetooth adapter with BLE central support
- enough storage for SQLite history retention

Important hardware note:

- classic-only Bluetooth adapters are not sufficient for BM200 monitoring
- the audited USB dongle `0a12:0001` from Cambridge Silicon Radio powered on
  correctly, but exposed only BR/EDR and no BLE central role, so it could not
  scan or connect to BM200 devices

## Installation

For Raspberry Pi or any other host install, the intended target is
`make install`, not `make install-dev`.

### One-Liner Bootstrap

If you already have a checkout of this repository on the target machine, the
shortest supported install path is:

```bash
./scripts/bootstrap-install.sh
```

That script:

- installs apt prerequisites
- installs `uv` if it is missing
- clones or updates the repository checkout
- runs `make install` with the host `python3`
- installs and starts the runtime and web `systemd` services by default
- preserves and updates user config under `~/.config/bm-gateway/`
- prints the management URLs at the end of the run

Supported bootstrap options:

- `--disable-web` keeps the runtime service but disables the management UI
- `--disable-home-assistant` disables MQTT and Home Assistant publishing in the
  installed config
- `--skip-services` performs only the standalone CLI install
- `--web-port <port>` changes the management UI port

If you publish the bootstrap script at a reachable URL, the same flow becomes a
single remote one-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/marcomc/BMGateway/main/scripts/bootstrap-install.sh | bash -s -- --repo-url https://github.com/marcomc/BMGateway.git
```

### Manual Install

Clone the repository and install the standalone CLI runtime:

```bash
git clone https://github.com/marcomc/BMGateway.git
cd BMGateway
make install
```

`make install`:

- creates a standalone virtual environment in
  `~/.local/share/bm-gateway/venv`
- installs the packaged CLI into that runtime from the repository root
- links `bm-gateway` into `~/.local/bin/bm-gateway`
- installs a config template to `~/.config/bm-gateway/config.toml` if it is
  missing
- installs a device registry template to
  `~/.config/bm-gateway/devices.toml` if it is missing

### Editable Development Install

```bash
make install-dev
```

This links the local development environment into `~/.local/bin/bm-gateway`.

## Configuration

The Python CLI reads optional config from:

- `~/.config/bm-gateway/config.toml`
- or a file passed with `--config`

Start from the example files in `python/config/`:

- `python/config/config.toml.example`
- `python/config/devices.toml`
- `python/config/devices.toml.example`
- `python/config/gateway.toml.example`
- `python/config/config.schema.json`

The key runtime switch is `gateway.reader_mode`:

- `fake` keeps the deterministic development reader
- `live` enables explicit BLE polling for `bm200` devices

The default polling baseline is intentionally low-frequency:

- `gateway.poll_interval_seconds = 300`
- this means one collection cycle every 5 minutes by default
- tighter intervals are allowed, but they are an explicit opt-in for
  troubleshooting or short-term monitoring, not the project default

The key retention settings are:

- `retention.raw_retention_days`
- `retention.daily_retention_days`

## Usage

Show the focused CLI help:

```bash
bm-gateway
```

Inspect the resolved configuration:

```bash
bm-gateway config show
bm-gateway --config ./python/config/gateway.toml.example config show --json
python -m bm_gateway config show
```

Validate the config and registry:

```bash
bm-gateway --config ./python/config/gateway.toml.example config validate
```

Inspect configured devices:

```bash
bm-gateway --config ./python/config/gateway.toml.example devices list --json
```

Render the Home Assistant contract:

```bash
bm-gateway --config ./python/config/gateway.toml.example ha contract --json
```

Export Home Assistant discovery payload examples:

```bash
bm-gateway --config ./python/config/gateway.toml.example ha discovery --output-dir ./home-assistant/discovery
```

Inspect persisted history:

```bash
bm-gateway --config ./python/config/gateway.toml.example history daily --device-id bm200_house --json
bm-gateway --config ./python/config/gateway.toml.example history monthly --device-id bm200_house --json
bm-gateway --config ./python/config/gateway.toml.example history yearly --device-id bm200_house --json
bm-gateway --config ./python/config/gateway.toml.example history compare --device-id bm200_house --json
bm-gateway --config ./python/config/gateway.toml.example history stats --json
bm-gateway --config ./python/config/gateway.toml.example history prune
```

Run the fake-reader runtime once and persist a snapshot:

```bash
bm-gateway --config ./python/config/gateway.toml.example run --once --dry-run --json
```

Enable real BM200 polling by setting `gateway.reader_mode = "live"` in the
config, then run:

```bash
bm-gateway --config ./python/config/gateway.toml.example run --once --json
```

The project default is a 5-minute polling interval because this is a battery
gateway, not a real-time telemetry stream. That reduces BLE churn, lowers
device wakeups, and fits weaker Raspberry Pi hardware better. If you need
short-interval diagnostics, lower `gateway.poll_interval_seconds` explicitly.

Render HTML from the latest snapshot:

```bash
bm-gateway web render --snapshot-file ./python/config/data/runtime/latest_snapshot.json
```

Run the host-managed web UI:

```bash
bm-gateway --config ./python/config/gateway.toml.example web manage --port 8080
```

Runtime artifacts written by `run`:

- `.../runtime/latest_snapshot.json`
- `.../runtime/gateway.db`

Per-device payloads now include:

- `state`
- `error_code`
- `error_detail`

The database keeps:

- raw per-cycle readings with pruning
- daily device rollups for long-term comparison
- monthly summaries derived from daily rollups
- yearly summaries and degradation comparison windows derived from daily rollups

## Development

Sync the environment and run the default quality gate:

```bash
make check
```

Common commands:

```bash
make sync
make test
make lint
make run
```

Remote development deployment:

```bash
make dev-deploy TARGET=admin@host
```

That command syncs the current checkout to the remote host, runs
`make install`, and refreshes the runtime and web services with
`rpi-setup/scripts/install-service.sh`.

The automated test suite now covers:

- direct CLI invocation through `bm-gateway`
- module invocation through `python -m bm_gateway`
- subprocess-driven fake-device runtime flows
- HTTP checks for `web serve` and `web manage`

## Deployment

For a repository-backed Raspberry Pi install, use the documented bootstrap flow:

```bash
./scripts/bootstrap-install.sh
```

For iterative development deployments to an already bootstrapped host, use:

```bash
make dev-deploy TARGET=admin@host
```

Optional override:

```bash
make dev-deploy TARGET=admin@host REMOTE_DIR=/srv/bm-gateway-dev
```

The dev deploy path:

- syncs the current local checkout with `rsync`
- runs `make install` on the remote host with its local `python3`
- refreshes `bm-gateway.service` and `bm-gateway-web.service`

## Roadmap

- Extend live Bluetooth support beyond the current BM200 implementation.
- Complete live BM200 history retrieval and persist decoded history packets.
- Add yearly degradation summaries on top of the existing daily and monthly rollups.
- Extend the Home Assistant assets under `home-assistant/`.
- Expand the Raspberry Pi setup guide into automation under `rpi-setup/ansible/`.
- Grow the host-run management web UI beyond the current config, contract,
  storage, analytics, and history views.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
