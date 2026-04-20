# BMGateway

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

## Overview

`BMGateway` is a Raspberry Pi battery monitor gateway built as one shared
Python codebase with two executables:

- `bm-gateway` for configuration, runtime collection, history inspection, and
  Home Assistant publishing
- `bm-gateway-web` for the optional local management web interface

The web UI is additive, not required. A runtime-only install is still a valid
and supported appliance shape when you only need CLI access plus Home Assistant.

## Architecture

The live project architecture is:

- shared core code in `python/src/bm_gateway/`
- runtime and Home Assistant surface through `bm-gateway`
- optional web surface through `bm-gateway-web`

This keeps config, BLE, SQLite, MQTT, and Home Assistant logic in one place
instead of maintaining separate Python products with duplicated behavior.

The authoritative boundary and migration decision lives in
[docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md).

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
├── rpi-setup/
├── scripts/
└── web/
```

- `python/` contains the packaged application, tests, and example config
- `home-assistant/` contains the MQTT contract and exported assets
- `rpi-setup/` contains Raspberry Pi install, service, and operations guidance
- `web/` contains web product notes and boundary documentation
- `docs/` contains cross-cutting architecture, specs, and research

## Quick Start

### Local Development

```bash
make install-dev
bm-gateway --config ./python/config/gateway.toml.example config validate
bm-gateway --config ./python/config/gateway.toml.example run --once --dry-run --json
bm-gateway-web --config ./python/config/gateway.toml.example --host 127.0.0.1 --port 8080
```

### Raspberry Pi Appliance Install

If the repository is already present on the target host:

```bash
./scripts/bootstrap-install.sh
```

That bootstrap path installs the standalone runtime, config templates, runtime
service, and optional web service. For the full appliance flow, service options,
and host operations details, use
[rpi-setup/manual-setup.md](rpi-setup/manual-setup.md).

### Runtime and Web Commands

- `bm-gateway config validate`
- `bm-gateway devices list`
- `bm-gateway ha contract`
- `bm-gateway run --once --dry-run --json`
- `bm-gateway history stats --json`
- `bm-gateway-web --config /path/to/config.toml`
- `bm-gateway-web serve --snapshot-file /path/to/latest_snapshot.json`
- `bm-gateway-web render --snapshot-file /path/to/latest_snapshot.json`

## Documentation

Use one canonical source per topic:

| Topic | Canonical doc |
| --- | --- |
| Architecture and migration plan | [docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md) |
| Documentation index | [docs/README.md](docs/README.md) |
| Runtime and packaged Python component | [python/README.md](python/README.md) |
| Home Assistant MQTT contract | [home-assistant/contract.md](home-assistant/contract.md) |
| Raspberry Pi appliance install | [rpi-setup/manual-setup.md](rpi-setup/manual-setup.md) |
| Raspberry Pi Imager CLI flow | [rpi-setup/macos-imager-cli.md](rpi-setup/macos-imager-cli.md) |
| Hardware audit and service tuning | [rpi-setup/hardware-audit.md](rpi-setup/hardware-audit.md) |
| Web product boundary | [web/README.md](web/README.md) |

## Development

Primary maintainer commands:

```bash
make check
make install-dev
make dev-deploy TARGET=admin@host
```

`make check` runs:

- `uv run pytest -q`
- `uv run ruff check python/src python/tests`
- `uv run ruff format --check python/src python/tests`
- `uv run mypy python/src python/tests`
- repo Markdown linting
- shell script linting

## Roadmap

See [TODO.md](TODO.md) for the active backlog. Current themes are:

- BM200 live history retrieval
- BM300 Pro support decisioning
- richer degradation analytics
- Home Assistant/MQTT resilience improvements
- web security and hardening follow-up

## License

[MIT](LICENSE)
