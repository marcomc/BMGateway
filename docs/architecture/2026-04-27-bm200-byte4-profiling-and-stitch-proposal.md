# BM200 Byte-4 Profiling and Offline Stitch Proposal

## Goal

Determine whether the BM200/BM6 byte-4 `d15505` history ranges contain
meaningful records, document the remaining unknown fields, and only then build
an offline stitch plan for importing missing history.

## Current Evidence

The 2026-04-27 `spare_nlp5` captures show that byte 4 is not opaque noise.
When decoded with the same modern BM6/BM900 and BM7/BM300 history layout,
records become plausible physical readings:

```text
vvv ss tt p
```

| Field | Meaning | Confidence |
| --- | --- | --- |
| `vvv` | Voltage in centivolts | High |
| `ss` | State of charge | High |
| `tt` | Temperature Celsius | High |
| `p` | Event/status nibble | Medium; keep raw |

Byte 6 is not useful for BM200 history expansion because all tested values
returned the current saturated byte-7 window. Byte 7 is useful but already
understood as the cumulative current-window selector. Byte 4 is the only
observed selector that exposes additional plausible history ranges.

## Profiling Phase

Before importing byte-4 ranges into SQLite, run an offline profile across the
saved JSONL captures:

```sh
bm-gateway protocol analyze-history-captures \
  --input output/protocol-probes/bm200-b4-shift-t0-spare_nlp5-20260427-181107.jsonl \
  --input output/protocol-probes/bm200-b4-shift-t0b-group09-spare_nlp5-20260427-181324.jsonl \
  --input output/protocol-probes/bm200-b4-shift-t1-spare_nlp5-20260427-211240.jsonl \
  --input output/protocol-probes/bm200-b7-55-retry-t1-spare_nlp5-20260427-211824.jsonl
```

The profiler must report:

- decoded voltage, SoC, temperature, and event distributions;
- zero-like marker records such as `00000001`;
- exact sequence overlaps between repeated captures of the same selector;
- selector-level stitch recommendations.

The current expected recommendations are:

| Selector | Expected status | Reason |
| --- | --- | --- |
| `b7=55` | Stitch candidate | Current window shifted by 93 records |
| `b4=0a` | Stitch candidate | Previous window appears at offset 90 |
| `b4=10` | Stitch candidate | Previous window appears at offset 90 |
| `b4=47` | Trimmed stitch candidate | Prefix preserved at offset 91, old tail trimmed |
| `b4=09` | Capped stitch candidate | Shifts, but reached the 8192-record cap |
| `b4=2f` | Caution | Long overlap starts at old offset 40 |

## Offline Stitch Phase

After profiling, build the import timeline offline before touching the real
database:

1. Treat byte-7 `b7=55` as the known current-window anchor.
2. Add clean byte-4 rolling selectors first: `b4=0a`, `b4=10`, and `b4=47`.
3. Keep `b4=09` capped-window records only where long sequence overlap proves
   placement.
4. Keep `b4=2f` in a caution bucket until the ambiguous prefix is explained.
5. Preserve zero-like marker records as raw evidence, but do not turn them into
   ordinary voltage readings.
6. Deduplicate by sequence placement and timestamp, not by raw value alone,
   because stable batteries repeat identical records.

## Acceptance Criteria

- The profiler can be rerun from saved JSONL without BLE access.
- The report identifies meaningful decoded fields and marker records.
- The report flags selector confidence before import.
- The stitcher can produce a candidate timeline with no impossible voltage,
  SoC, or temperature values.
- Ambiguous byte-4 prefixes are excluded from normal import until explained.

## Implementation Status

Initial implementation is available through:

```sh
bm-gateway protocol analyze-history-captures --input CAPTURE.jsonl
```

This command is intentionally offline: it does not connect to BLE, does not
write SQLite rows, and does not alter the gateway service.
