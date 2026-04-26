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
- BM6/BM7-compatible parser and driver work:
  [battery-hawk BM6 driver](https://github.com/UpDryTwist/battery-hawk)
- Android BM300 helper using the BM7 key:
  [xpcardata BM300 helper](https://github.com/stevelea/xpcardata)
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

- `bm200`, `bm6`, `bm900`, and `bm900pro` use the existing `bm200.py`
  driver family
- `bm300`, `bm300pro`, and `bm7` use the new `bm300.py` driver family
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

### Protocol Research Pass: 2026-04-25

The 2026-04-25 live probe kept the `bm-gateway` service stopped only while the
radio was under test, then restarted it. Both `bm-gateway` and
`bm-gateway-web` were active after the probe.

Configured `bm300pro` devices advertised as `BM300 Pro` and exposed the same
core GATT shape:

- service `0000fff0-0000-1000-8000-00805f9b34fb`
- write characteristic `0000fff3-0000-1000-8000-00805f9b34fb`
- notify characteristic `0000fff4-0000-1000-8000-00805f9b34fb`
- auxiliary readable characteristics `fff1` and `fff2`
- `fee0` / `fee1`, Generic Access, Generic Attribute, and Device Information
  services

The standard Device Information strings are not useful as real identity data on
the tested units. They returned placeholder text such as `Model Number`,
`Serial Number`, `Firmware Revision`, and `Software Revision`.

Two reachable BM300 Pro devices returned the same encrypted-version response
after writing plaintext command `d1550100000000000000000000000000` with the
BM7 key:

```text
d1550102021125000000000000000000
```

Treat that as a raw firmware or protocol-version payload for now. Public
projects know the command and prefix, but none of the reviewed sources provide
enough evidence to assign each byte a durable semantic name.

The same two devices returned live packets with state code `0` during this
probe:

```text
d155070010005c053300000000000000
d1550700120061053d00000000000000
```

Decoded values were consistent with existing parser offsets:

- `Libertv LD13CZT`: 13.31 V, 92%, 16°C, status code `0`
- `DOC FB12899`: 13.41 V, 97%, 18°C, status code `0`

`Punto FA376HT` advertised as `BM300 Pro` but the direct GATT probe timed out
at very low RSSI during this pass. A read-only probe did later connect long
enough to confirm the same `fff1 = 01` and `fff2 = 02` values.

Read-only custom characteristics on BM300 Pro showed:

| Characteristic | Observed value | Current interpretation |
| --- | --- | --- |
| `fff1` | `01` | Unknown |
| `fff2` | `02` | Unknown |
| `fff5` | timeout | Unknown |
| `fee1` | timeout on tested units | Unknown |

Do not expose `fff1` or `fff2` as features until a source or controlled test
explains them.

The BM2 history-count command `e701` was also tested against a reachable
BM300 Pro unit with both the BM7 family key and the older BM2 key. Neither
variant produced a history-count response or any other notification during the
test window. This is negative evidence only; it says that the direct BM2
history-count request is not a BM300 Pro history entrypoint.

Additional `e7xx` variants tested on a reachable BM300 Pro were also silent:

- `e700`
- `e701`
- `e70100`
- `e702`
- `e7ff`

The same `d15500..d1550f` zero-payload command sweep used for BM6 was also run
against BM300 Pro. The BM300 Pro unit produced ordinary echoes or live packets
for several command IDs, but `d15505` was again the only unmapped command that
returned a historical marker-shaped response:

```text
d1550500000000000000000000000000
fffefe00000000000000000000000000
```

That is consistent with the BM6-family `d15505` result. A later BM7 probe on
`doc_fb12899` also returned 30 historical-looking 4-byte chunks for byte-6 or
byte-7 `d15505` selectors. Those chunks are raw evidence only: order, cadence,
and field layout have not been validated for BM7.

Treat BM7 history as unresolved. Do not import BM300 Pro/BM7 history until a
BM7-specific validation test proves the record layout.

### External Research Status

The reviewed BM300 Pro / BM7 projects converge on live current-state polling
and the `d15501` version command. None of the reviewed BM300 Pro / BM7 projects
implements onboard history download.

Community discussion also confirms that Ancel `BM300 Pro` devices are often
seen separately from Ancel `BM200` devices even when integrations share a BM6
lineage. That matches the project decision to keep `bm300pro` on a separate
driver path using the BM7 key.

## Remaining Gaps

The public references contain enough information for live current-state polling
but not enough verified information for all original-app features.

Open BM300 Pro/BM7 work:

- onboard history download
- semantic parsing of the raw `d15501` firmware or protocol-version response
- cranking, charging, and trip-history event records
- rapid acceleration and rapid deceleration persistence
- validation of the observed `d15505` 4-byte chunks: order, cadence, field
  layout, and relationship to live voltage, SoC, and temperature

The 2026-04-25 probe added one project-local discovery: tested BM300 Pro units
return raw `d15501` payload `d1550102021125000000000000000000`. The payload is
documented here as raw evidence only.
