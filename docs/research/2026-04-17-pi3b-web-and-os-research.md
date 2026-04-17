# Raspberry Pi 3B Web and OS Research

## Summary

For `BMGateway` on Raspberry Pi 3B, the recommended near-term architecture is:

- run the collector/runtime as a host Python process under `systemd`
- run the management web UI as a separate host Python process under `systemd`
- keep Docker out of the active Raspberry Pi 3B deployment plan
- use SQLite with raw-retention pruning and daily rollups

This keeps BLE collection isolated from the web UI without paying the extra
operational and compatibility cost of Docker on Raspberry Pi OS 32-bit.

## Findings

### Raspberry Pi 3B hardware baseline

Raspberry Pi’s product page lists Raspberry Pi 3 Model B with:

- quad-core 1.2 GHz BCM2837 64-bit CPU
- 1 GB RAM
- onboard Bluetooth Low Energy

That is enough for a Python collector plus a lightweight Python web process,
but it is not a generous system for extra container overhead or a heavy web
stack.

Source:

- [Raspberry Pi 3 Model B](https://www.raspberrypi.com/products/raspberry-pi-3-model-b/)

### Latest stable Raspberry Pi OS 32-bit supported by Pi 3B

As of April 17, 2026, Raspberry Pi’s OS downloads page lists:

- `Raspberry Pi OS (32-bit)` based on Debian 13 `trixie`
- release date `April 13, 2026`
- compatibility: `All Raspberry Pi models`

So the latest stable 32-bit Raspberry Pi OS for Pi 3B is the Trixie-based
32-bit release dated April 13, 2026.

Source:

- [Raspberry Pi OS downloads](https://www.raspberrypi.com/software/operating-systems/)

### Docker on Raspberry Pi OS 32-bit

Docker’s official Raspberry Pi OS 32-bit installation page states:

- Docker Engine `v28` is the last major version to support Raspberry Pi OS
  32-bit (`armhf`)
- starting with Docker Engine `v29`, new major versions will no longer provide
  packages for Raspberry Pi OS 32-bit

Docker also says the supported Raspberry Pi OS 32-bit targets are:

- Bookworm 12 stable
- Bullseye 11 oldstable

This makes Docker a poor primary architectural dependency for a Pi 3B running
32-bit Raspberry Pi OS going forward.

Source:

- [Docker Engine on Raspberry Pi OS (32-bit / armhf)](https://docs.docker.com/engine/install/raspberry-pi-os/)

## Architecture Recommendation

### Collector

Keep the collector as the primary host process:

- Python
- `systemd`
- direct BLE access
- SQLite writes
- MQTT publishing

### Web UI

Use a second Python process for the web UI:

- separate `systemd` unit
- reads SQLite and snapshot data
- edits the same TOML config and device-registry files
- can trigger a one-shot collection cycle through the CLI/module path

### Why not Docker here

For Pi 3B on 32-bit Raspberry Pi OS:

- Docker support is on a deprecation path
- containerization adds operational complexity
- the failure boundary we want can already be achieved with separate Python
  processes and separate `systemd` units

### Why not PHP/Nginx

The collector, config parsing, runtime logic, and persistence are already
Python. Reusing Python models and services is lower risk and lighter than
introducing a second application stack.

## Storage Recommendation

Do not keep unbounded raw readings.

Recommended defaults:

- raw readings: `180` days
- daily rollups: unlimited by default

This supports long-term comparison of battery decline while keeping raw storage
bounded on microSD media.

## Follow-up Work

- add BM200 history retrieval into the database
- add richer daily and monthly degradation summaries
- add web UI pages for trend comparison across 6, 12, and 24 months
- revisit Docker only for 64-bit targets where it remains a supported
  deployment choice
