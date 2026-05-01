# BM300 Byte-7 Multipage Investigation and Controlled Import Plan

## Goal

Bring BM300 Pro / BM7 onboard history recovery to at least the same practical
level as the current BM200/BM6 multipage path: prove a usable cumulative paging
axis, implement conservative overlap-based stitching, and support controlled
SQLite import on a separate database for validation before any normal product
surface is changed.

## Current Evidence

The current BM300 Pro / BM7 archive importer uses profile
`bm7_d15505_b6_v1`, requests:

```text
d1550500000001000000000000000000
```

and imports selector `01` as one newest-first archive window in the same:

```text
vvv ss tt p
```

layout already used by BM200/BM6.

Earlier project evidence established:

- selector `b6=01` imported `883` records on `doc_fb12899`, about 29 hours
  26 minutes at the observed 2-minute cadence;
- the newest selector-`01` records matched live voltage, SoC, and
  temperature;
- selectors beyond `01` were implemented only as bounded candidates and were
  never validated strongly enough for normal import.

The 2026-04-30 live probe on `admin@bmgateway.local` added a more important
finding:

- `hist_d15505_b6_01` returned `3709` records;
- `hist_d15505_b6_02` returned `3711` records;
- `hist_d15505_b7_01` returned `256` records;
- `hist_d15505_b7_02` returned about `512` useful records;
- the first `256` records of `b7_01` matched a prefix of `b6_02`.

This is enough to reject the old one-axis model "BM300 multipage is just byte 6
page count". BM300 history appears to use at least two meaningful selector
axes, and the most promising candidate for a BM200-like cumulative depth axis
is now byte `7`, not byte `6`.

## Working Model

Use this as the implementation hypothesis until stronger evidence disproves it:

```text
byte 7 = cumulative depth selector for the active BM300 history window
byte 6 = bank, window, or range selector that still needs separate profiling
```

This mirrors the useful BM200 mental model more closely:

```text
BM200: byte 7 = depth, byte 4 = bank/window
BM300: byte 7 = depth candidate, byte 6 = bank/window candidate
```

Do not treat this as settled protocol truth. Treat it as the narrowest useful
hypothesis that can drive the next implementation slice.

## Scope of This Slice

This slice is protocol investigation plus controlled importer implementation.
It is not a product-surface simplification slice.

In scope:

- probe BM300 selectors `b7=01`, `02`, and `03` as the first cumulative-depth
  candidate;
- compare consecutive selector results by exact raw-record overlap;
- implement a controlled BM300 multipage import path when overlap passes the
  validation gate;
- write only to an explicitly supplied SQLite database path;
- keep the existing BM300 normal importer and normal UI/CLI behavior unchanged.

Out of scope:

- changing normal `history sync-device` behavior;
- exposing BM300 multipage through the web UI;
- removing the existing `bm7_d15505_b6_v1` path;
- proving the entire advertised 72-day retention window in one step;
- adding new persistent DB metadata for per-device validation depth.

## Decisions from the 2026-04-30 Design Session

- The goal of this work is not merely BM300 feature parity in appearance. It is
  BM300 multipage recovery at least to the same practical level as BM200/BM6.
- The first success criterion is not "a new probe exists". It is a usable
  importer strategy.
- The first milestone is proving and importing a coherent BM300 cumulative axis
  across `b7=01`, `b7=02`, and `b7=03`.
- Timestamp anchoring may remain estimated in the first implementation, as long
  as selector overlap is strong and explicit.
- Stitching must be conservative: exact `raw_record` overlap only.
- The initial validation gate is at least `128` consecutive identical raw
  records between consecutive selector depths.
- If `01 -> 02` passes but `02 -> 03` fails, import only to the deepest
  validated selector and fail the deeper extension.
- Validation evidence should remain in probe reports and capture artifacts for
  now; do not add new validation columns or tables yet.
- The new BM300 multipage path must be separate from the existing archive sync
  path.
- The implementation surface belongs under `bm-gateway protocol`, not under the
  normal `history` commands.
- When the validation gate is not met, the experimental command must fail
  explicitly.
- Controlled import must write only to a caller-supplied SQLite path, never to
  the normal runtime database.

## Overlap and Stitching Rules

For the first BM300 multipage importer:

1. Fetch candidate selectors in order: `b7=01`, `b7=02`, `b7=03`.
2. Decode records with the existing `vvv ss tt p` layout.
3. Compare raw 4-byte records only; do not deduplicate by decoded physical
   values because stable batteries repeat identical readings.
4. For each consecutive selector pair, search for the longest exact overlap of
   consecutive `raw_record` values.
5. Accept the deeper selector only if the strongest overlap includes at least
   `128` consecutive identical records.
6. When accepted, import only the prefix that is older than the shallower
   selector.
7. When rejected, stop at the last validated depth and fail the attempted
   extension explicitly.

This first implementation is intentionally simple and falsifiable. If the model
is wrong, the overlap rule should fail clearly.

## Falsification Goal Of This Slice

Treat the current BM300 theory as:

```text
byte 7 = cumulative depth
byte 6 = separate bank or window candidate
```

This slice is meant to attack the first half of that theory directly.

The primary predictions are:

- `b7=02` should preserve `b7=01` as an exact raw-record prefix;
- `b7=03` should preserve `b7=02` as an exact raw-record prefix;
- if the model is wrong, one of those prefix relationships should fail
  reproducibly under bounded retest.

Practical disproof conditions:

- a repeated `01 -> 02` or `02 -> 03` fetch does not produce a long exact
  overlap;
