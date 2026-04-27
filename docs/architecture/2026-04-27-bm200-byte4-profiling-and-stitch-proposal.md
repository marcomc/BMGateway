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

As of 2026-04-28, pause byte-4 import work and let the gateway collect several
weeks of ordinary runtime samples first. The only BM200/BM6 history that is
safe to import into the main SQLite history today is the existing byte-7
current-window archive sync. Byte-4 captures are real history evidence, but
they should remain protocol evidence until a later offline stitch pass can
anchor them against enough locally collected samples.

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

Later discussion clarified the naming:

- `b4=47` means command byte at index `4` has hex value `0x47`; byte index `7`
  remains a separate command byte.
- `0x47` is decimal `71`, but no evidence shows it means 71 hours, 71 pages, or
  a direct duration. Treat it as an opaque selector until proven otherwise.
- `8192` records at one sample every two minutes equals about 273 hours, or
  11.4 days. A full 30-day retention window would require about 21600 records,
  so multiple windows or banks are likely.

The focused byte-4/byte-7 matrix also refined the model:

| Byte-4 selector | Byte-7 behavior | Interpretation |
| --- | --- | --- |
| `b4=0a` | `b7=10`, `20`, and `55` returned cumulative windows | Strong evidence that byte 7 is depth inside this byte-4 window |
| `b4=10` | `b7=20` is contained in `b7=55` | Same model, with a higher apparent threshold |
| `b4=2f` | Only `b7=55` returned data in the focused matrix | Real data, but still caution |
| `b4=09` | Returned empty in the focused matrix, despite earlier success | Do not discard; repeat later |
| `b4=47` | Returned empty in the focused matrix, despite earlier success | Do not discard; repeat later |

This supports the working model:

```text
byte 4 = history window or bank selector
byte 7 = cumulative depth inside the selected window
```

However, byte-7 depth appears to have selector-specific thresholds; values
`01..06` can return empty for byte-4 windows even when higher byte-7 values
return data.

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

Do not start this phase until the gateway has accumulated enough local samples
to use as a trustworthy timeline. The intended workflow after the pause is:

1. Keep importing the already-supported byte-7 current-window history.
2. Let periodic runtime collection run for a few weeks.
3. Repeat focused byte-4/byte-7 probes for `b4=09`, `0a`, `10`, `2f`, and
   `47`, plus any new candidate bank selectors.
4. Compare device-returned records against the local database timeline before
   placing byte-4 records into the main archive table.
5. Only import byte-4 records whose placement is proven by long sequence
   overlap and plausible physical fields.

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

## Resume Prompt

Copy this prompt into a future Codex chat to resume the work:

```text
We are resuming BM200/BM6 history protocol work in
/Users/mmassari/Development/BMGateway. Read AGENTS.md, TODO.md,
docs/architecture/2026-04-27-bm200-byte4-profiling-and-stitch-proposal.md,
docs/2026-04-25-bm-protocol-research-handoff.md, and
docs/protocol-probe-tools.md.

Context: byte-7 d15505 history sync is the only BM200/BM6 history currently
safe to import into the main DB. Byte 4 returns real historical records in the
same vvv ss tt p layout, but byte-4 import is paused until enough local samples
exist to anchor timestamps. Byte 6 did not help. Byte 7 is cumulative current
window/depth. Byte 4 appears to be a history window/bank selector, and byte 7
appears to be depth inside that selected byte-4 window for at least b4=0a and
b4=10. b4=09 reached 8192 records in previous captures, b4=2f has a long
overlap with an ambiguous prefix, and b4=47 looked like a clean trimmed window
but later returned empty in a focused matrix session.

Important local artifacts are ignored by Git under output/protocol-probes/.
Start by reviewing output/protocol-probes/MANIFEST.md and rerun:

bm-gateway protocol analyze-history-captures \
  --input output/protocol-probes/bm200-b4-shift-t0-spare_nlp5-20260427-181107.jsonl \
  --input output/protocol-probes/bm200-b4-shift-t0b-group09-spare_nlp5-20260427-181324.jsonl \
  --input output/protocol-probes/bm200-b4-shift-t1-spare_nlp5-20260427-211240.jsonl \
  --input output/protocol-probes/bm200-b7-55-retry-t1-spare_nlp5-20260427-211824.jsonl \
  --input output/protocol-probes/bm200-b4-b7-matrix-spare_nlp5-20260427-223814.jsonl \
  --input output/protocol-probes/bm200-b4-b7-matrix-retry-spare_nlp5-20260427-224234.jsonl

Then inspect the current SQLite archive/history collected since the pause,
compare it against byte-4 captures, and only propose/import byte-4 records when
timestamp placement is proven by long sequence overlap. Do not deduplicate by
raw record equality alone because stable batteries repeat identical records.
Keep zero-like records such as 00000001 as raw markers. If code changes are
made, use TDD, run make check, and deploy to bmgateway.local for CLI/runtime
changes.
```
