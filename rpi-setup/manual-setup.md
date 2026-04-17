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
- a devices registry at `~/.config/bm-gateway/devices.toml` if missing

## Configure the Gateway

Use the example files in `python/config/` as the starting point:

- copy `python/config/config.toml.example` to
  `~/.config/bm-gateway/config.toml`
- copy `python/config/devices.toml` beside it if you want a separate working
  copy
- replace MQTT and device values with real values

## Validate the Setup

```bash
bm-gateway config show
bm-gateway config validate
bm-gateway devices list --json
bm-gateway ha contract --json
bm-gateway run --once --dry-run --json
```

Expected outcomes:

- `config show` prints the resolved settings
- `config validate` reports a valid configuration
- `devices list --json` prints the configured devices
- `ha contract --json` prints the MQTT topics and entities expected by Home
  Assistant
- `run --once --dry-run --json` writes a local snapshot without contacting MQTT

## Install the Service Assets

To install the runtime service unit on the Pi:

```bash
sudo ./rpi-setup/scripts/install-service.sh
```

This installs:

- `/etc/bm-gateway/config.toml`
- `/etc/bm-gateway/devices.toml`
- `/etc/systemd/system/bm-gateway.service`

Review the config, then start the service:

```bash
sudo systemctl start bm-gateway.service
sudo systemctl status bm-gateway.service
```

## Repository Areas

- `python/` contains the packaged CLI and future runtime code
- `home-assistant/` contains the MQTT/Home Assistant contract docs and assets
- `rpi-setup/ansible/` contains the first provisioning playbook
- `rpi-setup/systemd/` contains the service unit
- `rpi-setup/scripts/` contains install and update helpers
- `web/` contains Docker packaging for the status interface

## Next Step

Use the Ansible playbook when you want to stop managing the Pi by hand.
