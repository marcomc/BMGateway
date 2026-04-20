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
- `/settings` for the unified settings surface, with `?edit=1` enabling edit
  mode
- `/history`, `/device`, `/devices`, and `/devices/new` for the main product
  flow
- `/management` and `/gateway` as compatibility aliases that currently open the
  editable settings mode

Primary launch command:

```bash
bm-gateway-web --config /etc/bm-gateway/config.toml --port 8080
```

Authoritative references:

- [Architecture plan](../docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
- [Python component guide](../python/README.md)
- [Pi 3B web and OS research](../docs/research/2026-04-17-pi3b-web-and-os-research.md)
