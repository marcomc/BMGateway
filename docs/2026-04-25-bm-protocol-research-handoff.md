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

The byte at index 7 is now verified as a cumulative page count for BM200/BM6:

| Selector | Meaning | Local validation |
| --- | --- | --- |
| `01` | latest page | verified |
| `02` | latest 2 pages | verified by first 256-record overlap |
| `03` | latest 3 pages | verified by first 512-record overlap |

`BMGateway` uses this in production BM200/BM6 archive import through:

```sh
bm-gateway history sync-device --device-id spare_nlp5 --page-count 3
```

The command still treats timestamps as estimated because the device records do
not include absolute timestamps.

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

Three cumulative pages cover about 25 hours 36 minutes. Local gateway
validation imported:

| Device | Page count | Imported records |
| --- | --- | --- |
| `spare_nlp5` | `3` | `765` |
| `spare_nlp20` | `3` | `748` |

Manual full-window sync on `spare_nlp5` currently requests byte-7 selector
`0x55` (`85`) to match the 30-day advertised BM200 retention estimate. On
2026-04-27, the device returned only about 1455-1456 non-empty records, covering
roughly 48 hours 30 minutes:

| Selector | Records | Observed range |
| --- | --- | --- |
| `01` | `256` | `2026-04-27 08:20` .. `2026-04-27 16:50` |
| `03` | `768` | `2026-04-26 15:16` .. `2026-04-27 16:50` |
| `0a` | `1456` | `2026-04-25 16:22` .. `2026-04-27 16:52` |
| `55` | `1456` | `2026-04-25 16:22` .. `2026-04-27 16:52` |

This proves only that the current selector form saturates around 1456 records
on that capture. It does not prove the BM200 has no older retained data. Two
open explanations remain:

- the device may have had only that many records available because older memory
  was reset or overwritten before the test;
- another byte in `d15505` may select an offset, bank, cursor, direction, or
  segment needed to reach older history.

A controlled single-byte matrix was run for `spare_nlp5` using base command
`d1550500000000550000000000000000` and mutating one zero byte at a time to
`0x01`. The packaged probe tooling now writes unbuffered JSONL after each
command so long captures do not appear silent.

Primary captures:

| Capture | Path |
| --- | --- |
| Matrix | `/tmp/bm200-b7-55-matrix-spare_nlp5-20260427-153247.jsonl` |
| Byte-4 deepen | `/tmp/bm200-b7-55-b4-deepen-repeat-spare_nlp5-20260427-154307.jsonl` |
| Byte-8 deepen | `/tmp/bm200-b7-55-b8-deepen-spare_nlp5-20260427-153804.jsonl` |
| Byte-10 deepen | `/tmp/bm200-b7-55-b10-deepen-spare_nlp5-20260427-153855.jsonl` |
| Byte-12 deepen | `/tmp/bm200-b7-55-b12-deepen-spare_nlp5-20260427-153946.jsonl` |
| Byte-14 deepen | `/tmp/bm200-b7-55-b14-deepen-spare_nlp5-20260427-154036.jsonl` |
| Byte-4 sweep | `/tmp/bm200-b7-55-b4-sweep-00-ff-spare_nlp5-20260427-160351.jsonl` |
| Byte-6 sweep | `/tmp/bm200-b7-55-b6-sweep-00-ff-spare_nlp5-20260427-161648.jsonl` |
| Byte-7 sweep | `/tmp/bm200-b7-55-b7-sweep-00-ff-spare_nlp5-20260427-164223.jsonl` |

Matrix result:

- Baseline `d1550500000000550000000000000000` returned 1476 records, with the
  same approximate 48-hour range seen earlier.
- Byte indexes `4`, `8`, `10`, `12`, and `14` set to `01` returned only a
  short marker response (`fefefe...` followed by `fffefe...`) rather than
  history records. The first matrix file was captured just before the
  `fefefe` marker-count fix, so its summary counts those marker rows as one
  record; treat them as zero history records.
- Other tested byte indexes returned the same current 48-hour window, with
  one-record count differences consistent with new two-minute samples arriving
  during the run.

Byte index `4` is now the strongest BM200/BM6 segment or range selector
candidate. The repeat deepen produced:

| Command | Records | Notable raw boundary |
| --- | ---: | --- |
| `b4=02` | 970 | oldest raw `5b164122` |
| `b4=03` | 714 | oldest raw `5b164122` |
| `b4=04` | 458 | oldest raw `5b164122` |
| `b4=10` | 6198 | newest raw `4f056080`, oldest raw `50a59130` |
| `b4=20` | 2111 | newest raw `51560200`, oldest raw `50a59130` |
| `b4=40` | 77 | `4ee5d090` .. `4ef5e090` |
| `b4=80` | 0 | empty marker |
| `b4=ff` | 0 | empty marker |

The full byte-4 sweep confirmed multiple valid groups, not one continuous
linear page selector:

| Byte-4 range | Result |
| --- | --- |
| `00..01` | empty |
| `02..05` | non-empty current-window suffixes ending at oldest raw `5b164122` |
| `06..08` | empty |
| `09..28` | non-empty large group ending at oldest raw `50a59130`; `09` returned 7998 records |
| `29..2e` | empty |
| `2f..40` | non-empty group ending at oldest raw `4ef5e090` |
| `41..46` | empty |
| `47..54` | non-empty group ending at oldest raw `5325a170` |
| `55..ff` | empty |

Byte index `6` is not useful for BM200/BM6 archive range selection in this
test. Every `00..ff` value returned the same current byte-7 window with the
same oldest raw boundary `5b164122`; small count changes were consistent with
new two-minute samples arriving during the long sweep.

