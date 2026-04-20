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

## One-Liner Bootstrap

For routine host installation, the supported bootstrap path is the repository
script that performs apt setup, `uv` installation, clone-or-update, and
full appliance installation in one step:

```bash
./scripts/bootstrap-install.sh
```

That is the recommended command once the repository is already present on the
target machine.

If you later publish the script at a reachable URL, the same bootstrap can be
run without a pre-existing checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/marcomc/BMGateway/main/scripts/bootstrap-install.sh | bash -s -- --repo-url https://github.com/marcomc/BMGateway.git
```

The bootstrap script intentionally installs the standalone runtime through
`make install`, not `make install-dev`.

By default it also:

- installs and starts `bm-gateway.service`
- installs and starts `bm-gateway-web.service`
- keeps the web UI on `0.0.0.0:80`
- prints the working management URLs at the end of the run
- can optionally install and start `glances-web.service` for the Home
  Assistant Glances integration

Useful options:

- `--disable-web`
- `--disable-home-assistant`
- `--enable-glances`
- `--enable-cockpit`
- `--skip-services`
- `--web-port <port>`
- `--glances-port <port>`

## Install `uv`

Install `uv` with the official bootstrap command:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the shell or source the updated profile so `uv` is on `PATH`.

## Clone the Repository

```bash
git clone https://github.com/marcomc/BMGateway.git
cd BMGateway
```

## Install the Executables

```bash
make install
```

This creates:

- a standalone runtime under `~/.local/share/bm-gateway/venv`
- a user-facing command at `~/.local/bin/bm-gateway`
- a user-facing web command at `~/.local/bin/bm-gateway-web`
- a config template at `~/.config/bm-gateway/config.toml` if missing
- a devices registry at `~/.config/bm-gateway/devices.toml` if missing

## Optional: Install Glances for Home Assistant

Home Assistant's Glances integration requires a running `glances` instance in
web-server mode. The Debian package installs a stock `glances.service`, but it
uses `glances -s -B 127.0.0.1`, which is not the REST API that Home Assistant
expects.

Install and verify the included `glances-web.service` instead:

```bash
sudo apt-get update
sudo apt-get install -y glances
sudo install -m 0644 rpi-setup/systemd/glances-web.service /etc/systemd/system/glances-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now glances-web.service
curl -fsS http://127.0.0.1:61208/api/4/status
```

Expected response:

```json
{"version":"4.3.1"}
```

Then, in Home Assistant:

1. Open `Settings > Devices & services`.
2. Add the `Glances` integration.
3. Enter the Pi host, for example `bmgateway.local`.
4. Enter port `61208`.

If you prefer the automated path, the bootstrap and service installers support
the same flow with:

```bash
./scripts/bootstrap-install.sh --enable-glances
```

or, on an already installed host:

```bash
sudo ./rpi-setup/scripts/install-service.sh --enable-glances
```

## Optional: Install Cockpit

Cockpit is useful as a separate host-administration console for package,
service, storage, and network inspection on the Pi. It does not replace the
`BMGateway` web UI; it complements it on a different port.

On this Raspberry Pi OS `trixie` host, Cockpit is available directly from the
base repository, so no extra backports setup was needed.

Install and verify it:

```bash
sudo apt-get update
sudo apt-get install -y cockpit
sudo systemctl enable --now cockpit.socket
curl -k -I https://127.0.0.1:9090/
```

Open:

- [https://bmgateway.local:9090/](https://bmgateway.local:9090/)

Cockpit login uses a local system account and password. SSH keys alone are not
enough for the web login flow.

If you prefer the automated path, the bootstrap and service installers support
the same flow with:

```bash
./scripts/bootstrap-install.sh --enable-cockpit
```

or:

```bash
sudo ./rpi-setup/scripts/install-service.sh --enable-cockpit
```

## Optional: Make `admin` Passwordless for `sudo`

If you want the `admin` user to run privileged provisioning commands without
being prompted for a password, create a dedicated sudoers drop-in instead of
editing `/etc/sudoers` directly:

```bash
printf 'admin ALL=(ALL) NOPASSWD:ALL\n' | sudo tee /etc/sudoers.d/10-admin-nopasswd >/dev/null && sudo chmod 440 /etc/sudoers.d/10-admin-nopasswd && sudo visudo -cf /etc/sudoers.d/10-admin-nopasswd
```

This still requires the current `sudo` password one last time when you run the
command, unless `admin` is already passwordless.

## Radio Bring-Up on the Current Host

The current gateway host uses USB radios, not onboard ones:

- Wi-Fi: `Ralink RT5370`
- Bluetooth: `Cambridge Silicon Radio`

After attaching those dongles, verify:

```bash
lsusb
ip -br link
sudo iw dev
sudo rfkill list
sudo bluetoothctl list
sudo hciconfig -a
sudo nmcli device status
sudo ip route
```

If the Bluetooth dongle appears but is blocked or down, run:

```bash
sudo rfkill unblock bluetooth
sudo sh -c 'for f in /var/lib/systemd/rfkill/*bluetooth; do printf 0 > "$f"; done'
sudo systemctl restart bluetooth.service
sudo hciconfig hci0 up
sudo bluetoothctl power on
sudo rfkill list
sudo hciconfig -a
sudo bluetoothctl show
```

The intended steady state is:

- `eth0` connected and preferred as the default route
- `wlan0` connected as fallback with a higher route metric
- `hci0` present, unblocked, and powered on

For BM200 support, powered on is not enough. The Bluetooth adapter must also
support BLE central mode. The currently audited CSR USB dongle identified as
`0a12:0001` exposes BR/EDR only and does not provide the BLE central role
required by `bleak`, so it cannot monitor BM200 devices.

## Configure the Gateway

The appliance bootstrap now writes a live-ready config to:

- `~/.config/bm-gateway/config.toml`
- `~/.config/bm-gateway/devices.toml`

The default post-install workflow is:

1. Open the management UI
2. Add your Bluetooth devices there
3. Update MQTT settings there when you are ready to publish to Home Assistant

The installed config keeps:

- `gateway.reader_mode = "live"`
- `gateway.poll_interval_seconds = 300`
- `web.host = "0.0.0.0"`
- `web.port = 80`
- `web.show_chart_markers = false`

The devices registry starts empty on purpose so the web UI can be the first
real configuration surface instead of shipping fake sample hardware.

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

To install or refresh the runtime and web services on the Pi:

```bash
sudo ./rpi-setup/scripts/install-service.sh
```

For repeat repository-driven development deploys from your workstation to an
already bootstrapped host, use:

```bash
make dev-deploy TARGET=admin@host
```

That path syncs the current checkout to the remote host, runs `make install`,
and then refreshes the `systemd` services in place.

This installs:

- `/home/<user>/.config/bm-gateway/config.toml`
- `/home/<user>/.config/bm-gateway/devices.toml`
- `/etc/systemd/system/bm-gateway.service`
- `/etc/systemd/system/bm-gateway-web.service`
- `/etc/systemd/system/glances-web.service` when `--enable-glances` is used
- `cockpit.socket` when `--enable-cockpit` is used
- `/usr/local/bin/bm-gateway` as a stable systemd-facing symlink

Review the config, then check the service state:

```bash
sudo systemctl status bm-gateway.service
sudo systemctl status bm-gateway-web.service
sudo systemctl status glances-web.service
sudo systemctl status cockpit.socket
```

## Service and Module Policy for This Project

Keep enabled:

- `bluetooth.service`
- `wpa_supplicant.service`
- `NetworkManager.service`
- `avahi-daemon.service`
- `getty@tty1.service`

Disable:

- `udisks2.service`
- `serial-getty@ttyAMA0.service`

Disable after provisioning is complete:

- `cloud-init-local.service`
- `cloud-init-main.service`
- `cloud-init-network.service`
- `cloud-config.service`
- `cloud-final.service`

Keep HDMI console support:

- do not disable `vc4`, `drm`, `drm_kms_helper`, or `drm_display_helper`

Blacklist only:

- `snd_bcm2835`
- `snd_soc_hdmi_codec`
- `bcm2835_codec`
- `bcm2835_v4l2`
- `bcm2835_isp`
- `bcm2835_mmal_vchiq`

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
