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

The CLI entry point remains `bm-gateway`, and `python -m bm_gateway` remains a
supported module entry point through the root packaging configuration.

### `home-assistant/`

Contains Home Assistant facing artifacts such as:

- the MQTT topic and entity contract
- integration notes and future package snippets
- a place for dashboard definitions

### `rpi-setup/`

Contains Raspberry Pi setup and deployment guidance:

- a manual setup guide for Raspberry Pi 3B
- an Ansible area for later automation
- service installation and operational notes

### `web/`

Reserved for the local web interface.

The exact implementation remains open. Containerized deployment is acceptable
if the chosen stack is realistic for Raspberry Pi 3B constraints.

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
- optional Docker support if the web interface or supporting services use it

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
  `~/.config/bm-gateway/devices.toml.example` if it is missing

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
- `python/config/devices.toml.example`
- `python/config/gateway.toml.example`
- `python/config/config.schema.json`

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

- Build the Bluetooth polling and publish runtime behind the documented
  contract.
- Extend the Home Assistant assets under `home-assistant/`.
- Expand the Raspberry Pi setup guide into automation under `rpi-setup/ansible/`.
- Choose and scaffold the web interface under `web/`.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
