# Optional Live BLE Monitoring Proposal

## Table of Contents

- [Summary](#summary)
- [Observed Behavior](#observed-behavior)
- [Motivation](#motivation)
- [Target Behavior](#target-behavior)
- [Current BLE Procedure](#current-ble-procedure)
- [Proposed Live Session Procedure](#proposed-live-session-procedure)
- [Design Considerations](#design-considerations)
- [Implementation Plan](#implementation-plan)
- [Risks And Tradeoffs](#risks-and-tradeoffs)
- [Open Questions](#open-questions)

## Summary

This proposal captures a future enhancement for optional live battery-monitor
streaming. The standard appliance behavior should remain periodic polling so
the Raspberry Pi does not monopolize the Bluetooth battery monitor. A separate
user-controlled live mode can keep a BLE connection open and update values at a
near-real-time cadence when an operator explicitly needs that view. Normal
unattended monitoring should continue to leave room for the original mobile app
to connect when live monitoring is not active.

## Observed Behavior

The original mobile application appears to keep an active connection to the
battery monitor while viewing a device. During that session, voltage,
temperature, and other live readings update roughly once per second or faster.
The same active connection likely explains why the original application can
lock out other clients while it is connected. The inverse is also important:
if `BMGateway` holds this live connection continuously, the phone app may be
unable to connect when the user wants to inspect a device manually.

`BMGateway` currently favors periodic collection. That is better for an
appliance that should monitor in the background without blocking the mobile app,
but it cannot show second-by-second changes during diagnostics or active
testing.

## Motivation

Live monitoring would be useful when:

- checking a charger or load response in real time
- watching voltage or temperature changes during a short diagnostic session
- comparing BMGateway readings with the original mobile application
- manually validating behavior before relying on slower periodic polling

It should remain optional because holding the BLE connection open may prevent
the original phone app or other tools from connecting.

## Target Behavior

The target model is:

- keep periodic polling as the default runtime mode
- add an explicit live monitoring action per device or per selected device
  group
- show live values in the web UI at a short cadence, likely around one second
- avoid enabling live mode automatically during normal Raspberry Pi background
  monitoring
- clearly show when live mode is active and which device connection is being
  held
- allow the user to stop live mode immediately
- automatically stop live mode after an idle timeout or maximum session length
- keep live mode disabled during normal unattended appliance operation unless
  explicitly enabled

## Current BLE Procedure

The existing one-shot live polling path already contains the protocol sequence
needed to attach to a monitor and read current data:

1. Resolve the configured MAC address with `BleakScanner.find_device_by_address`.
2. Connect with `BleakClient`.
3. Subscribe to notifications on
   `0000fff4-0000-1000-8000-00805f9b34fb`.
4. Write an encrypted live poll command to
   `0000fff3-0000-1000-8000-00805f9b34fb`.
5. Decode the first valid live notification.
6. Stop notifications and disconnect.

BM200/BM6-family devices use:

- key `leagend\xff\xfe0100009`
- plaintext command `d1550700000000000000000000000000`
- write without response in the current driver
- parser `parse_bm6_plaintext_measurement`

BM300 Pro/BM7-family devices use:

- key `leagend\xff\xfe010000@`
- plaintext command `d1550700000000000000000000000000`
- write with response in the current driver
- parser `parse_bm300_plaintext_measurement`

Relevant code paths:

- `python/src/bm_gateway/drivers/bm200.py`
- `python/src/bm_gateway/drivers/bm300.py`
- `python/src/bm_gateway/runtime.py`
- `python/src/bm_gateway/protocol_probe.py`

The current drivers arm notifications first, write the poll command, wait for a
valid `d15507` notification, and then disconnect. BM6-family devices do not
reliably stream passive notifications, so the live implementation should assume
it must keep sending the encrypted `d15507` poll command at the selected live
cadence while the BLE connection is held.

## Proposed Live Session Procedure

A web-controlled live session should reuse the same protocol but keep the
connection open:

1. User presses a per-device `Live` toggle in the web UI.
2. Web API starts a bounded live session for that device and marks the device
   as owned by the live-session manager.
3. The session scans for the configured MAC and opens a `BleakClient`
   connection.
4. The session subscribes once to `FFF4`.
5. The session writes encrypted `d15507` requests to `FFF3` at a bounded cadence,
   for example once per second.
6. Each valid `d15507` notification updates transient live-session state.
7. The device detail page receives updates through server-sent events,
   WebSocket, or short-poll JSON.
8. Normal scheduled polling skips that device while the live session owns the
   connection, or the live session publishes a compatible latest reading for
   the regular snapshot path.
9. User presses `Stop Live`, leaves the page, or the maximum session duration
   expires.
10. The session stops notifications, disconnects, clears ownership, and allows
    normal periodic polling and the original app to reconnect.

The UI should state that this mode intentionally holds the BLE connection and
may prevent the original Android or iPhone app from connecting until the live
session is stopped.

## Design Considerations

### Connection Ownership

Live mode should be treated as an exclusive BLE session. The UI should warn
that the original app may not connect while BMGateway is holding the session.
The first implementation should allow only one active live session per physical
device, and probably only one active session per Bluetooth adapter until
multi-device reliability is measured.

### Runtime Isolation

The implementation should avoid disrupting the normal polling loop. A bounded
live session can run through a separate task, thread, or runtime command path
with clear cancellation behavior.
It also needs an ownership guard so scheduled polling does not try to connect
to the same monitor while live mode is holding the BLE link.

### Data Persistence

Not every live sample needs to become long-term history. The implementation
should decide whether live samples:

- update only transient UI state
- also update the latest snapshot
- are downsampled before being stored in SQLite
- are excluded from historical rollups to avoid high-frequency storage churn

### UI Placement

The most natural place is the device detail page, with a visible live status
and a start/stop action. Diagnostics may also expose a read-only view of active
live sessions.

### MQTT Behavior

If live samples update MQTT state, the message rate must be bounded. A
separate setting may be needed so live UI updates can be faster than MQTT
publishing.

## Implementation Plan

1. Identify the BLE notification or read path used by the original app for
   high-frequency updates.
2. Add a bounded live-session service that can connect to one battery monitor,
   stream readings, and stop cleanly.
3. Reuse the current `d15507` request/notification path as the first
   implementation, because the app-like behavior can be approximated by
   keeping the connection open and polling at a short cadence.
4. Add a web API or server-sent event endpoint for live readings without
   refreshing the whole page.
5. Add device detail controls to start and stop live mode with a visible
   warning about connection exclusivity.
6. Add automatic timeout and cancellation handling so live mode cannot be left
   running accidentally.
7. Decide and document persistence rules for live samples.
8. Add tests for session state transitions, timeout behavior, concurrent
   polling protection, and UI/API responses.
9. Validate on real hardware against the original mobile app to confirm
   connection-locking behavior and update cadence.

## Risks And Tradeoffs

- Holding the BLE connection open may block the original app.
- Higher sample rates can increase CPU, BLE adapter, and storage pressure.
- Live mode may reduce reliability if it competes with scheduled polling.
- Persisting every live sample could create excessive database growth.
- The implementation may need model-specific behavior if BM6-family and
  BM200-family monitors expose live data differently.

## Open Questions

- Which BLE characteristic or notification path provides the original app's
  live update cadence?
- Should live mode support one device at a time, or multiple devices
  sequentially?
- Should live samples be stored, downsampled, or kept transient?
- What default maximum live-session duration is safe?
- Should MQTT publishing remain at the normal cadence even while the web UI
  displays faster live values?
