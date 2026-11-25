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
- **Refresh job:** `python -m sentra.wellness_refresh`, available through
  `.github/workflows/wellness.yml`.
  1. Checks finished `audit.collection_runs` against durable record-write timestamps,
     including partial runs whose counters omit already committed pages.
     Paused and unchanged attempts do not advance the watermark. The incremental path
     also compares complete monthly source fingerprints, so old corrections and
     omissions cannot hide behind an unchanged run timestamp. Unchanged source and
     current board/rules skip processing and publication after cache verification.
  2. It rebuilds changed input groups within each month, reuses verified unchanged groups, materializes the compact cache and
     runs processing **before publishing anything**. Processing failure retains the
     previous tiers and board. Changed assessment/board versions rerun processing;
     changed tier layout versions rebuild source partitions too.
  3. It uploads new immutable monthly objects, switches the complete tier manifest,
     then uploads `sentra-tiers/board/board.json`. The board records the corresponding
     tier hashes. A failed board upload retains the old board; the hash mismatch
     forces the next run to retry even if the collection watermark did not change.
  4. With sql/014 installed, the existing collector database role publishes only bounded
     eligibility metadata for enrollment after board success. The original read-only
     viewer role still performs health reads. A failed feed update reports that the
     board was published; the next unchanged refresh repairs the feed from that board.
     No data or assessment thresholds are changed and no collection control is enabled.
- **Viewer:** the **Wellness board** page. It is available only after the existing Google
  sign-in and approved-email check, and it is cleared on sign-out like other private
  state.

All outputs are wellness indicators, not medical assessments. Thresholds stay
**v0 — pending medical expert sign-off**, and the board stays internal to the team until
then.

## Publication consistency (#48)

What a refresh guarantees, and the synthetic test that checks it
(`tests/test_wellness_board.py::PublicationConsistencyTests`, `tests/test_monthly_tiers.py`
and the real PostgreSQL monthly-correction case in `tests/test_compaction_db.py`). The test runs the real slot
publisher, `fetch` and `refresh` against an in-memory bucket.

| Situation | Published result |
| --- | --- |
| Repeated run, no new collection | Source fingerprints and compact cache verified; no database partition reads or writes |
| Processing fails | Nothing published; previous tiers and board stay |
| Tier upload interrupted part-way | `size_report.json` still names the previous complete objects; readers and the board keep the previous complete set |
| Tiers switch, board upload fails | Board keeps its previous complete version; the next run sees different tier hashes and rebuilds it |
| Corrected reading (same record, new value, newer collection run) | The next run republishes it; tiers and board both show the corrected value, and the run after that skips |

Corrections reach Sentra because the collector rechecks recent days. For a changed record,
`put_records` replaces the record and its measurements under the same record key, and updates
the record's `collected_at`. Monthly source fingerprints detect the changed contents, and the affected partitions
are rebuilt even for older corrections. The original responses in `sentra-originals` are never
rewritten.

Limitations:

- Monthly fingerprint scans still inspect source rows server-side. Complete compact
  cache download and processing remain bounded but are not incremental processing.
- Publication is ordered (tiers, then report, then board) but not one atomic step. Between a
  tier switch and a failed board upload, the tiers can be one run newer than the board until
  the next run.
- Scheduled/manual refreshes and `tiers-build` share a database publication lock.
  Obsolete immutable objects remain until a separately reviewed cleanup; their
  storage is included in capacity checks.
- The November 26 stored-data refresh published and verified the dashboard. The daily schedule remains paused. [November sprint closeout](sprint-closeout.md)

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

## Controls for a separately authorized refresh

For a capped run on stored data, use the [resumable refresh procedure](operating-guide.md#resuming-a-local-stored-data-refresh). The controls below describe the hosted workflow.

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

Budget for reading changed data, processing the compact files, publication and verification. A stopped attempt still uses its reservations. The November stopped attempts and sizing reserved 99.50 MB. The successful retry and verification reserved another 64.60 MB. Estimate and cap each future run against the shared 4.5 GB monthly stop. [Measured transfer and limitations](sprint-closeout.md)
