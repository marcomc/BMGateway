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

It also covers the current BM200/BM6-family and BM300 Pro/BM7-family live
polling paths.

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

The reproducible setup command is the bootstrap script in the next section.
It installs the system packages needed by the runtime, web UI, service helper,
and USB OTG helper path. If you are installing packages manually before running
individual lower-level scripts, install the same baseline:

```bash
sudo apt update
sudo apt install -y \
  bluetooth \
  bluez \
  ca-certificates \
  chromium \
  curl \
  dosfstools \
  git \
  kmod \
  libjpeg-dev \
  make \
  python3 \
  python3-dev \
  python3-venv \
  util-linux \
  zlib1g-dev
```

Package purpose:

| Package | Used for |
| --- | --- |
| `bluetooth`, `bluez` | Bluetooth service, `bluetoothctl`, and BLE polling |
| `ca-certificates`, `curl` | Downloading the `uv` installer over HTTPS |
| `git`, `make`, `python3`, `python3-venv` | Checkout and packaged Python runtime installation |
| `chromium` | USB OTG frame-image screenshots and Diagnostics frame previews |
| `dosfstools` | `mkfs.vfat` for USB OTG backing images |
| `kmod` | `modprobe libcomposite` for USB gadget setup |
| `libjpeg-dev`, `python3-dev`, `zlib1g-dev` | Native build headers for optional image dependencies |
| `util-linux` | `findmnt`, `mount`, and `umount` used by USB OTG helpers |

Optional integrations install their own extra packages when enabled:

| Option | Extra package |
| --- | --- |
| `--enable-glances` | `glances` |
| `--enable-cockpit` | `cockpit` |

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

By default, `BMGateway` assumes the Raspberry Pi hostname is `bmgateway`, so
the common Bonjour/mDNS address becomes:

- `bmgateway.local`

If you prefer a different `.local` hostname, set it before first deployment or
pass it during bootstrap with:

```bash
./scripts/bootstrap-install.sh --hostname garage-gateway
```

That updates the system hostname before the installer prints the final service
URLs, so the web UI and Cockpit addresses are emitted with
`garage-gateway.local` instead of `bmgateway.local`.

