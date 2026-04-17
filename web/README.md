# Web Component

This directory owns the host-run web interface plan for `BMGateway`.

Current implementation:

- the actual web servers live in the Python CLI
- `bm-gateway web serve` renders a snapshot file
- `bm-gateway web manage` runs the management UI as a separate Python process
- the management UI exposes config editing, run-once control, retention-driven
  pruning, configured devices, Home Assistant contract views, storage summary,
  and raw/daily/monthly history from SQLite

Recommended Raspberry Pi 3B usage:

```bash
bm-gateway --config /etc/bm-gateway/config.toml web manage --port 8080
```

The active architecture recommendation is:

- collector/runtime process under `systemd`
- separate web-management process under `systemd`
- no Docker requirement on Raspberry Pi OS 32-bit

See:

- `docs/research/2026-04-17-pi3b-web-and-os-research.md`
