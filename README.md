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

The CLI entry point remains `bm-gateway`, and `python -m bm_gateway` remains a
supported module entry point through the root packaging configuration.

### `home-assistant/`

Contains Home Assistant facing artifacts such as:

- the MQTT topic and entity contract
- exportable discovery payload examples
- package snippets and dashboard definitions

### `rpi-setup/`

Contains Raspberry Pi setup and deployment guidance:

- a manual setup guide for Raspberry Pi 3B
- an Ansible area for later automation
- service installation and operational notes

### `web/`

Contains the host-run management web interface plan and assets.

The current Python component ships:

- a simple snapshot/status web server
- a separate host-run management web interface via `bm-gateway web manage`

For Raspberry Pi 3B, the active recommendation is a separate Python process
under `systemd`, not Docker. See
`docs/research/2026-04-17-pi3b-web-and-os-research.md`.

## Requirements

For development:

- Python `3.11`
- `uv`
- `make`
- `markdownlint`
- `shellcheck`

For the runtime target:

- Raspberry Pi 3B or compatible Linux host
- Bluetooth support
- enough storage for SQLite history retention

## Installation

Clone the repository and install the standalone CLI runtime:

```bash
git clone <repo-url>
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

## Roadmap

- Extend live Bluetooth support beyond the current BM200 implementation.
- Complete live BM200 history retrieval and persist decoded history packets.
- Add yearly degradation summaries on top of the existing daily and monthly rollups.
- Extend the Home Assistant assets under `home-assistant/`.
- Expand the Raspberry Pi setup guide into automation under `rpi-setup/ansible/`.
- Grow the host-run management web UI beyond the current config, contract,
  storage, and history views.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
