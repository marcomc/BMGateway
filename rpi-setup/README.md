# Raspberry Pi Setup

This directory owns Raspberry Pi provisioning and operational guidance.

Current contents:

- [manual-setup.md](manual-setup.md) for the first manual Raspberry Pi 3B setup
  flow
- `ansible/` for provisioning automation
- `systemd/` for the runtime unit
- `scripts/` for install and update helpers

The install helper now places:

- `/etc/bm-gateway/config.toml`
- `/etc/bm-gateway/devices.toml`
- `/etc/systemd/system/bm-gateway.service`
- `/etc/systemd/system/bm-gateway-web.service`

Stabilize the manual setup first, then translate it into Ansible.
