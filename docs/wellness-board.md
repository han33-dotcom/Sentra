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
     only metadata and the previous board are checked; tier reads and publication are skipped.
  2. Otherwise it rebuilds the tiers, runs processing and uploads
     `sentra-tiers/board/board.json`.
- **Viewer:** the **Wellness board** page. It is available only after the existing Google
  sign-in and approved-email check, and it is cleared on sign-out like other private
  state.

All outputs are wellness indicators, not medical assessments. Thresholds stay
**v0 — pending medical expert sign-off**, and the board stays internal to the team until
then.

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
