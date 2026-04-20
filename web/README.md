# Web Component

This directory documents the web product boundary for `BMGateway`.

## Current Role

- the shipped web executable is `bm-gateway-web`
- the implementation lives in `python/src/bm_gateway/web.py` and
  `python/src/bm_gateway/web_ui.py`
- the shared-core decision avoids a second Python codebase with duplicated
  config, runtime, and persistence logic

## Management Surface

The optional web process serves:

- `/` for the battery-first landing page
- `/management` and `/gateway` for operational and configuration actions
- `/history`, `/device`, `/devices`, and `/settings` for the main product flow

Primary launch command:

```bash
bm-gateway-web --config /etc/bm-gateway/config.toml --port 8080
```

Authoritative references:

- [Architecture plan](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- [Python component guide](../python/README.md)
- [Pi 3B web and OS research](../docs/research/2026-04-17-pi3b-web-and-os-research.md)
