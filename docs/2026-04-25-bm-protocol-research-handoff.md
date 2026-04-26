# BM Protocol Research Handoff

This document is the compact handoff for the ANCEL BM200/BM6 and
BM300 Pro/BM7 BLE protocol work. It keeps only verified findings, known-safe
commands, and unresolved gaps.

## Scope And Safety

The work covers local, authorized communication with owned monitors only:

- BM200-labelled devices that behave as BM6-family monitors on BLE
- BM300 Pro devices that behave as BM7-family monitors on BLE

Do not brute force AES keys, try random command IDs, bypass access controls, or
probe third-party devices. Direct BLE probes should stay bounded and read-like.

## Code Paths

| Area | Files |
| --- | --- |
| BM200/BM6 driver | `python/src/bm_gateway/drivers/bm200.py` |
| BM300 Pro/BM7 driver | `python/src/bm_gateway/drivers/bm300.py` |
| Bounded protocol probe CLI | `python/src/bm_gateway/protocol_probe.py` |
| Probe-tool documentation | `docs/protocol-probe-tools.md` |

Runtime driver routing:

- `bm200`, `bm6`, `bm900`, and `bm900pro` use the BM200/BM6 driver family.
- `bm300`, `bm300pro`, and `bm7` use the BM300 Pro/BM7 driver family.

## Shared BLE Shape

Both tested families use:

- service `0000fff0-0000-1000-8000-00805f9b34fb`
- write characteristic `0000fff3-0000-1000-8000-00805f9b34fb`
- notify characteristic `0000fff4-0000-1000-8000-00805f9b34fb`
- AES-CBC with a zero IV

Known keys:

| Family | Key bytes |
| --- | --- |
| BM2 / older BM200 | `leagend\xff\xfe1882466` |
| BM6 / BM200-labelled request-response devices | `leagend\xff\xfe0100009` |
| BM300 Pro / BM7 | `leagend\xff\xfe010000@` |

## Verified Live Command: `d15507`

Plaintext command:

```text
d1550700000000000000000000000000
```

Response shape:

| Byte | Meaning |
| --- | --- |
| `0..2` | Prefix `d1 55 07` |
| `3` | Temperature sign; `01` means negative |
| `4` | Temperature magnitude in degrees Celsius |
| `5` | Device state code |
| `6` | State of charge percentage |
| `7..8` | Battery voltage in centivolts, big-endian |
| `9..10` | Rapid acceleration value |
| `11..12` | Rapid deceleration value |

BM6/BM200 and BM7/BM300 Pro live status mapping:

| Code | State |
| --- | --- |
| `0` | `normal` |
| `1` | `low` |
| `2` | `charging` |

`charging` is the monitor-reported state. It is not proof that a charger is
physically connected; a high-voltage fully charged battery can also be reported
as charging.

## Raw Version Command: `d15501`

Plaintext command:

```text
d1550100000000000000000000000000
```

Observed payloads:

| Family | Payload |
| --- | --- |
| BM6/BM200 | `d1550101080005000000000000000000` |
| BM7/BM300 Pro | `d1550102021125000000000000000000` |
| BM7/BM300 Pro | `d1550102020000000000000000000000` |

Byte-level semantics are still unknown. Keep these values as raw version or
protocol payload evidence only.

## BM200/BM6 Onboard History

### Request

The verified BM200/BM6 history selector is:

```text
d1550500000000010000000000000000
```

In the probe tool this is named `hist_d15505_b7_01`.

### Response Size

On `spare_nlp20`, a full page returned:

```text
d1550501000000000000000000000000
...
fffefe00040900000000000000000000
```

The final marker length matches one 256-record page:

- `0x409 = 1033` total framed response bytes
- `1033 - 9 = 1024` payload bytes
- `1024 / 4 = 256` records

At 2 minutes per record, one page covers about 8 hours 32 minutes.

### Record Layout

Each historical sample is 4 bytes:

```text
vvv ss tt p
```

| Field | Meaning | Status |
| --- | --- | --- |
| `vvv` | Battery voltage in centivolts, hex | Verified |
| `ss` | State of charge percentage, hex byte | Verified |
| `tt` | Temperature in degrees Celsius, hex byte | Verified |
| `p` | Event or record-type nibble | Unresolved |

Example:

```text
52b53170
```

Decodes as:

| Field | Value |
| --- | --- |
| `vvv` | `0x52b / 100 = 13.23 V` |
| `ss` | `0x53 = 83%` |
| `tt` | `0x17 = 23 C` |
| `p` | `0` |

### Order And Cadence

The page is newest-first. Each next record is about 2 minutes older.

Four captures from `spare_nlp20` proved the shift behavior:

| Pair | Interval | Best offset | Matching records | Mismatches |
| --- | --- | --- | --- | --- |
| `t00 -> t20` | `1236 s` | `10` | `246` | `0` |
| `t20 -> t40` | `1245 s` | `11` | `245` | `0` |
| `t40 -> t60` | `1246 s` | `10` | `246` | `0` |
| `t00 -> t60` | `3727 s` | `31` | `225` | `0` |

