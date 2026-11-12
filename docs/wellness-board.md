# Wellness board

The wellness board is the team dashboard (latest-day cards, wellness level by day, trends
against each person's own normal, device coverage). It runs online with no laptop involved:

```
GitHub Actions collect.yml (00:00 Beirut)  ->  Supabase audit tables
GitHub Actions wellness.yml (01:30 Beirut) ->  sentra-tiers: parquet tiers + board/board.json
Streamlit viewer "Wellness board" page      ->  reads board/board.json, renders src/sentra/board/board.html
```

- **Page:** `src/sentra/board/board.html`, the original board design. Data is embedded
  server-side as JSON; the page makes no data requests of its own.
- **Payload:** `src/sentra/processing/board.py` builds it from `daily_features`.
  - Pseudonymous IDs only (`p01` …) plus the device family.
  - Days without usable data are omitted, so they show as "no data".
  - Missing values are left out, never zero.
  - Comparisons use each day's processing baseline from the preceding 28 calendar days.
    A missing baseline leaves the comparison empty; current and future days never substitute for it.
- **Refresh job:** `python -m sentra.wellness_refresh`, run daily by
  `.github/workflows/wellness.yml`.
  1. Checks finished `audit.collection_runs` against durable record-write timestamps,
     including partial runs whose counters omit already committed pages.
     Paused and unchanged attempts do not advance the watermark. Without new changes,
     only metadata and the previous board are checked; tier reads and publication are skipped,
     **unless** the previous board was built under a different `assessment_version` or
     `board_version` (or none). Then it is rebuilt from the existing data, so new assessment
     rules or board meaning (for example single-provider device labels, #45) apply without
     restarting collection.
  2. Otherwise it rebuilds the tiers and runs processing **before publishing anything**.
     A processing failure leaves the previous tiers and board unchanged.
  3. It then publishes the tiers into the unused slot (see
     [parquet-tiers.md](parquet-tiers.md)), switches `size_report.json`, and uploads
     `sentra-tiers/board/board.json` last. If the board upload fails, the previous board
     stays published and the next run rebuilds it, because the board's `source_run` is older
     than the newest collection.
- **Viewer:** the **Wellness board** page. It is available only after the existing Google
  sign-in and approved-email check, and it is cleared on sign-out like other private
  state.

All outputs are wellness indicators, not medical assessments. Thresholds stay
**v0 — pending medical expert sign-off**, and the board stays internal to the team until
then.

## Publication consistency (#48)

What a refresh guarantees, and the synthetic test that checks it
(`tests/test_wellness_board.py::PublicationConsistencyTests`). The test runs the real slot
publisher, `fetch` and `refresh` against an in-memory bucket.

| Situation | Published result |
| --- | --- |
| Repeated run, no new collection | Skipped: no tier read, no write, bucket unchanged |
| Processing fails | Nothing published; previous tiers and board stay |
| Tier upload interrupted part-way | `size_report.json` still names the previous slot; readers and the board keep the previous complete set |
| Tiers switch, board upload fails | Board keeps its previous complete version; the next run sees an older `source_run` and rebuilds it |
| Corrected reading (same record, new value, newer collection run) | The next run republishes it; tiers and board both show the corrected value, and the run after that skips |

Corrections reach Sentra because the collector rechecks recent days. For a changed record,
`put_records` replaces the record and its measurements under the same record key, and updates
the record's `collected_at`. That moves the durable-write watermark, and the full rebuild
picks up the corrected reading. The original responses in `sentra-originals` are never
rewritten.

Limitations:

- Each refresh with new data rebuilds every tier in full. Incremental monthly partitions
  are phase 4 of [storage-plan.md](storage-plan.md) and depend on the compact storage
  work (#46).
- Publication is ordered (tiers, then report, then board) but not one atomic step. Between a
  tier switch and a failed board upload, the tiers can be one run newer than the board until
  the next run.
- The workflow's `sentra-wellness` concurrency group serializes scheduled and manual
  refreshes. A manual `sentra tiers-build` upload is outside that group: run it only while no
  refresh is running, or two writers can share the unused slot. `fetch` then refuses the
  mixed set ("Tiers kept changing…") until the next complete publication.
- Not yet exercised against the shared bucket: collection and the daily refresh stay paused.

## Data used

| Board field | Source |
| --- | --- |
| Sleep, deep/REM minutes | Complete Fitbit vendor totals take precedence over stage-derived duration; stage summaries and WHOOP stage totals |
| Sleeping HR (Fitbit) | Minute heart-rate rollups during asleep stages |
| Resting HR, HRV, breathing rate, skin temperature | Daily vendor values (Fitbit) and recovery/sleep scores (WHOOP) |
| Steps, wear time | Fitbit minute rollups |
| WHOOP recovery, strain, SpO2 | WHOOP recovery and cycle |
| Wellness level and signals | `processing/pipeline.py` flags against the 28-day personal baseline |

Every field above comes from data the collector already requests.

**Not pulled: original-resolution heart rate.** It is only one representative day.
Second-by-second heart rate would cost far more database space than the 400 MB ceiling
allows, and the board only needs minute heart rate.

## Turning it on (repository owner)

1. **Secret `SENTRA_VIEWER_CONFIG`:** a single-line JSON with the viewer-only database and
   storage credentials (same fields as the processing job's `SENTRA_PROCESSING_CONFIG`).
   The workflow also reuses `SENTRA_COLLECTOR_CONFIG`, but only its storage account,
   to write into `sentra-tiers`.
2. **First run:** Actions → **Wellness board refresh** → Run workflow with `force`. Check
   the log line `Board published: …`.
3. **Daily schedule:** set the repository variable `SENTRA_WELLNESS_ENABLED=true`.
4. **Daily data:** the board only gets new days when daily collection runs. Collection is
   a separate team decision with its own controls (`SENTRA_COLLECTION_ENABLED` and the
   database daily-collection control). See the capacity notes below before enabling it.

## Capacity

- **Database:** the board itself adds nothing.
- **Objects:** the tiers are about 3–4 MB and `board.json` is under 1 MB; both are
  replaced on each run.
- **Egress:** each refresh after new collection reads about 40 MB from the database (the
  full tier rebuild). Daily, that is about 1.2 GB per month of the 3.5 GB monthly
  budget. When collection is paused, a run reads only a few kilobytes.
- **Daily collection itself:** about 4.5 MB of database per participant-day. With about
  70 MB left before the 380 MB import stop, two participants fill it in roughly a week.
  Continuous daily updates therefore need a storage reduction step first: moving
  minute-level rows to the tiers, or retention in PostgreSQL. That is a reviewed
  follow-up, not part of this change.
