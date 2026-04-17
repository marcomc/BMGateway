# Raspberry Pi 3B Manual Setup

## Scope

This guide bootstraps a Raspberry Pi 3B to the point where the `BMGateway` CLI
can validate config, inspect the device registry, and render the Home Assistant
contract.

It does not yet install the future long-running Bluetooth polling service.

## Base System

- Install Raspberry Pi OS
- Ensure the Pi has network access
- Ensure Bluetooth is enabled
- Ensure the system clock and timezone are correct

Recommended checks:

```bash
uname -a
bluetoothctl --version
timedatectl
```

## System Packages

Install the packages needed for Python development and Bluetooth tooling:

```bash
sudo apt update
sudo apt install -y bluetooth bluez curl git make
```

Verify the Bluetooth adapter is visible:

```bash
bluetoothctl list
```

If the adapter is not visible, inspect Raspberry Pi Bluetooth configuration
before proceeding.

## Install `uv`

Install `uv` with the official bootstrap command:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the shell or source the updated profile so `uv` is on `PATH`.

## Clone the Repository

```bash
git clone <repo-url>
cd BMGateway
```

## Install the CLI

```bash
make install
```

This creates:

- a standalone runtime under `~/.local/share/bm-gateway/venv`
- a user-facing command at `~/.local/bin/bm-gateway`
- a config template at `~/.config/bm-gateway/config.toml` if missing
- a devices template at `~/.config/bm-gateway/devices.toml.example` if missing

## Configure the Gateway

Use the example files in `python/config/` as the starting point:

- copy `python/config/config.toml.example` to
  `~/.config/bm-gateway/config.toml`
- copy `python/config/devices.toml.example` beside it if you want a separate
  working copy
- replace MQTT and device values with real values

## Validate the Setup

```bash
bm-gateway config show
bm-gateway config validate
bm-gateway devices list --json
bm-gateway ha contract --json
```

Expected outcomes:

- `config show` prints the resolved settings
- `config validate` reports a valid configuration
- `devices list --json` prints the configured devices
- `ha contract --json` prints the MQTT topics and entities expected by Home
  Assistant

## Repository Areas

- `python/` contains the packaged CLI and future runtime code
- `home-assistant/` contains the MQTT/Home Assistant contract docs
- `rpi-setup/ansible/` is reserved for future automation
- `web/` is reserved for the future local UI

## Next Step

Once the manual flow is stable, encode it under `rpi-setup/ansible/` instead of
editing the Pi by hand.
