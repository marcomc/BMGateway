# Home Assistant Integration

## Table of Contents

- [Overview](#overview)
- [Setup](#setup)
- [Repository Assets](#repository-assets)
- [CLI Support](#cli-support)

## Overview

This directory owns the Home Assistant-facing setup for `BMGateway`.

`BMGateway` uses Home Assistant's built-in MQTT integration and MQTT discovery.
There is no separate custom integration to install for the normal setup path.

## Setup

Use the canonical setup guide:

- [setup.md](setup.md)

## Repository Assets

Current contents:

- [contract.md](contract.md) for the MQTT topic and entity contract
- [setup.md](setup.md) for the end-user setup flow
- `packages/bm_gateway.yaml` for optional template helpers and startup logging
- `dashboards/bm_gateway.yaml` for a starter Lovelace dashboard
- `discovery/` for exported example MQTT discovery payloads

## CLI Support

The Python CLI mirrors this contract through:

- `bm-gateway ha contract`
- `bm-gateway ha discovery --output-dir home-assistant/discovery`
