# Web Component

This directory owns the deployable web interface packaging for `BMGateway`.

Current implementation:

- the actual web server lives in the Python CLI as `bm-gateway web serve`
- `Dockerfile` wraps that server as a standalone container
- `compose.yaml` mounts the runtime snapshot directory read-only at `/data`

Local usage:

```bash
docker compose -f web/compose.yaml up --build
```

The container expects the runtime to keep writing
`/data/runtime/latest_snapshot.json`.
