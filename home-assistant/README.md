# Home Assistant Component

This directory owns the Home Assistant facing contract for `BMGateway`.

Current contents:

- [contract.md](contract.md) for the MQTT topic and entity contract
- `packages/bm_gateway.yaml` for optional template helpers and startup logging
- `dashboards/bm_gateway.yaml` for a starter Lovelace dashboard
- `discovery/` for exported example MQTT discovery payloads

The Python CLI mirrors this contract through:

- `bm-gateway ha contract`
- `bm-gateway ha discovery --output-dir home-assistant/discovery`
