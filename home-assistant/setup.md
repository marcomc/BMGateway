# Home Assistant Setup

## Overview

`BMGateway` integrates with Home Assistant through MQTT discovery.

In user-facing terms, this is best described as `Home Assistant MQTT
discovery`, not as a `contract`.

You do not need a custom Home Assistant integration for the normal setup path.
The required Home Assistant-side integration already exists: the built-in MQTT
integration.

Before following this file, use the project overview in
[../README.md](../README.md) if you still need the Raspberry Pi install path or
the broader documentation map.

Reference documents for this setup:

- [README.md](README.md)
- [contract.md](contract.md)

## Prerequisites

- A working Home Assistant installation
- An MQTT broker reachable by both Home Assistant and `BMGateway`
- `BMGateway` running on the Raspberry Pi with valid BLE access to the battery
  monitors

Common broker choices:

- Home Assistant Mosquitto add-on
- An external broker such as Mosquitto on another host

## How Auto-Discovery Works

Home Assistant does not detect `BMGateway` by scanning the LAN or by opening
the gateway web UI directly.

Home Assistant auto-discovers `BMGateway` only when all of these are true:

- Home Assistant has the built-in `MQTT` integration configured
- `BMGateway` can connect to the same MQTT broker
- `BMGateway` publishes Home Assistant MQTT discovery payloads to that broker
- Home Assistant is listening on the same discovery prefix, normally
  `homeassistant`

The practical message flow is:

```text
BMGateway -> MQTT broker -> Home Assistant
```

In configuration terms:

- `mqtt.enabled = true` means `BMGateway` will try to connect to an MQTT broker
  and publish MQTT messages
- `home_assistant.enabled = true` means `BMGateway` will publish the
  Home Assistant-specific MQTT discovery and topic layout on top of that MQTT
  connection

If MQTT is not connected, Home Assistant discovery cannot succeed even when the
Home Assistant integration flag is enabled.

## 1. Configure MQTT in Home Assistant

In Home Assistant:

1. Open `Settings -> Devices & Services`
2. Add or confirm the `MQTT` integration
3. Point it at the same broker host, port, and credentials used by
   `BMGateway`

If Home Assistant cannot connect to MQTT, discovery will never complete.

## 2. Configure BMGateway MQTT and Home Assistant settings

In the gateway config file:

```toml
[mqtt]
enabled = true
host = "mqtt.local"
port = 1883
username = "mqtt-user"
password = "CHANGE_ME"
base_topic = "bm_gateway"
discovery_prefix = "homeassistant"
retain_discovery = true
retain_state = false

[home_assistant]
enabled = true
status_topic = "homeassistant/status"
gateway_device_id = "bm_gateway"
```

The broker details must match the Home Assistant MQTT integration.

### MQTT authentication

`BMGateway` does not need a separate anonymous-broker flag.

Use these rules:

- for an authenticated broker, set both `mqtt.username` and `mqtt.password`
- for an anonymous broker, leave both `mqtt.username` and `mqtt.password`
  empty

At runtime, `BMGateway` only sends MQTT credentials when `mqtt.username` is
non-empty. If the username is empty, the gateway attempts an anonymous MQTT
connection and the password value is not used.

### Retained MQTT messages

`retain_discovery = true` is the recommended default. Home Assistant discovery
payloads describe which entities should exist, and retaining them lets Home
Assistant recreate the gateway and battery entities after Home Assistant or the
broker restarts.

`retain_state = false` is the recommended default. Battery readings are live
telemetry, and retaining state can make old values look current after gateway
downtime. Leave state retention disabled unless you explicitly want the broker
to keep the last published gateway and battery state for new subscribers.

### Discovery prefix

`discovery_prefix = "homeassistant"` is the Home Assistant MQTT discovery
default. Keep this value unless your Home Assistant MQTT integration has been
configured with a different discovery prefix.

Changing the prefix only on `BMGateway` will prevent Home Assistant
auto-discovery, because Home Assistant will keep listening under its configured
prefix.

## 3. Publish discovery payloads

You can either wait for the runtime to publish discovery on a normal cycle, or
force a one-shot publish:

```bash
bm-gateway run --once --publish-discovery
```

You can inspect the expected discovery topics locally:

```bash
bm-gateway ha contract --json
bm-gateway ha discovery --output-dir ./home-assistant/discovery
```

## 4. Confirm entities in Home Assistant

After discovery succeeds, Home Assistant should create:

- Gateway entities such as:
  - version
  - active adapter
  - running
  - MQTT connected
  - devices total
  - devices online
- Per-device entities such as:
  - voltage
  - state of charge
  - temperature
  - connected
  - last seen
  - RSSI
  - reported state
  - availability reason
  - error code

The discovery payloads now classify connectivity states correctly, so Home
Assistant will receive binary sensors for gateway/device connectivity and
sensors with proper units and device classes for battery data.

If no entities appear in Home Assistant, the first thing to verify is whether
`BMGateway` is actually connected to the MQTT broker. A gateway with Home
Assistant discovery enabled but `mqtt_connected = false` will not be visible to
Home Assistant.

## 5. Optional package and dashboard

This repository includes optional Home Assistant assets:

- `packages/bm_gateway.yaml`
- `dashboards/bm_gateway.yaml`

### Optional package install

If your Home Assistant configuration uses packages, copy:

```text
home-assistant/packages/bm_gateway.yaml
```

into your Home Assistant packages directory and include it from
`configuration.yaml` if needed.

### Optional dashboard import

Import or copy:

```text
home-assistant/dashboards/bm_gateway.yaml
```

into a Lovelace dashboard to get a starter overview.

## Troubleshooting

### No entities appear

Check:

- Home Assistant MQTT integration is connected
- `BMGateway` MQTT settings match the broker
- discovery topics are being published under the configured
  `mqtt.discovery_prefix`

### Entities exist but devices look offline

That usually means the MQTT path is working but live BLE polling is failing.
Check:

- the Raspberry Pi Bluetooth adapter is healthy
- the battery monitors are advertising
- the official mobile app is fully closed and not holding the monitor session

### Discovery payloads look wrong

Regenerate the reference files:

```bash
bm-gateway --config ./python/config/gateway.toml.example ha discovery \
  --output-dir ./home-assistant/discovery
```

### Home Assistant restarted and entities look stale

`retain_discovery = true` is the safest default. It lets Home Assistant rebuild
entities from retained discovery topics without waiting for a manual reinstall.

If telemetry values look stale after gateway downtime, keep
`retain_state = false`. State retention is intentionally separate from
discovery retention so Home Assistant can remember the entity definitions
without preserving old battery measurements as if they were fresh.
