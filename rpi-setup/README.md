# Raspberry Pi Setup

This directory owns Raspberry Pi provisioning and operational guidance.

Current contents:

- [manual-setup.md](manual-setup.md) for the current manual Raspberry Pi
  gateway setup flow
- [macos-imager-cli.md](macos-imager-cli.md) for SD-card provisioning from
  macOS with Raspberry Pi Imager CLI
- [hardware-audit.md](hardware-audit.md) for hardware validation, boot tuning,
  and service/module trimming on a headless gateway
- `ansible/` for provisioning automation
- `examples/imager/` for first-boot payload examples
- `systemd/` for the runtime unit
- `scripts/` for install and update helpers
- `../scripts/bootstrap-install.sh` for one-line host bootstrap onto the Pi

macOS helpers now include:

- `rpi-setup/scripts/macos-imager-cli.sh` for wrapping Raspberry Pi Imager CLI
- `rpi-setup/examples/imager/bm-gateway-first-run.sh` as a first-boot example

The install helper now places:

- `~/.config/bm-gateway/config.toml`
- `~/.config/bm-gateway/devices.toml`
- `/etc/systemd/system/bm-gateway.service`
- `/etc/systemd/system/bm-gateway-web.service`
- `/usr/local/bin/bm-gateway`

The one-line bootstrap now installs the full appliance by default:

- standalone CLI runtime
- runtime service
- management web service
- live-ready config with an empty device registry

Stabilize the manual setup first, then translate it into Ansible.
