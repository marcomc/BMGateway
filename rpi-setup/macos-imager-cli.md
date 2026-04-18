# Raspberry Pi Imager CLI on macOS

## Scope

This guide shows how to provision a Raspberry Pi 3B SD card from macOS using
the Raspberry Pi Imager command-line mode, then hand first-boot setup to
`BMGateway`.

It covers:

- flashing an image with Raspberry Pi Imager from Terminal on macOS
- injecting a first-boot script or cloud-init payload
- using the repo helper script at
  `rpi-setup/scripts/macos-imager-cli.sh`
- a `BMGateway` first-run payload example

## Source Basis

The command syntax in this guide is based on:

- Raspberry Pi’s installation documentation for Imager on macOS:
  [Getting started](https://www.raspberrypi.com/documentation/computers/getting-started.html)
- the upstream Raspberry Pi Imager repository:
  [raspberrypi/rpi-imager](https://github.com/raspberrypi/rpi-imager)
- the upstream CLI implementation in `src/cli.cpp`, which currently exposes:
  `--cli`, `--sha256`, `--cache-file`, `--first-run-script`,
  `--cloudinit-userdata`, `--cloudinit-networkconfig`, `--disable-verify`,
  `--disable-eject`, and `--enable-writing-system-drives`
- the Ubuntu `rpi-imager` man page for the core `--cli` behavior:
  [rpi-imager(1)](https://manpages.ubuntu.com/manpages/questing/en/man1/rpi-imager.1.html)

Two important caveats:

- Raspberry Pi’s public macOS documentation focuses on the GUI, not the CLI.
- The standard macOS app-bundle binary path used below is an inference from the
  installed app layout:
  `/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager`

## Prerequisites

- macOS with Terminal access
- Raspberry Pi Imager installed from
  [raspberrypi.com/software](https://www.raspberrypi.com/software/)
- an SD card reader
- a target SD card, identified with `diskutil list`
- this repository checked out locally

## Find the Imager Binary

Assuming the app is installed in `/Applications`, the CLI-capable binary is
typically:

```bash
/Applications/Raspberry\ Pi\ Imager.app/Contents/MacOS/rpi-imager
```

Check that the binary exists:

```bash
test -x "/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager"
```

## Identify the SD Card Device

Insert the target SD card and list block devices:

```bash
diskutil list
```

Pick the whole-device path for the SD card, for example:

```text
/dev/disk4
```

Do not use a partition path such as `/dev/disk4s1`.

## Choose the Image

You can pass either:

- a local `.img`, `.img.xz`, or `.img.zip` file
- an HTTP or HTTPS URL

For Raspberry Pi 3B, the pragmatic default is Raspberry Pi OS Lite 32-bit.

## Helper Script

This repository ships a wrapper for the macOS app-bundle CLI:

```bash
./rpi-setup/scripts/macos-imager-cli.sh --help
```

The wrapper validates common arguments and constructs the final `rpi-imager`
command for you.

## Fast Flash Only

To flash an image without extra customisation:

```bash
./rpi-setup/scripts/macos-imager-cli.sh \
  --image ~/Downloads/raspios-lite.img.xz \
  --device /dev/disk4 \
  --debug
```

## Flash with a First-Run Bootstrap Script

For Raspberry Pi OS based deployments, the most direct repo-backed automation
path is a first-run script:

```bash
./rpi-setup/scripts/macos-imager-cli.sh \
  --image ~/Downloads/raspios-lite.img.xz \
  --device /dev/disk4 \
  --first-run-script ./rpi-setup/examples/imager/bm-gateway-first-run.sh \
  --debug
```

The example first-run script:

- installs Bluetooth and repo prerequisites
- clones or updates `BMGateway` on the Pi
- runs `make install`
- installs example config if needed
- overlays `bm-gateway-config.toml` and `bm-gateway-devices.toml` from the boot
  partition when present
- installs and enables `bm-gateway.service`
- installs and enables `bm-gateway-web.service`

Before using that script in a real deployment, set:

- `BMGATEWAY_REPO_URL`
- optionally `BMGATEWAY_REPO_DIR`

The shipped default now points at:

- `https://github.com/marcomc/BMGateway.git`

You can still override that variable or maintain your own copy of the file for
deployment.

## Flash with Cloud-Init Payloads

The current upstream CLI source also supports cloud-init payload injection:

```bash
./rpi-setup/scripts/macos-imager-cli.sh \
  --image ~/Downloads/raspios-lite.img.xz \
  --device /dev/disk4 \
  --cloudinit-userdata ./user-data.yaml \
  --cloudinit-networkconfig ./network-config.yaml \
  --debug
```

This path is only appropriate when the selected image supports cloud-init.
That support is image-dependent.

## Using SHA-256 Verification

If you have an expected image hash, pass it explicitly:

```bash
./rpi-setup/scripts/macos-imager-cli.sh \
  --image ~/Downloads/raspios-lite.img.xz \
  --device /dev/disk4 \
  --sha256 <expected-hash>
```

If you need a cached artifact and a fixed hash together:

```bash
./rpi-setup/scripts/macos-imager-cli.sh \
  --image https://downloads.example.invalid/raspios-lite.img.xz \
  --device /dev/disk4 \
  --sha256 <expected-hash> \
  --cache-file ~/Library/Caches/bm-gateway/raspios-lite.img.xz
```

## Dry-Run the Command

To inspect the final invocation without writing media:

```bash
./rpi-setup/scripts/macos-imager-cli.sh \
  --image ~/Downloads/raspios-lite.img.xz \
  --device /dev/disk4 \
  --first-run-script ./rpi-setup/examples/imager/bm-gateway-first-run.sh \
  --dry-run
```

## After Flashing

Boot the Raspberry Pi 3B and then verify:

```bash
ssh <user>@<hostname-or-ip>
sudo systemctl status bm-gateway.service
sudo systemctl status bm-gateway-web.service
bm-gateway config validate
bm-gateway run --once --dry-run --json
```

If you do not want the first-run path, follow
`rpi-setup/manual-setup.md` after the OS boots.
