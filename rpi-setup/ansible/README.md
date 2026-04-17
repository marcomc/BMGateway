# Ansible Automation

This directory contains the first Ansible scaffold for Raspberry Pi
provisioning.

Current contents:

- `inventory.example.ini` as a starter inventory
- `playbook.yml` to install packages, config, the devices registry, and both
  systemd units

Run it from the repository root with:

```bash
ansible-playbook -i rpi-setup/ansible/inventory.example.ini rpi-setup/ansible/playbook.yml
```
