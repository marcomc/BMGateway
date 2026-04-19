# BM6 / BM200 Integration Notes

This note captures what `BMGateway` verified during live integration of an
Ancell `BM200`-labelled device that behaves as a `BM6`-family monitor on the
wire.

The goal is to separate:

- knowledge that already existed in upstream/community references
- findings verified directly in `BMGateway`
- open questions that still need more protocol capture or hardware access

## External Knowledge Already Available

The following behavior was already described by community or reverse
engineering work outside this repository:

- BM6-family devices use encrypted traffic over `FFF3` / `FFF4`
- BM6 current-state reads are request/response rather than passive streaming
- BlueZ / Bleak on Raspberry Pi can be sensitive to scan/connect sequencing
- Raspberry Pi onboard Wi-Fi and Bluetooth can interfere with BLE reliability

Useful references:

- BM6 reverse engineering:
  [tarball.ca BM6 article](https://www.tarball.ca/posts/reverse-engineering-the-bm6-ble-battery-monitor/)
- Bleak scan/connect discussion:
  [Bleak discussion #933](https://github.com/hbldh/bleak/discussions/933)
- Bleak troubleshooting:
  [Bleak troubleshooting docs](https://bleak.readthedocs.io/en/stable/troubleshooting.html)
- BM6 ESPHome/Home Assistant thread:
  [Home Assistant BM6 thread](https://community.home-assistant.io/t/bm6-battery-monitor-esphome/806239)
- BM2/BM6 broadcasting discussion:
  [OpenMQTTGateway BM2 thread](https://community.openmqttgateway.com/t/omg-1-8-0-no-longer-gets-bm2-messages/3578)

## BMGateway-Verified Findings

These findings were verified directly on the live `BMGateway` hardware and are
the project-specific part worth preserving.

### 1. Some `BM200`-branded hardware behaves like `BM6`

The device configured as:

- MAC: `3C:AB:72:82:86:EA`
- name seen by the adapter: `BM6`

did not behave like the older passive BM2/BM200 assumptions.

Verified result:

- the device advertises as `BM6`
- direct service access exposes `FFF0` / `FFF3` / `FFF4`
- successful current-state reads require:
  1. scan first
  2. connect
  3. start notify on `FFF4`
  4. write the encrypted poll request to `FFF3`
  5. wait for the notification

### 2. `scan_timeout_seconds` materially affects real success rate

`BMGateway` originally configured:

- `scan_timeout_seconds = 8`
- `connect_timeout_seconds = 20`

but the live driver was not actually using the configured scan timeout.

Verified result:

- short visibility windows were enough to miss the device entirely
- wiring the configured scan timeout into the driver was necessary
- more conservative defaults are safer for BM6-family devices:
  - `scan_timeout_seconds = 15`
  - `connect_timeout_seconds = 45`

### 3. Failure classification needs to preserve the actual BLE error

When the device was not visible, earlier runtime rows often collapsed into
low-signal `timeout` or blank `unexpected_error` outcomes.

Verified result:

- preserving the last BLE-layer exception produces more useful history rows
- the most useful real failure string so far has been:
  - `Device with address 3C:AB:72:82:86:EA was not found.`

That distinction matters because it separates:

- device not advertising / not visible
- protocol timeout after a successful connection
- generic driver or runtime faults

### 4. The Pi adapter can be healthy while the BM6 is absent

The Raspberry Pi Zero 2 W adapter continued to see many other BLE devices even
while the BM6 failed.

Verified result:

- the adapter was powered and healthy
- other BLE devices appeared during `bluetoothctl scan on`
- the BM6 sometimes did not appear at all in the same scan window

That means at least some failures are genuinely on the monitor visibility side,
not only on the host stack side.

### 5. A bounded Bluetooth recovery path is worth having

`BMGateway` now includes:

- a bounded automatic retry after `not found` / `timeout`
- a management action to trigger adapter recovery manually

Current recovery behavior:

1. `bluetoothctl scan off`
2. `bluetoothctl power off`
3. `bluetoothctl power on`
4. retry the poll once

This is a recovery aid, not a substitute for a visible device.

### 6. Error-heavy days can poison rollups if they are averaged naively

During live integration, the device history initially looked far worse than the
actual valid readings because daily rollups were including error snapshots as
if they were real `0 V / 0%` measurements.

Verified result:

- raw history tables should continue to preserve error rows
- charts should only plot valid measurements
- daily rollups need to count errors separately from valid-sample averages
- an explicit rollup rebuild is useful after changing the persistence logic so
  existing SQLite history becomes trustworthy again

## Open Questions

These are still not fully verified.

### Device history memory on BM6-family hardware

`BMGateway` already contains partial BM2-style history helpers:

- `encode_history_count_request`
- `encode_history_download_request`
- `decode_history_count_packet`
- `parse_history_items`

Open question:

- does the BM6-family device use the same history request/response protocol as
  older BM2/BM200 references, or a different one used only by the official
  app?

This needs a BLE capture while the official app downloads history.

### Why the monitor disappears from advertising

We still do not know which of these is dominant:

- monitor-side sleep policy
- app/device wake-up behavior
- connection ownership contention with the official app or another client
- Raspberry Pi radio coexistence effects

## Practical Guidance For Future Work

When debugging BM6-family devices in `BMGateway`:

1. Check plain visibility first with a raw scan before changing protocol code.
2. Distinguish `not found` from `timeout after connect`.
3. Avoid assuming a `BM200` label means legacy BM2 passive behavior.
4. Prefer scan-first, bounded retries, and explicit request/response polling.
5. Capture official-app traffic before implementing history download.
