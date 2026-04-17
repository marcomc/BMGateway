# Home Assistant MQTT Contract

## Purpose

This document defines the MQTT-facing contract that `BMGateway` will expose to
Home Assistant.

The same contract is rendered by the Python CLI:

```bash
bm-gateway --config ./python/config/gateway.toml.example ha contract --json
```

Discovery payload examples can be exported with:

```bash
bm-gateway --config ./python/config/gateway.toml.example ha discovery \
  --output-dir ./home-assistant/discovery
```

## Discovery Strategy

- Use Home Assistant MQTT Device Discovery
- Publish one retained discovery payload per device
- Publish one JSON state topic for the gateway
- Publish one JSON state topic per battery monitor

## Topic Layout

Assuming:

- `mqtt.base_topic = "bm_gateway"`
- `mqtt.discovery_prefix = "homeassistant"`
- `home_assistant.gateway_device_id = "bm_gateway"`

The contract uses:

```text
bm_gateway/gateway/state
bm_gateway/devices/<device_id>/state
homeassistant/device/bm_gateway/config
homeassistant/device/<device_id>/config
```

## Gateway Entities

The gateway discovery payload should expose these entities:

- `version`
- `uptime`
- `active_adapter`
- `running`
- `mqtt_connected`
- `devices_total`
- `devices_online`

## Device Entities

Each battery monitor discovery payload should expose these entities:

- `voltage`
- `soc`
- `temperature`
- `connected`
- `last_seen`
- `rssi`
- `state`

## State Payload Shape

Gateway state topic:

```json
{
  "version": "0.1.0",
  "uptime": 1200,
  "active_adapter": "hci0",
  "running": true,
  "mqtt_connected": true,
  "devices_total": 2,
  "devices_online": 1
}
```

Per-device state topic:

```json
{
  "voltage": 12.64,
  "soc": 81,
  "temperature": 23.4,
  "connected": true,
  "last_seen": "2026-04-17T15:45:00+02:00",
  "rssi": -71,
  "state": "normal"
}
```

## Notes

- Disabled devices may still exist in the registry, but the runtime can choose
  whether to publish them.
- `bm-gateway run --publish-discovery` is the intended path for publishing
  retained discovery payloads in the current runtime slice.
- `home-assistant/packages/bm_gateway.yaml` is optional convenience glue on top
  of MQTT discovery, not a replacement for it.
- The runtime implementation should keep this document and the CLI contract
  output aligned.