The cumulative `t00 -> t60` offset of 31 records over `3727 s` matches
`3727 / 120 = 31.06` two-minute samples.

### SoC And Temperature Validation

The lower-SoC validation capture is:

```text
/tmp/bm200-soc-ss-check-20260426-192523.jsonl
```

Live `d15507` packets during that probe:

| Device | Live voltage | Live SoC | Live temperature | Live status |
| --- | --- | --- | --- | --- |
| `spare_nlp20` | `13.22-13.23 V` | `82%` | `23-24 C` | `0` / `normal` |
| `spare_nlp5` | `13.29-13.30 V` | `88%` | `20 C` | `0` / `normal` |

Historical `ss` values in the same probe:

| Device | Newest historical `ss` values | Distribution |
| --- | --- | --- |
| `spare_nlp20` | `83, 84, 85, 86, 88, 90, 91, 93, 94, 96, 98, 99` | recent `83..99`, older `100` |
| `spare_nlp5` | `88, 88, 88, 88, 88, 88, 88, 88, 88, 88, 88, 88` | `88`, `89`, `90` |

The one-point gap between live `82%` and newest historical `83%` on
`spare_nlp20` is consistent with live data being newer than the latest
2-minute historical sample.

### Unresolved BM200/BM6 History Items

- Meaning of `p`. Observed values include `0`, `2`, and `4`. It is not the live
  status code, because monitors reporting live `charging` still usually had
  `p=0` in history.
- Paging or range selection for the full advertised 30-day history. The known
  selector returns one 256-record page.
- Cranking, charging-test, or waveform event records. These may use `p`,
  another `d15505` selector, or another command family.

## BM300 Pro/BM7 Status

Live `d15507` polling is implemented and verified for BM300 Pro/BM7 with the
BM7 key. It uses the same live response offsets as BM6/BM200.

BM300 Pro/BM7 onboard history is not decoded.

Known facts:

- The BM2 `e7xx` history-count variants tested on BM7 produced no notification.
- Zero-payload `d15505` can return marker-shaped responses.
- `doc_fb12899` returned 30 historical-looking 4-byte chunks for byte-6 or
  byte-7 `d15505` selectors during one probe.
- Those BM7 chunks have not been validated for order, cadence, or field layout.

Do not import BM300 Pro/BM7 history until a BM7-specific validation test proves
the record layout.

## Dead Ends

The older BM2 `e7xx` history-count path did not work on tested BM6/BM200 or
BM7/BM300 Pro devices.

Tested variants included:

- `e700`
- `e701`
- `e70100`
- `e7010000`
- `e701000000`
- `e702`
- `e703`
- `e704`
- `e705`
- `e7ff`

These were tried with relevant BM6/BM7/BM2 keys where applicable. No usable
history-count notification was observed.

## Device Notes

Configured live gateway devices:

| Device | Type | MAC | Note |
| --- | --- | --- | --- |
| `spare_nlp5` | `bm200` | `3C:AB:72:82:86:EA` | BM6-family, sometimes harder to find |
| `spare_nlp20` | `bm200` | `3C:AB:72:EB:68:C9` | Reliable BM6-family responder |
| `libertv_ld13czt` | `bm300pro` | `E0:4E:7A:AF:9B:E8` | BM7-family, intermittent |
| `doc_fb12899` | `bm300pro` | `3C:AB:72:B2:C6:67` | BM7-family, responded to probes |
| `punto_fa376ht` | `bm300pro` | `C8:17:F5:29:91:01` | BM7-family, weak RSSI |

## Safe Probe Workflow

Stop the normal gateway service only during direct BLE probes:

```sh
ssh admin@bmgateway.local 'sudo systemctl stop bm-gateway'
ssh admin@bmgateway.local 'bm-gateway protocol probe-history --device-id spare_nlp20'
ssh admin@bmgateway.local 'sudo systemctl start bm-gateway && systemctl is-active bm-gateway bm-gateway-web'
```

Both services must be active after every probe.

## Next Work

1. Implement a BM200/BM6 history reader for `hist_d15505_b7_01`.
2. Store decoded `voltage`, `soc`, and `temperature`; keep raw record and `p`.
3. Add duplicate handling for repeated 256-record pages.
4. Research or capture the paging mechanism for older BM200/BM6 history.
5. Decode or validate `p` using known cranking or charging-test events.
6. Run a separate BM300 Pro/BM7 history validation before importing BM7 history.

## References

- [Protocol Probe Tools](protocol-probe-tools.md)
- [BM6 / BM200 Integration Notes](2026-04-19-bm6-bm200-integration-notes.md)
- [BM300 Pro / BM7 Integration Notes](2026-04-25-bm300-bm7-integration-notes.md)
- [slydiman/bm7-battery-monitor](https://github.com/slydiman/bm7-battery-monitor)
- [JeffWDH/bm6-battery-monitor](https://github.com/JeffWDH/bm6-battery-monitor)
- [tarball.ca BM6 article](https://www.tarball.ca/posts/reverse-engineering-the-bm6-ble-battery-monitor/)
