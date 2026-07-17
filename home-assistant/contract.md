# Home Assistant MQTT Contract

## Contents

- [Purpose](#purpose)
- [Discovery Strategy](#discovery-strategy)
- [Topic Layout](#topic-layout)
- [Gateway Entities](#gateway-entities)
- [Device Entities](#device-entities)
- [State Payload Shape](#state-payload-shape)
- [Notes](#notes)

## Purpose

This document defines the MQTT-facing contract that `BMGateway` exposes to
Home Assistant through the built-in MQTT integration and MQTT discovery.

For the end-user setup flow, use [setup.md](setup.md).

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

The gateway discovery payload exposes:

| Entity | Home Assistant type | Notes |
| --- | --- | --- |
| `version` | `sensor` | diagnostic |
| `uptime` | `sensor` | seconds, diagnostic |
| `active_adapter` | `sensor` | diagnostic |
| `running` | `binary_sensor` | connectivity |
| `mqtt_connected` | `binary_sensor` | connectivity |
| `devices_total` | `sensor` | diagnostic |
| `devices_online` | `sensor` | summary |

## Device Entities

Each battery monitor discovery payload exposes:

| Entity | Home Assistant type | Notes |
| --- | --- | --- |
| `voltage` | `sensor` | voltage, `V` |
| `soc` | `sensor` | battery percentage, `%` |
| `temperature` | `sensor` | temperature, `°C` |
| `connected` | `binary_sensor` | connectivity |
| `availability_reason` | `sensor` | diagnostic |
| `error_code` | `sensor` | diagnostic |
| `last_seen` | `sensor` | timestamp |
| `rssi` | `sensor` | signal strength, `dBm` |
| `state` | `sensor` | monitor-reported state |

## State Payload Shape

Gateway state topic:

```json
{
  "active_adapter": "hci0",
  "availability": "online",
  "devices_online": 1,
  "devices_total": 2,
  "generated_at": "2026-05-16T12:00:00+02:00",
  "mqtt_connected": true,
  "running": true,
  "uptime": 300,
  "version": "0.3.2"
}
```

Per-device state topic:

```json
{
  "adapter": "hci0",
  "availability": "online",
  "availability_reason": "ok",
  "connected": true,
  "driver": "bm200",
  "error_code": null,
  "error_detail": null,
  "last_seen": "2026-04-17T15:45:00+02:00",
  "rssi": -71,
  "soc": 81,
  "state": "normal",
  "temperature": 23.4,
  "voltage": 12.64
}
```

## Notes

- No custom Home Assistant integration is required for the normal setup path.
  The built-in MQTT integration is the intended integration surface.
- Disabled devices may still exist in the registry, but the runtime can choose
  whether to publish them.
- `bm-gateway run --publish-discovery` is the intended path for publishing
  retained discovery payloads in the current runtime slice.
- `home-assistant/packages/bm_gateway.yaml` is optional convenience glue on top
  of MQTT discovery, not a replacement for it.
- The runtime implementation should keep this document and the CLI contract
  output aligned.
