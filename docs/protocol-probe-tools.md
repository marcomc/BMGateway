# Protocol Probe Tools

## Purpose

`BMGateway` includes a bounded BLE diagnostic command for BM200/BM6 and
BM300 Pro/BM7 protocol work.

Use it to:

- confirm live `d15507` readings
- capture encrypted and decrypted notifications
- download the verified BM200/BM6 256-record history page
- preserve JSONL evidence for parser work

It is not a fuzzer. It does not try unknown AES keys, brute force, bypass, or
broad command sweeps.

## Safety Model

The probe sends only this fixed allowlist:

| Command name | Plaintext command | Purpose |
| --- | --- | --- |
| `live_d15507` | `d1550700000000000000000000000000` | Current live state |
| `version_d15501` | `d1550100000000000000000000000000` | Raw version payload |
| `hist_d15505_zero` | `d1550500000000000000000000000000` | Empty history boundary baseline |
| `hist_d15505_b3_01` | `d1550501000000000000000000000000` | Bounded selector probe |
| `hist_d15505_b4_01` | `d1550500010000000000000000000000` | Bounded selector probe |
| `hist_d15505_b5_01` | `d1550500000100000000000000000000` | Bounded selector probe |
| `hist_d15505_b6_01` | `d1550500000001000000000000000000` | Bounded selector probe |
| `hist_d15505_b7_01` | `d1550500000000010000000000000000` | Verified BM200/BM6 history page |

Do not add commands without public-source evidence, official-app capture, or a
written local test plan.

## Operational Workflow

Direct BLE probes should not run while the normal gateway service is polling.

On the gateway host:

```sh
sudo systemctl stop bm-gateway
bm-gateway protocol probe-history --device-id spare_nlp20
sudo systemctl start bm-gateway
systemctl is-active bm-gateway bm-gateway-web
```

Both services must be active after every probe.

For two BM200 devices:

```sh
sudo systemctl stop bm-gateway
bm-gateway protocol probe-history \
  --device-id spare_nlp20 \
  --device-id spare_nlp5 \
  --command-timeout-seconds 3.5 \
  > /tmp/bm200-probe.jsonl
sudo systemctl start bm-gateway
systemctl is-active bm-gateway bm-gateway-web
```

## Command Reference

### `bm-gateway protocol probe-history`

Options:

| Option | Meaning |
| --- | --- |
| `--device-id <id>` | Limit to one configured device. May be repeated. |
| `--command-timeout-seconds <seconds>` | Wait time for notifications after each command. Default is `3.5`. |
| `--config <path>` | Standard global CLI option for an alternate config file. |

Family selection comes from configured device type:

| Configured type | Probe family |
| --- | --- |
| `bm200`, `bm6`, `bm900`, `bm900pro` | BM6 key and BM6 write behavior |
| `bm300`, `bm300pro`, `bm7` | BM7 key and BM7 write behavior |

## Output Format

The command prints JSONL: one JSON object per event.

Important event types:

| Event | Meaning |
| --- | --- |
| `device_found` | BLE advertisement found; includes name and RSSI when available. |
| `device_not_found` | No advertisement seen before scan timeout. |
| `command_result` | Notifications captured after one command. |
| `command_write_error` | BLE write failed. |
| `device_error` | Connection or notify handling failed. |

`command_result.packets` may include:

| Field | Meaning |
| --- | --- |
| `encrypted` | Raw notification bytes as hex. |
| `plaintext` | Decrypted notification bytes as hex. |
| `marker` | First three decrypted bytes. |
| `parsed` | Parsed fields when packet is a live `d15507` response. |
| `frames` | Long notifications split into decrypted 16-byte frames. |

Example live packet:

```json
{"marker":"d15507","parsed":{"status_code":0,"state":"normal","soc":88,"voltage":13.29,"temperature_c":20.0,"rapid_accel":0,"rapid_decel":0}}
```

## Decoding Reference

