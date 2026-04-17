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

The CLI entry point remains `bm-gateway`, and `python -m bm_gateway` remains a
supported module entry point through the root packaging configuration.

### `home-assistant/`

Reserved for Home Assistant facing artifacts such as:

- MQTT discovery payload examples
- package snippets
- dashboard definitions
- operator notes for HA setup

### `rpi-setup/`

Reserved for Raspberry Pi setup and deployment guidance:

- manual setup instructions first
- Ansible playbooks and inventory later
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
- `python/config/config.schema.json`

## Usage

Show the focused CLI help:

```bash
bm-gateway
```

Inspect the resolved configuration:

```bash
bm-gateway info
bm-gateway --config ./python/config/config.toml.example info --json
python -m bm_gateway info
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

- Replace the placeholder `info` command with gateway-oriented commands.
- Define the MQTT and Home Assistant contract under `home-assistant/`.
- Write the Raspberry Pi setup guide under `rpi-setup/`.
- Choose and scaffold the web interface under `web/`.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
