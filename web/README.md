# Web Component

This directory owns the host-run web interface plan for `BMGateway`.

Current implementation:

- the actual web servers live in the Python CLI
- `bm-gateway web serve` renders a snapshot file
- `bm-gateway web manage` runs the management UI as a separate Python process
- the management UI now uses a BM300-inspired premium server-rendered design
  system rather than the earlier proof-of-work boxes and tables
- `/` is the battery-first landing page
- `/management` is the operational control-plane dashboard
- `/history`, `/device`, `/devices`, and `/settings` now form the main product
  journey
- the management UI exposes config editing, run-once control, retention-driven
  pruning, configured devices, Home Assistant contract views, storage summary,
  raw/daily/monthly history from SQLite, device analytics pages, yearly
  summaries, degradation comparison windows, chart-first history views, and a
  richer device detail page

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