### Live `d15507`

BM200/BM6 and BM300 Pro/BM7 live packets use the same parsed fields:

| Field | Meaning |
| --- | --- |
| `voltage` | Battery voltage |
| `soc` | State of charge percentage |
| `temperature_c` | Temperature in degrees Celsius |
| `status_code` | Device-reported status code |
| `state` | Gateway label for `status_code` |
| `rapid_accel` | Raw rapid acceleration value |
| `rapid_decel` | Raw rapid deceleration value |

Status mapping:

| Code | State |
| --- | --- |
| `0` | `normal` |
| `1` | `low` |
| `2` | `charging` |

`charging` is monitor-reported. It does not prove that a charger is physically
connected.

### BM200/BM6 History Page

`hist_d15505_b7_01` returns a verified BM200/BM6 history page when records are
available.

Properties:

- 256 records per full page
- 4 bytes per record
- newest record first
- one record about every 2 minutes
- one page covers about 8 hours 32 minutes

Record layout:

```text
vvv ss tt p
```

Example:

```text
52b53170
```

Decodes as:

| Field | Decode | Meaning |
| --- | --- | --- |
| `vvv` | `0x52b / 100 = 13.23` | Voltage in volts |
| `ss` | `0x53 = 83` | SoC percentage |
| `tt` | `0x17 = 23` | Temperature in Celsius |
| `p` | `0` | Event or record type, unresolved |

The latest lower-SoC validation proved `ss` varies with live SoC:

| Device | Live SoC | Newest historical `ss` |
| --- | --- | --- |
| `spare_nlp20` | `82%` | first record `83%`, then older `84..100%` |
| `spare_nlp5` | `88%` | first records `88%`, then older `89..90%` |

The `spare_nlp20` one-point difference is consistent with the 2-minute history
cadence.

### BM300 Pro/BM7 History

BM300 Pro/BM7 live polling is verified. BM7 history is not decoded.

One BM7 unit returned 30 historical-looking 4-byte chunks for `d15505` byte-6
or byte-7 selectors, but the order, cadence, and field layout are not validated.
Do not import BM7 history yet.

## BM200 Shift Verification Recipe

To verify page order and cadence on a BM200/BM6 device:

1. Capture `hist_d15505_b7_01`.
2. Wait about 20 minutes with normal gateway polling running.
3. Capture again.
4. Compare raw 4-byte records.

Expected result:

- later page has about 10 newer records at the front
- `later[10:]` should match `earlier[:-10]`, allowing one-record variation when
  the interval is closer to 21 minutes

The verified `spare_nlp20` run produced:

| Pair | Interval | Offset | Mismatches |
| --- | --- | --- | --- |
| `t00 -> t20` | `1236 s` | `10` | `0` |
| `t20 -> t40` | `1245 s` | `11` | `0` |
| `t40 -> t60` | `1246 s` | `10` | `0` |
| `t00 -> t60` | `3727 s` | `31` | `0` |

## Result Triage

Useful quick checks:

```sh
grep '"event": "device_found"' /tmp/bm-protocol-probe.jsonl
grep '"command": "live_d15507"' /tmp/bm-protocol-probe.jsonl
grep '"command": "hist_d15505_b7_01"' /tmp/bm-protocol-probe.jsonl
```

If a device is not found:

- verify `bm-gateway` is stopped during the direct probe
- move the monitor closer to the Bluetooth adapter
- try one `--device-id`
- check whether the official phone app is connected

If `hist_d15505_b7_01` returns no record frames, save the JSONL anyway. Empty
responses are useful evidence for visibility, command timing, and family
differences.

## Related Documents

- [BM Protocol Research Handoff](2026-04-25-bm-protocol-research-handoff.md)
- [BM6 / BM200 Integration Notes](2026-04-19-bm6-bm200-integration-notes.md)
- [BM300 Pro / BM7 Integration Notes](2026-04-25-bm300-bm7-integration-notes.md)
