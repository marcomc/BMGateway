# Raspberry Pi Setup

This directory owns Raspberry Pi provisioning and operational guidance.

Current contents:

- [manual-setup.md](manual-setup.md) for the first manual Raspberry Pi 3B setup
  flow
- [macos-imager-cli.md](macos-imager-cli.md) for SD-card provisioning from
  macOS with Raspberry Pi Imager CLI
- `ansible/` for provisioning automation
- `examples/imager/` for first-boot payload examples
- `systemd/` for the runtime unit
- `scripts/` for install and update helpers

macOS helpers now include:

- `rpi-setup/scripts/macos-imager-cli.sh` for wrapping Raspberry Pi Imager CLI
- `rpi-setup/examples/imager/bm-gateway-first-run.sh` as a first-boot example

The install helper now places:

- `/etc/bm-gateway/config.toml`
- `/etc/bm-gateway/devices.toml`
- `/etc/systemd/system/bm-gateway.service`
- `/etc/systemd/system/bm-gateway-web.service`

Stabilize the manual setup first, then translate it into Ansible.
