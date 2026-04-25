# BM300 Pro / BM7 Integration Notes

This note captures the protocol facts used to add live `BM300 Pro` support to
`BMGateway`.

The goal is to keep BM300 Pro support separate from the existing BM200/BM6
driver while preserving the same runtime features where the public protocol
information is sufficient.

## External Knowledge Already Available

Community work refers to the Ancel `BM300 Pro` as `BM7`.

Useful references:

- BM7 Python and ESPHome reference:
  [slydiman/bm7-battery-monitor](https://github.com/slydiman/bm7-battery-monitor)
- BM7 Home Assistant fork:
  [derekpurdy/BM7](https://github.com/derekpurdy/BM7)
- BM6 reverse engineering that established the shared request/response shape:
  [tarball.ca BM6 article](https://www.tarball.ca/posts/reverse-engineering-the-bm6-ble-battery-monitor/)
- BM6 and BM7 community discussion:
  [Home Assistant BM6 thread](https://community.home-assistant.io/t/bm6-battery-monitor-esphome/806239?page=2)

The public BM7 references show that BM300 Pro/BM7 uses:

- service UUID `0000fff0-0000-1000-8000-00805f9b34fb`
- write characteristic `0000fff3-0000-1000-8000-00805f9b34fb`
- notify characteristic `0000fff4-0000-1000-8000-00805f9b34fb`
- AES-CBC with a zero IV
- poll plaintext `d1550700000000000000000000000000`
- BM7 AES key bytes
  `[108, 101, 97, 103, 101, 110, 100, 255, 254, 48, 49, 48, 48, 48, 48, 64]`

That key is the critical difference from the BM6/BM200-family key already used
by `BMGateway`.

## Live Payload

The BM300 Pro/BM7 live notification plaintext uses the same `d15507` prefix as
the BM6 current-state response. The currently implemented offsets are:

| Byte | Meaning |
| --- | --- |
| `0..2` | Prefix `d1 55 07` |
| `3` | Temperature sign, where `01` means negative |
| `4` | Temperature magnitude in degrees Celsius |
| `5` | Device state code |
| `6` | State of charge percentage |
| `7..8` | Battery voltage in centivolts, big-endian |
| `9..10` | Rapid acceleration value, not persisted yet |
| `11..12` | Rapid deceleration value, not persisted yet |

The state codes documented by the BM7 Home Assistant fork are:

| Code | Gateway state |
| --- | --- |
| `0` | `normal` |
| `1` | `low` |
| `2` | `charging` |

## BMGateway Implementation

`BMGateway` now keeps BM300 Pro live polling in
`python/src/bm_gateway/drivers/bm300.py`.

The runtime dispatch is model-based:

- `bm200` uses the existing `bm200.py` driver
- `bm300pro` uses the new `bm300.py` driver
- any unknown device type remains unsupported

The BM200/BM6 driver was not changed to understand BM300 payloads. This keeps
the two protocol paths isolated even though they use the same BLE
characteristics and request plaintext.

Supported BM300 Pro live fields now match the fields currently persisted for
BM200/BM6-family live polling:

- voltage
- state of charge
- temperature
- RSSI when BlueZ/Bleak exposes it
- device-reported state

## BMGateway-Verified Findings

After deployment to the gateway, three configured `bm300pro` devices returned
live readings through the dedicated driver. The verified fields were voltage,
state of charge, temperature, RSSI-derived connectivity, and device state.

One configured identifier had been entered with Cyrillic lookalike characters
from phone/OCR input. `BMGateway` now normalizes the narrow set of Cyrillic
characters that commonly look like MAC-address hex characters before deciding
whether an input is a compact MAC address. This is an input-normalization
finding, not a BM300 protocol finding.

## Remaining Gaps

The public references contain enough information for live current-state polling
but not enough verified information for all original-app features.

Open BM300 Pro/BM7 work:

- onboard history download
- firmware version retrieval
- cranking, charging, and trip-history event records
- rapid acceleration and rapid deceleration persistence

No new private reverse-engineering discovery was made in this implementation.
The protocol code is based on public BM7 references and local adaptation into
the existing `BMGateway` runtime shape.
