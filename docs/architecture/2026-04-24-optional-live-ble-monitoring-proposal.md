# Optional Live BLE Monitoring Proposal

## Table of Contents

- [Summary](#summary)
- [Observed Behavior](#observed-behavior)
- [Motivation](#motivation)
- [Target Behavior](#target-behavior)
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

## Design Considerations

### Connection Ownership

Live mode should be treated as an exclusive BLE session. The UI should warn
that the original app may not connect while BMGateway is holding the session.

### Runtime Isolation

The implementation should avoid disrupting the normal polling loop. A bounded
live session can run through a separate task, thread, or runtime command path
with clear cancellation behavior.

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
3. Add a web API or server-sent event endpoint for live readings without
   refreshing the whole page.
4. Add device detail controls to start and stop live mode with a visible
   warning about connection exclusivity.
5. Add automatic timeout and cancellation handling so live mode cannot be left
   running accidentally.
6. Decide and document persistence rules for live samples.
7. Add tests for session state transitions, timeout behavior, concurrent
   polling protection, and UI/API responses.
8. Validate on real hardware against the original mobile app to confirm
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
