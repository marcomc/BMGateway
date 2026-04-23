# Home Assistant Integration

## Table of Contents

- [Purpose](#purpose)
- [Start Here](#start-here)
- [Included Assets](#included-assets)
- [CLI Support](#cli-support)

## Purpose

This directory contains the Home Assistant-facing assets and documentation for
`BMGateway`.

`BMGateway` uses Home Assistant's built-in MQTT integration. There is no
separate custom Home Assistant integration required for the normal setup path.

When describing this behavior for operators, prefer `Home Assistant MQTT
discovery` over `Home Assistant contract`. The latter is repository/developer
language for the MQTT topic and payload definition.

## Start Here

Use these documents in order:

1. [setup.md](setup.md)
2. [contract.md](contract.md)

The setup guide is the operator-facing source of truth for MQTT broker
placement, anonymous versus authenticated MQTT connections, retained discovery
versus retained state, and the default `homeassistant` discovery prefix.

## Included Assets

- [setup.md](setup.md) for end-user setup
- [contract.md](contract.md) for the MQTT topic/entity contract
- `packages/bm_gateway.yaml` for optional Home Assistant helpers
- `dashboards/bm_gateway.yaml` for a starter Lovelace dashboard
- `discovery/` for exported example discovery payloads

## CLI Support

The Python CLI mirrors the Home Assistant surface through:

- `bm-gateway ha contract`
- `bm-gateway ha discovery --output-dir home-assistant/discovery`

For the main project entry point, go back to the root
[README.md](../README.md).
