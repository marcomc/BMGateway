# BMGateway

## Table of Contents

- [Overview](#overview)
- [Choose Your Path](#choose-your-path)
- [What Is Included](#what-is-included)
- [Repository Structure](#repository-structure)
- [Documentation Map](#documentation-map)
- [Development](#development)
- [Release Status](#release-status)
- [Credits And Attribution](#credits-and-attribution)
- [License](#license)

## Overview

`BMGateway` is a Raspberry Pi battery-monitor gateway for BM200/BM6-family
devices.

It ships as one Python codebase with two executables:

- `bm-gateway` for runtime collection, configuration, history, and Home
  Assistant publishing
- `bm-gateway-web` for the optional local web application

The project is intentionally battery-first:

- live polling from the Raspberry Pi
- retained local history in SQLite
- Home Assistant integration through MQTT discovery
- a mobile-friendly local web UI for Home, History, Devices, and Settings

## Choose Your Path

### I Want To Install It On A Raspberry Pi

Start here:

- [rpi-setup/manual-setup.md](rpi-setup/manual-setup.md)

If you want to prepare the SD card from macOS first:

- [rpi-setup/macos-imager-cli.md](rpi-setup/macos-imager-cli.md)

### I Want To Connect It To Home Assistant

Start here:

- [home-assistant/setup.md](home-assistant/setup.md)

Reference contract:

- [home-assistant/contract.md](home-assistant/contract.md)

### I Want To Develop Or Modify The Project

Start here:

- [python/README.md](python/README.md)
- [docs/README.md](docs/README.md)

## What Is Included

- Packaged runtime CLI and web executable
- Live BM200/BM6-family polling path
- SQLite history with raw, daily, monthly, and yearly views
- Optional Home Assistant MQTT discovery integration
- Raspberry Pi bootstrap and `systemd` service installation
- Local web app with:
  - Home
  - History
  - Device Detail
  - Devices
  - Settings
- Light/dark/system appearance modes
- Modular web localization with a Settings language selector
- Per-device colors, badges, and battery metadata
- Battery, fleet, history, and device charts

For the first release summary, use [CHANGELOG.md](CHANGELOG.md).

## Repository Structure

```text
.
├── CHANGELOG.md
├── README.md
├── TODO.md
├── docs/
├── home-assistant/
├── python/
├── rpi-setup/
└── web/
```

- `python/` contains the packaged application and tests
- `home-assistant/` contains the MQTT contract and Home Assistant assets
- `rpi-setup/` contains Raspberry Pi installation and operations docs
- `web/` contains the web product boundary notes
- `docs/` contains architecture, research, and development notes

## Documentation Map

Use one canonical source per topic:

| Topic | Canonical document |
| --- | --- |
| First-release summary | [CHANGELOG.md](CHANGELOG.md) |
| Active backlog | [TODO.md](TODO.md) |
| Python package and contributor entry point | [python/README.md](python/README.md) |
| Developer notes and architecture index | [docs/README.md](docs/README.md) |
| Home Assistant setup | [home-assistant/setup.md](home-assistant/setup.md) |
| Home Assistant MQTT contract | [home-assistant/contract.md](home-assistant/contract.md) |
| Raspberry Pi installation | [rpi-setup/manual-setup.md](rpi-setup/manual-setup.md) |
| Web product boundary | [web/README.md](web/README.md) |

## Development

Primary maintainer commands:

```bash
make install-dev
make check
make dev-deploy TARGET=admin@host
```

The default quality gate is `make check`.

## Release Status

The current documented first release is:

- `0.1.1`

Use [CHANGELOG.md](CHANGELOG.md) for release content and [TODO.md](TODO.md) for
work that is not shipped yet.

## Credits And Attribution

`BMGateway` is an original project, but it builds on upstream open-source
software and protocol research that should be credited explicitly.

### Open-Source Software Used

- [Bleak](https://github.com/hbldh/bleak) by
  [Henrik Blidh](https://github.com/hbldh) and contributors.
  `BMGateway` uses `Bleak` as the Python BLE client/scanner foundation for the
  Raspberry Pi live polling path. Thanks to the Bleak maintainers and
  contributors for the library and surrounding troubleshooting knowledge.

### Protocol / Reverse-Engineering References

- BM6 reverse-engineering reference by
  [tarball.ca](https://www.tarball.ca/posts/reverse-engineering-the-bm6-ble-battery-monitor/).
  This informed parts of the BM6/BM200 protocol investigation. Thanks for the
  published research.
- BM6/Home Assistant community discussion:
  [Home Assistant BM6 thread](https://community.home-assistant.io/t/bm6-battery-monitor-esphome/806239).
  This helped validate practical behavior seen on live hardware. Thanks to the
  community contributors for sharing findings.
- BM2/BM6 community discussion:
  [OpenMQTTGateway BM2 thread](https://community.openmqttgateway.com/t/omg-1-8-0-no-longer-gets-bm2-messages/3578).
  This provided useful context during compatibility debugging. Thanks to the
  contributors there as well.

### Attribution Policy

Whenever code, protocol logic, assets, or meaningful implementation ideas are
adapted from other open-source projects in the future, they must be added to
this section with:

- the project name
- a link to the canonical Git repository when available
- the author or maintainer name when known
- a short note explaining what `BMGateway` reused or was inspired by

## License

[MIT](LICENSE)
