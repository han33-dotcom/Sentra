# Storage and Supabase usage plan

Status: **proposal for review**. Nothing in this document deletes data yet. Every step
that removes rows is gated on verification and explicit approval by both code owners.

## Why

Sentra runs on Supabase Free. Its guards stop collection safely before the free
allowances are reached:

| Resource | Free allowance | Sentra guard | Measured (11 Oct 2026) |
| --- | --- | --- | --- |
| Database | 500 MB | 400 MB (380 MB import stop, 20 MB reserve) | **310.2 MB** |
| Storage objects | 1 GB | 700 MB | 4.0 MB |
| Egress, monthly | 5 GB | 3.5 GB | **2.52 GB** month-to-date |

About 70 MB of database headroom is left. Daily collection would hit the import stop in
about a week, so the wellness board cannot update daily yet.

## Where the database space goes

From the measured growth reports
([stage 3](stage-3-storage.md#import-and-growth-finding),
[stage 6](stage-6-validation.md), [probe](data-dictionary.md#measured-storage-per-dataset)):

| Data | Database cost | Kind |
| --- | --- | --- |
| One representative day of original-resolution heart rate | ≈ 122 MB | dense, one-off |
| Google minute rollups (steps, distance, calories, zone minutes, HR) | ≈ 17.3 MB per participant-day | dense, daily |
| `activity-level` (Oct 9 probe) | ≈ 22.9 MB per participant-day | dense, on request |
| `sedentary-period` | ≈ 0.45 MB per participant-day | medium, daily |
| Google daily and session datasets | ≈ 0.33 MB per participant-day | sparse, daily |
| WHOOP cycles, recovery, sleep, workouts | ≈ 0.08 MB per participant-day | sparse, daily |

Nearly all the space is **dense time series stored one field per row**.
`audit.measurements` keeps each returned scalar as its own row with full context: timing
JSON, resolution text, source pointer and indexes. For a minute rollup that is about
2–3 KB per minute, while the value itself needs a few bytes. The original API responses
are already kept, compressed and hash-verified, in Storage (≈ 4 MB in total). So the
per-row copy is a convenience for querying, not the only record.

## Target design

```
                 dense series (minute_*, original_heart-rate, activity-level)
collector ──►  audit.series           one row per participant/dataset/day, values as arrays
          ──►  audit.records/measurements   sparse daily + session data (unchanged)
          ──►  sentra-originals      unchanged compressed responses (unchanged, lossless source)
tiers job ──►  sentra-tiers          monthly parquet partitions, built incrementally
```

1. **Compact series table.** Add `audit.series` with one row per participant, provider,
   dataset and civil day:
   - sample times as second offsets from the day start;
   - one exact `numeric[]` array per vendor field;
   - the source response IDs.

   Values, units and provenance are kept exactly as returned; only the row layout
   changes. Estimated cost is about 0.1–0.2 MB per participant-day for all minute
   datasets, about **100× smaller** than now.
2. **Collector change.** Dense datasets write `audit.series` instead of per-field
   measurement rows. Sparse datasets keep the current path. The correction rechecks of
   the last three days and the coverage bookkeeping stay the same.
3. **One-time migration of existing dense rows** (this frees about 250 MB):
   1. Build `audit.series` rows from the existing dense measurement rows.
   2. Verify losslessly: re-expand every series and compare value-for-value and
      timestamp-for-timestamp with the original rows, and record the check counts.
   3. Only after verification passes, and after both owners approve, delete the
      migrated per-field rows inside the same guarded migration.
   4. Run `VACUUM FULL` on the two audit tables once. Plain `DELETE` does not shrink
      `pg_database_size`; the admin role runs this during a paused window.
4. **Incremental, partitioned tiers.** Tiers become monthly partitions
   (`measurements/2026-10.parquet`, `hr_minute/p01/2026-10.parquet` …). Each refresh
   rebuilds only the open partitions: the current month, plus the previous month for 3
   days after it ends to catch corrections. A refresh then reads a few MB instead of
   about 40 MB.
5. **Postgres stays the recent working set; parquet holds the long history.** Sparse
   daily and session data stay in Postgres for the project's lifetime (about 0.4 MB
   per participant-day). A retention window for older per-field rows is a later, separate
   decision, needed only beyond about 10 participants or several months.

### Expected effect

| | Today | After steps 1–4 |
| --- | --- | --- |
| Database used | 310 MB | ≈ 60–80 MB |
| Daily growth, 2 participants | ≈ 18 MB | ≈ 1 MB |
| Daily growth, 10 participants | ≈ 90 MB | ≈ 5 MB (headroom ≈ 2 months; then retention or compact daily rows) |
| Tier refresh egress | ≈ 40 MB per run | ≈ 2–5 MB per run |

## Egress plan

Egress is the allowance closest to its limit: 2.52 GB of the 3.5 GB guard by 11 October.

- **Attribute it first.** Add a `purpose` to every egress reservation (collector,
  viewer, tiers, backup, verify), so the monthly spend can be broken down. Today only
  the total is known.
- **Incremental tiers** (step 4), and a refresh only after a new collection run
  (already in place).
- **Board instead of database queries.** The board reads one JSON file of about 1 MB or
  less. Heavy viewer audit queries stay opt-in.
- **Fewer full backups.** Run full encrypted backups weekly, not per change, and
  `shared-verify --originals` monthly. Both download everything.
- **Keep current safeguards.** The 3.5 GB stop and the weekly baseline refresh stay
  as they are.

## Phases and approvals

| Phase | Change | Deletes data? | Approval |
| --- | --- | --- | --- |
| 1 | `audit.series` table + collector writes dense datasets there + viewer/tiers read it; egress `purpose` | No | Normal PR review |
| 2 | Migration builds series from existing dense rows + lossless verification report | No | Normal PR review |
| 3 | Delete verified per-field dense rows + `VACUUM FULL` | **Yes** (originals and series keep the data) | Both owners, recorded in the PR, collection paused |
| 4 | Monthly partitioned, incremental tiers | No | Normal PR review |
| 5 | Re-enable daily collection and the daily board | No | Team decision |

Until phase 3 is done, `activity-level` stays on request and daily collection stays
paused.
