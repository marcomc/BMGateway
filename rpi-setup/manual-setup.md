# Raspberry Pi Gateway Manual Setup

## Scope

This guide bootstraps the currently used Raspberry Pi gateway hardware to the
point where the `BMGateway` CLI can validate config, inspect the device
registry, and render the Home Assistant contract.

The actual audited host in this project is:

- Raspberry Pi `Model B Rev 2`
- Ethernet as the primary network path
- USB Wi-Fi dongle for wireless connectivity
- USB Bluetooth dongle for BLE connectivity

It also covers the current BM200 live polling path. BM300 Pro is still not
implemented.

If you want to prebuild and customise the SD card from macOS before first
boot, use [macos-imager-cli.md](macos-imager-cli.md).

If you are deploying on a newer board with integrated radios, the same flow
still applies, but the hardware validation expectations differ.

## Base System

- Install Raspberry Pi OS
- Ensure the Pi has network access
- Ensure Bluetooth is enabled
- Ensure the system clock and timezone are correct

Before assuming Wi-Fi or Bluetooth exists, validate the actual board model.
Not every Raspberry Pi has integrated radios. Follow
[hardware-audit.md](hardware-audit.md) first when bringing up a new or unknown
device.

Recommended checks:

```bash
uname -a
cat /proc/device-tree/model
bluetoothctl --version
timedatectl
```

Integrated Wi-Fi and Bluetooth are present on these commonly relevant boards:

- Raspberry Pi `3B`
- Raspberry Pi `3B+`
- Raspberry Pi `Zero W`
- Raspberry Pi `Zero 2 W`
- Raspberry Pi `4`
- Raspberry Pi `400`
- Raspberry Pi `5`

Important distinction for the Zero family:

- Raspberry Pi `Zero W` has integrated Wi-Fi and Bluetooth
- Raspberry Pi `Zero 2 W` has integrated Wi-Fi and Bluetooth
- plain Raspberry Pi `Zero` without the `W` does not

The currently used Raspberry Pi `Model B Rev 2` does not include onboard
Wi-Fi or Bluetooth, so USB radios are required on that host.

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
before proceeding. If the board model is an older non-wireless Pi, there may be
no Bluetooth controller to configure.

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

## Optional: Make `admin` Passwordless for `sudo`

If you want the `admin` user to run privileged provisioning commands without
being prompted for a password, create a dedicated sudoers drop-in instead of
editing `/etc/sudoers` directly:

```bash
printf 'admin ALL=(ALL) NOPASSWD:ALL\n' | sudo tee /etc/sudoers.d/10-admin-nopasswd >/dev/null && sudo chmod 440 /etc/sudoers.d/10-admin-nopasswd && sudo visudo -cf /etc/sudoers.d/10-admin-nopasswd
```

This still requires the current `sudo` password one last time when you run the
command, unless `admin` is already passwordless.

## Configure the Gateway

Use the example files in `python/config/` as the starting point:

- copy `python/config/config.toml.example` to
  `~/.config/bm-gateway/config.toml`
- copy `python/config/devices.toml` beside it if you want a separate working
  copy
- set `gateway.reader_mode = "live"` when you want to connect to real BM200
  hardware
- keep `gateway.poll_interval_seconds = 300` as the default baseline unless
  you have a specific reason to poll more aggressively
- replace MQTT and device values with real values

## Validate the Setup

```bash
bm-gateway config show
bm-gateway config validate
bm-gateway devices list --json
bm-gateway ha contract --json
bm-gateway run --once --dry-run --json
bm-gateway run --once --json
```

Expected outcomes:

- `config show` prints the resolved settings
- `config validate` reports a valid configuration
- `devices list --json` prints the configured devices
- `ha contract --json` prints the MQTT topics and entities expected by Home
  Assistant
- `run --once --dry-run --json` writes a local snapshot without contacting MQTT
- `run --once --json` polls enabled BM200 devices when `reader_mode = "live"`
- each run also writes `runtime/gateway.db` with persisted gateway and device
  rows

## Install the Service Assets

To install the runtime service unit on the Pi:

```bash
sudo ./rpi-setup/scripts/install-service.sh
```

This installs:

- `/etc/bm-gateway/config.toml`
- `/etc/bm-gateway/devices.toml`
- `/etc/systemd/system/bm-gateway.service`
- `/etc/systemd/system/bm-gateway-web.service`

Review the config, then start the service:

```bash
sudo systemctl start bm-gateway.service
sudo systemctl start bm-gateway-web.service
sudo systemctl status bm-gateway.service
sudo systemctl status bm-gateway-web.service
```

## Repository Areas

- `python/` contains the packaged CLI and future runtime code
- `home-assistant/` contains the MQTT/Home Assistant contract docs and assets
- `rpi-setup/ansible/` contains the first provisioning playbook
- `rpi-setup/systemd/` contains the service unit
- `rpi-setup/scripts/` contains install and update helpers
- `web/` contains the host-run management web plan and docs

## Next Step

Use the Ansible playbook when you want to stop managing the Pi by hand.

If you need to trim the machine into a smaller headless appliance after basic
bring-up, use [hardware-audit.md](hardware-audit.md) for service and module
review first.
