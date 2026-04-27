# History Backfill Integration Proposal

## Table of Contents

- [Summary](#summary)
- [Verified Constraints](#verified-constraints)
- [Goals](#goals)
- [Non-Goals](#non-goals)
- [Data Model](#data-model)
- [Sync Triggers](#sync-triggers)
- [Deduplication And Timestamping](#deduplication-and-timestamping)
- [Paging Research Plan](#paging-research-plan)
- [Configuration](#configuration)
- [Implementation Tasks](#implementation-tasks)
- [Acceptance Criteria](#acceptance-criteria)
- [References](#references)

## Summary

`BMGateway` should keep the existing live polling loop and add a separate
archive backfill path for monitor-stored history.

The live loop answers "what can the gateway see now?" every configured poll
interval. The archive path answers "what did the battery monitor record while
the gateway was not connected or while it was polling at lower resolution?"

For BM200/BM6, and for the verified BM300 Pro/BM7 byte-6 selector, the latest
onboard history records decode as:

```text
vvv ss tt p
```

That gives voltage, SoC, temperature, and an unresolved event/type nibble every
2 minutes. The import path should preserve all 2-minute archive samples without
overwriting the lower-frequency live samples.

## Verified Constraints

Live polling:

- Current normal polling is usually every 15 minutes.
- Live `d15507` gives current voltage, SoC, temperature, state, RSSI context,
  and connectivity status.
- Live rows are still valuable even after archive import because they preserve
  gateway visibility, RSSI, and failures.

BM200/BM6 and BM300 Pro/BM7 archive:

- `hist_d15505_b7_01` returns the latest verified history page.
- `hist_d15505_b6_01` returns the latest verified BM300 Pro/BM7 archive
  selector.
- Records are newest-first.
- Records are spaced about 2 minutes apart.
- Each record decodes as `vvv ss tt p`.
- `p` is unresolved and must be stored raw.

BM200/BM6-specific paging:

- One full BM200/BM6 page contains 256 records.
- One BM200/BM6 page covers about 8 hours 32 minutes.
- Byte 7 of `d15505` is a cumulative page count on tested BM200/BM6 devices.
- Selectors `01`, `02`, and `03` are verified as latest 1, 2, and 3 pages.

BM300 Pro/BM7-specific paging:

- Byte 6 selector `01` is validated against live voltage, SoC, and temperature.
- A live BM300 Pro/BM7 selector-`01` import returned 883 records, about
  29 hours 26 minutes at 2-minute cadence.
- Selectors beyond `01` are implemented as bounded candidates but need
  overlap/range validation before relying on full 72-day recovery.

Published device capacities:

- ANCEL BM200 is advertised as storing up to 30 days of voltage, charge
  percentage, and temperature every 2 minutes.
- ANCEL BM300 Pro is advertised as storing up to 72 days of data.

Important current limitation:

- BM200/BM6 cumulative paging is only verified through 3 pages so far.
- With the current safe production default, a returning vehicle can backfill
  about 25 hours 36 minutes.
- Full advertised 30-day BM200/BM6 recovery would require validating much
  higher cumulative page counts, around 85 pages if the current page size holds.
- BM300 Pro/BM7 history uses a separate profile and is disabled by default for
  automatic sync until byte-6 page/range behavior is validated beyond selector
  `01`.

## Goals

- Preserve 2-minute historical battery samples when monitors return to range.
- Avoid duplicates when live samples and archive samples overlap.
- Avoid replacing live connectivity evidence with archive data.
- Keep BLE use bounded so normal monitoring does not monopolize devices.
- Make the strategy safe before BM200/BM6 paging is known.
- Leave a clean extension point for higher BM200/BM6 and BM300 Pro/BM7 page
  validation.

## Non-Goals

- Do not implement continuous live streaming here.
- Do not enable automatic BM300 Pro/BM7 history import by default before
  byte-6 page/range behavior is validated beyond selector `01`.
- Do not treat the final BM200/BM6 `p` nibble as a live status code.
- Do not delete live rows after importing archive rows.

## Data Model

Keep two data classes conceptually separate:

| Source | Purpose | Cadence |
| --- | --- | --- |
| `live` | Gateway observations, connectivity, RSSI, device state, MQTT/UI freshness | normal poll interval |
| `device_archive` | Device-recorded voltage, SoC, temperature, raw record data | device history cadence |

The archive table should support BM200/BM6 decoded fields directly:

- `device_id`
- `ts`
- `voltage`
- `soc`
- `temperature`
- `raw_record`
- `event_type` or raw `p`
- `history_profile`, for example `bm6_d15505_b7_v1`
- `page_selector`
- `record_index`
- `imported_at`
- `timestamp_quality`, for example `estimated` or `overlap_aligned`

Existing live queries can keep returning both live and archive rows through a
`sample_source` field. Chart and analytics code should prefer archive rows for
dense voltage, SoC, and temperature trends, while still using live rows for
connectivity and RSSI.

## Sync Triggers

### Reconnect Backfill

Run an archive sync after a device returns online if the previous live polling
cycle missed it at least once.

Example:

1. `10:00` live poll succeeds.
2. Vehicle leaves shortly after.
3. `10:15` live poll fails with `device_not_found`.
4. Vehicle returns.
5. `10:30` live poll succeeds.
6. Immediately run archive sync for that device.

This captures the short-trip case without waiting for the next periodic archive
window.

### Periodic Sync While Visible

Run periodic archive syncs even when the device never disappears, so garage
devices accumulate the higher-resolution 2-minute archive.

Recommended defaults while higher page counts are still being validated:

| Device family | Periodic archive interval | Reason |
| --- | --- | --- |
| BM200/BM6 | 6 hours | conservative while full 30-day recovery is not validated |
| BM300 Pro/BM7 | disabled by default | record layout is decoded, but full 72-day page/range behavior is not validated |

After BM200/BM6 paging is decoded, the interval can be relaxed because the sync
can walk older pages until it finds overlap.

Recommended future defaults with paging:

| Device family | Periodic archive interval | Reason |
| --- | --- | --- |
| BM200/BM6 | 24 hours, configurable | advertised 30-day retention gives margin |
| BM300 Pro/BM7 | configurable after page/range validation | advertised 72-day retention but higher selectors need proof |

### Startup Sync

On service startup, if a device is visible and its last successful archive sync
is older than the configured archive interval, run archive sync after the first
successful live poll.

### Manual Sync

Expose a manual "Sync history now" action for the configured archive families.
It should run the same bounded path as automatic sync and report inserted,
ignored, and failed records.

## Deduplication And Timestamping

Archive import must be idempotent. Downloading the same page repeatedly should
insert only new records.

Recommended approach:

1. Decode all records and preserve raw 4-byte strings.
2. Compare the new page against existing archive rows for the same device and
   profile.
3. Find the strongest overlap using raw record sequence plus decoded values.
4. If overlap is found, align timestamps from the existing archive grid.
5. If no overlap is found, estimate timestamps from download time:
   `download_time - index * 120 seconds`.
6. Mark estimated timestamps with `timestamp_quality = estimated`.
7. Insert with a uniqueness rule that prevents duplicates for the same device,
   profile, and timestamp or archive sequence.

Live rows should not be overwritten. If a live row and archive row land near the
same time, keep both. Presentation code can choose:

- archive for dense trend lines
- live for connectivity, RSSI, and device-reported current state
- both when debugging data provenance

This avoids losing a live failure or RSSI observation just because the device
later supplied archive measurements for the same period.

## Paging Research Plan

The verified BM200/BM6 selector is:

```text
d1550500000000010000000000000000
```

The `01` byte is now verified as a cumulative page count. A bounded paging
probe can test higher values after the production import path can safely
preserve raw captures:

```text
d1550500000000020000000000000000
d1550500000000030000000000000000
d1550500000000040000000000000000
```

Expected result:

- selector `01` returns the newest page
- selector `02` returns the newest 2 pages
- selector `03` returns the newest 3 pages
- higher selectors should continue appending older records if the same scheme
  holds

Stop conditions for paging probes:

- stop when a page is empty
- stop when a page fully overlaps imported archive rows
- stop at a configured maximum page count
- stop on repeated protocol errors

Rough selector counts:

| Device | Advertised retention | Records at 2-minute cadence | Planning selector count |
| --- | --- | --- | --- |
| BM200/BM6 | 30 days | 21,600 | 85, using 256 records/page |
| BM300 Pro/BM7 | 72 days | 51,840 | 59, using the observed 883-record selector window |

These counts are planning estimates. BM300 Pro/BM7 record layout is validated
for the newest records from selector `01`, but selector behavior beyond `01`
still needs proof.

## Configuration

Add archive sync settings with conservative defaults:

```toml
[archive_sync]
enabled = true
periodic_interval_seconds = 64800
reconnect_min_gap_seconds = 28800
safety_margin_seconds = 7200
bm200_max_pages_per_sync = 3
bm300_enabled = false
bm300_max_pages_per_sync = 1
```

Meaning:

- `periodic_interval_seconds = 64800`: run periodic BM200/BM6 archive sync when
  the newest archive row is older than 18 hours.
- `reconnect_min_gap_seconds = 28800`: backfill when a device returns after at
  least 8 hours without a successful live row.
- `safety_margin_seconds = 7200`: request a two-hour overlap so page-boundary
  timestamp estimates do not leave small gaps.
- `bm200_max_pages_per_sync = 3`: currently verified safe BM200/BM6 page count.
- `bm300_enabled = false`: keep BM7 automatic archive import opt-in until
  byte-6 page/range behavior is validated beyond selector `01`.
- `bm300_max_pages_per_sync = 1`: bounded BM300 Pro/BM7 selector cap when
  BM300 archive import is enabled. Runtime validation allows up to 59 selectors
  to match the advertised 72-day retention estimate from the observed
  883-record selector window.

## Implementation Tasks

1. Add a BM200/BM6 history parser for `vvv ss tt p`. Done for the verified
   BM200/BM6 record shape.
2. Add archive schema fields for SoC, temperature, raw record, profile,
   selector, record index, and timestamp quality.
3. Implement a BM200/BM6 archive reader for cumulative `d15505` page counts.
   Done for verified page selectors 1 through 3.
4. Implement idempotent archive import with raw-sequence overlap alignment.
   Done for duplicate suppression by `(device_id, ts, profile)`; stronger raw
   sequence alignment remains open.
5. Use the latest successful live row and latest archive row to trigger
   reconnect and periodic bounded sync. Done for BM200/BM6.
6. Keep archive sync failures non-fatal for normal live polling. Done for
   candidate sync; errors are reported in the sync result payload.
7. Add a Settings action for an immediate bounded history import. Done for
   enabled BM200 devices and opted-in BM300 Pro/BM7 devices.
8. Add web or CLI status output showing last archive sync, inserted rows,
   ignored duplicates, and failure reason.
9. Add tests for short absence, long absence beyond 3 pages, repeated imports,
    live/archive overlap, and timestamp alignment.
10. Add a separate bounded paging probe for higher cumulative page counts.
11. Keep BM300 Pro/BM7 automatic archive import disabled by default until
    byte-6 page/range behavior beyond selector `01` is validated.

## Acceptance Criteria

- A BM200/BM6 device that returns after the configured live-row gap triggers a
  bounded archive sync.
- Re-importing the same page does not create duplicate archive rows.
- A visible BM200/BM6 device with no missed polls still syncs at the configured
  periodic interval.
- Charts can show 2-minute archive voltage, SoC, and temperature without losing
  live connectivity rows.
- The implementation clearly reports the configured cumulative page count and
  the fact that full 30-day BM200/BM6 recovery is not yet validated.
- BM300 Pro/BM7 archive sync remains disabled by default but can be enabled
  explicitly with its own page cap.

## References

- [BM Protocol Research Handoff](../2026-04-25-bm-protocol-research-handoff.md)
- [Protocol Probe Tools](../protocol-probe-tools.md)
- [BM6 / BM200 Integration Notes](../2026-04-19-bm6-bm200-integration-notes.md)
- [BM300 Pro / BM7 Integration Notes](../2026-04-25-bm300-bm7-integration-notes.md)
- [ANCEL BM200 product page](https://www.ancel.com/products/ancel-bm200)
- [ANCEL BM300 Pro product page](https://www.ancel.com/es/products/ancel-bm300-pro)