- overlap exists only by decoded physical values, not by exact raw-record
  sequence;
- a supposedly deeper selector returns records that cannot be placed as a clean
  older extension of the shallower selector.

If the slice survives those checks, treat it as partial progress only. It means
the byte-7 depth model is strong enough to use for bounded import on that
device. It does not prove that `byte 6` is the bank axis, and it does not prove
the full 72-day recovery strategy.

## Controlled Import Surface

Add a new experimental command under `bm-gateway protocol`.

Suggested shape:

```text
bm-gateway protocol bm300-multipage-import \
  --device-id <device-id> \
  --output-db <sqlite-path> \
  --depth 3 \
  [--json]
```

Expected behavior:

- use BM300 probe/import logic only;
- use `byte 7` selectors from `01` through the requested depth;
- default the requested depth to `3` for the first slice;
- refuse to write unless `--output-db` is supplied;
- produce a structured report including:
  - tested selectors
  - fetched-record counts
  - strongest overlap lengths
  - validated maximum depth
  - inserted-row count
  - explicit failure reason when the gate is not met

This command is experimental protocol tooling, not a normal end-user history
surface.

## Implementation Plan

### Phase 1: Probe and compare

- Extend or reuse the BM300 probe path so `b7=01..03` can be fetched
  intentionally for one configured device.
- Preserve enough structured data to compare exact raw-record sequences.
- Report overlap lengths between `01 -> 02` and `02 -> 03`.

### Phase 2: Controlled import

- Implement a BM300 experimental importer that:
  - validates overlap;
  - builds the stitched selector timeline conservatively;
  - assigns estimated timestamps on the same 2-minute cadence used today;
  - imports only validated older prefixes into a caller-supplied SQLite file.

### Phase 3: Test coverage

- Unit-test overlap detection with synthetic record sequences.
- Unit-test the stop-on-failed-depth rule.
- Unit-test that the command refuses to write without an explicit output DB.
- Unit-test that only validated prefixes are imported.

### Phase 4: Live validation

- Run the protocol command against `doc_fb12899` on `admin@bmgateway.local`.
- Save JSONL or equivalent structured captures.
- Verify whether `b7=01 -> 02` and `02 -> 03` meet the `128`-record gate.
- Only after the gate passes, test controlled import into a disposable SQLite
  path outside the normal runtime DB.

## Acceptance Criteria

- A new BM300 experimental protocol command exists under `bm-gateway protocol`.
- The command can fetch BM300 `b7=01..03` candidates for a configured device.
- The command reports exact overlap lengths between consecutive depths.
- The command fails explicitly when overlap is shorter than `128` consecutive
  raw records.
- The command writes only to an explicitly supplied SQLite path.
- When overlap passes, the command imports only the validated older prefixes
  and leaves the runtime database untouched.
- Targeted tests cover overlap acceptance, overlap rejection, and controlled DB
  writes.

## Open Questions After This Slice

- What exact role does BM300 `byte 6` play when `byte 7` is treated as depth?
- Does `byte 6` select banks, windows, time ranges, or some combination?
- Is `b7=03` still cumulative in the same way as `b7=02`, or do thresholds or
  saturation rules change?
- Can BM300 timestamps later be anchored more strongly than estimated cadence?
- Does the final `p` nibble carry the same type of event semantics suspected in
  BM200?

## References

- [docs/2026-04-25-bm300-bm7-integration-notes.md](../2026-04-25-bm300-bm7-integration-notes.md)
- [docs/2026-04-25-bm-protocol-research-handoff.md](../2026-04-25-bm-protocol-research-handoff.md)
- [docs/protocol-probe-tools.md](../protocol-probe-tools.md)
- [docs/architecture/2026-04-26-history-backfill-integration-proposal.md](2026-04-26-history-backfill-integration-proposal.md)
- [docs/architecture/2026-04-27-bm200-byte4-profiling-and-stitch-proposal.md](2026-04-27-bm200-byte4-profiling-and-stitch-proposal.md)

## Resume Prompt

Copy this prompt into a future Codex chat to implement the next slice:

```text
We are resuming BM300 Pro / BM7 multipage history work in
/Users/mmassari/Development/BMGateway.

Read:
- AGENTS.md
- TODO.md
- docs/2026-04-25-bm300-bm7-integration-notes.md
- docs/2026-04-25-bm-protocol-research-handoff.md
- docs/protocol-probe-tools.md
- docs/architecture/2026-04-30-bm300-byte7-multipage-investigation-plan.md
- docs/architecture/2026-04-27-bm200-byte4-profiling-and-stitch-proposal.md

Goal:
- bring BM300 Pro / BM7 onboard history recovery to at least the same
  practical level as BM200/BM6 multipage recovery

Current working model:
- byte 7 is the BM300 cumulative depth candidate
- byte 6 is a separate bank/window candidate that is still unresolved

Implement:
- a new experimental `bm-gateway protocol` subcommand for BM300 multipage
  controlled import
- fetch selectors b7=01,02,03
- validate overlap by exact raw_record sequence only
- require at least 128 consecutive identical raw records between consecutive
  depths
- if overlap fails, exit with explicit failure and do not write
- if overlap passes, import only the validated older prefix
- write only to an explicitly supplied SQLite path, never to the normal runtime
  DB

Also:
- add targeted tests
- run make check
- run markdownlint on any edited Markdown files

If live validation is needed, the real gateway is reachable at:
- ssh admin@bmgateway.local

Use non-destructive live probes first. Do not write to the gateway runtime DB.
```