If you later publish the script at a reachable URL, the same bootstrap can be
run without a pre-existing checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/marcomc/BMGateway/main/scripts/bootstrap-install.sh | bash -s -- --repo-url https://github.com/marcomc/BMGateway.git
```

The bootstrap script intentionally installs the standalone runtime through
`make install`, not `make install-dev`.

Do not use `--skip-apt` for a fresh Raspberry Pi. That option is only for
controlled rebuilds where the packages listed in [System Packages](#system-packages)
are already installed by another provisioning layer.

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
- `--hostname <name>`
- `--enable-glances`
- `--enable-cockpit`
- `--skip-usb-otg-tools`
- `--skip-services`
- `--web-port <port>`
- `--glances-port <port>`

When `--disable-web` is used, the installer disables the web service and removes
the `/etc/sudoers.d/bm-gateway-web` web-action policy.

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

## Structured Audit Logs

The runtime keeps machine-readable audit logs under the state directory:

```text
/var/lib/bm-gateway/runtime/audit/YYYY-MM-DD.jsonl
```

These logs are newline-delimited JSON and are intended for diagnosing gateway
behavior over time, including automatic polling, per-device BLE poll outcomes,
archive sync activity, manual history sync requests, and key web-managed
configuration or device changes.

Retention is enforced automatically by the application: files older than
90 days are pruned as new audit events are written.

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
3. Enter the Pi host, for example `bmgateway.local` or your custom
   `<hostname>.local`.
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

If you changed the hostname during bootstrap, replace `bmgateway.local` with
your chosen `<hostname>.local`.

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
- `web.appearance = "system"`
- `web.language = "auto"`
- `usb_otg.enabled = false`
- `usb_otg.image_width_px = 480`
- `usb_otg.image_height_px = 234`
- `usb_otg.image_format = "jpeg"`
- `usb_otg.refresh_interval_seconds = 0`

The devices registry starts empty on purpose so the web UI can be the first
real configuration surface instead of shipping fake sample hardware.

The poll interval is editable in Settings. Values below `300` seconds are
allowed for testing, but the Settings page shows a red warning because frequent
BM6/BM200 polling can increase Bluetooth discovery failures, device contention,
and error-heavy history.

## Optional: Prepare USB OTG Image Export

`BMGateway` includes a disabled-by-default USB OTG image-export setting for
external monitors and digital picture frames.

This setting is intentionally split into three parts in the web UI:

- `Enable USB OTG image export` controls whether `BMGateway` should use the
  feature when the host is capable of it.
- `USB OTG support` reports whether the installer placed the OTG helper
  commands and `dosfstools` on the system.
- `USB OTG device controller` reports whether Linux currently exposes a USB
  gadget device controller under `/sys/class/udc`.
- `Prepare USB OTG Mode` or `Restore USB Host Mode` edits Raspberry Pi boot
  configuration and requires a reboot before taking effect.

If the installer was run with `--skip-usb-otg-tools`, the Settings page shows
USB OTG support as not installed and hides the prepare/export actions. Re-run
the bootstrap installer without that skip option, or run
`sudo rpi-setup/scripts/install-service.sh` from the checkout without
`--skip-usb-otg-tools`, to install:

- `chromium`
- `dosfstools`
- `kmod`
- `libjpeg-dev`, `python3-dev`, and `zlib1g-dev`
- `util-linux`
- `/usr/local/bin/bm-gateway-usb-otg-boot-mode`
- `/usr/local/bin/bm-gateway-usb-otg-frame-test`
- the scoped sudoers entries used by the web actions and runtime exporter

The web service keeps USB OTG privileges out of its ambient capability set.
Operations that must rewrite, mount, or attach the backing disk image run
through the scoped root helper installed by the service script.

Use `Prepare USB OTG Mode` when the Settings page reports no USB OTG device
controller and the Pi is connected through the Zero USB Plug or an OTG cable.
The action adds a BMGateway-managed `dwc2` peripheral-mode block under `[all]`
in:

```text
/boot/firmware/config.txt
```

The web UI shows only the action that matches the current boot-mode state:
prepare when USB OTG peripheral mode is not prepared, or restore when it is.
BMGateway intentionally treats USB OTG peripheral boot mode as an
application-owned setting. The restore action removes the managed block and any
`[all]` `dtoverlay=dwc2...dr_mode=peripheral` line, even if that line predated
BMGateway, so the host returns to USB host mode. Prepare still preserves
non-peripheral `dwc2` lines, and both actions create timestamped backups beside
the boot config before writing.

When USB OTG image export is enabled, the runtime screenshots the same hidden
frame-render pages used by Diagnostics and publishes those images after each
gateway polling cycle by default. Set
`usb_otg.refresh_interval_seconds` to a positive number to use a custom export
cadence. The Settings page warns if that export interval is shorter than the
gateway polling interval because the picture frame may see repeated stale data
and extra USB detach/reattach churn.

The generated image settings include:

- image width and height in pixels
- backing disk image size, from 1 through 4096 MB
- image format: JPEG, PNG, or BMP
- light or dark appearance
- overview devices per image, from 1 through 10
- whether to export battery overview pages, Fleet Trend, or both
- which Fleet Trend metric images to export: Voltage, SoC, Temperature, or any
  combination of them
- the Fleet Trend frame history range and configured devices included in those
  frame images

Saving USB OTG image-export settings starts background regeneration for the
configured frame images and redirects Settings without waiting for screenshots
and drive reattachment to finish when USB OTG image export is enabled.

In non-editing Settings mode, use `Export Frame Images` to regenerate the
configured images and expose a fresh drive immediately. Use
`Refresh USB OTG Drive` when the picture frame does not recognize the current drive
and you only want to detach and reattach the existing backing disk image.

The bootstrap installer installs USB OTG tools by default. If you are
installing on a host that will never use USB OTG image export, skip those
packages, helpers, and sudoers entries with:

```bash
./scripts/bootstrap-install.sh --skip-usb-otg-tools
```

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