Byte index `7` remains the cumulative page-count selector. The full byte-7
sweep showed:

| Byte-7 range | Result |
| --- | --- |
| `00` | empty |
| `01..05` | 256-record increments: 256, 512, 768, 1024, 1280 |
| `06..76` | saturated current window, about 1511-1517 records |
| `77..97` | odd values empty, even values saturated |
| `98..ff` | saturated current window, ending around 1522 records |

The byte-7 sweep did not reveal access to older history beyond the saturated
current window. It only clarified selector behavior and the empty-marker
pattern for high odd values.

The first raw-record overlap pass found:

- `b4=02` is a suffix of the current byte-7 window. In the `b7=55` capture, the
  whole `b4=02` sequence starts at record offset `535`, so it does not add new
  historical coverage.
- Inside each non-empty byte-4 group, higher selector values are usually tails
  of the lower selector value. For example, `b4=0a` is a tail of `b4=09`,
  `b4=30` is a tail of `b4=2f`, and `b4=48` is a tail of `b4=47`.
- Representative group heads `b4=09`, `b4=2f`, and `b4=47` did not show long
  exact raw-record overlap with the current byte-7 window or with each other.

This means byte 4 likely exposes separate archive segments, but their
chronological order and timestamp anchors are not proven yet.

Follow-up shift baseline captured on 2026-04-27:

| Capture | Path | Notes |
| --- | --- | --- |
| Byte-4 shift `t0` | `/tmp/bm200-b4-shift-t0-spare_nlp5-20260427-181107.jsonl` | Captured `b7=55`, `b4=2f`, and `b4=47`; first `b4=09` attempt returned empty. |
| Byte-4 shift `t0b` | `/tmp/bm200-b4-shift-t0b-group09-spare_nlp5-20260427-181324.jsonl` | Recaptured group A with `b4=09`, `0a`, and `10`; `b4=09` returned 8063 records. |

Repeat the same focused capture about 20 minutes later and compare whether
`b4=09`, `b4=2f`, and `b4=47` shift by about 10 records. If they do, the
segments can be timestamp-anchored with much higher confidence.

The probe summaries estimate timestamps by anchoring the first returned record
to the probe time and walking backward at two-minute cadence. That is useful
for ordinary newest-first pages but is not proven for byte-4 segmented ranges.
Before importing byte-4 ranges into SQLite, compare raw-record overlap and
ordering against the baseline and against each other. Do not import byte-4
segments into SQLite until that stitching is proven; otherwise duplicate raw
records or false timestamps are likely.

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
- Safe stitching for byte-4 ranges before claiming full advertised 30-day
  history recovery. Byte 7 is a cumulative selector, but the full byte-7 sweep
  still saturated around 1511-1522 records on `spare_nlp5`; byte 4 is the only
  strong segment/range candidate found so far.
- Cranking, charging-test, or waveform event records. These may use `p`,
  another `d15505` selector, or another command family.

## BM300 Pro/BM7 Onboard History

Live `d15507` polling is implemented and verified for BM300 Pro/BM7 with the
BM7 key. It uses the same live response offsets as BM6/BM200.

BM300 Pro/BM7 archive import is implemented as profile `bm7_d15505_b6_v1` and
is disabled by default for automatic background sync. Manual CLI sync can still
run against a named BM300 Pro device for controlled tests.

Known facts:

- The BM2 `e7xx` history-count variants tested on BM7 produced no notification.
- Zero-payload `d15505` can return marker-shaped responses.
- The verified BM7 history request uses byte 6:

  ```text
  d1550500000001000000000000000000
  ```

- `doc_fb12899` returned newest records that match live voltage, SoC, and
  temperature using the same record layout as BM200/BM6:

  ```text
  vvv ss tt p
  ```

Examples:

| Raw record | Voltage | SoC | Temperature | Event/type |
| --- | --- | --- | --- | --- |
| `53b620f0` | `13.39 V` | `98%` | `15 C` | `0` |
| `53a620e0` | `13.38 V` | `98%` | `14 C` | `0` |

The first production sync on `doc_fb12899` imported 883 selector-`01` records,
which is about 29 hours 26 minutes at the observed 2-minute cadence.

Open BM7 history items:

- exact page/range semantics for byte-6 selectors beyond `01`
- full recovery strategy for the advertised 72-day retention window
- meaning of the final `p` nibble
- whether cranking or charging-test records appear in the same stream or use
  another command

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

1. Analyze raw-record overlap across the BM200/BM6 byte-4 captures before
   importing those segments or claiming full 30-day recovery.
2. Validate BM300 Pro/BM7 byte-6 selectors beyond `01` before claiming full
   72-day recovery.
3. Add stronger raw-sequence timestamp alignment for long absences and service
   restarts.
4. Report last archive-sync time, inserted rows, duplicate rows, and failure
   reason in status output.
5. Decode or validate `p` using known cranking or charging-test events.

## References

- [Protocol Probe Tools](protocol-probe-tools.md)
- [BM6 / BM200 Integration Notes](2026-04-19-bm6-bm200-integration-notes.md)
- [BM300 Pro / BM7 Integration Notes](2026-04-25-bm300-bm7-integration-notes.md)
- [slydiman/bm7-battery-monitor](https://github.com/slydiman/bm7-battery-monitor)
- [JeffWDH/bm6-battery-monitor](https://github.com/JeffWDH/bm6-battery-monitor)
- [tarball.ca BM6 article](https://www.tarball.ca/posts/reverse-engineering-the-bm6-ble-battery-monitor/)
