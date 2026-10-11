# Parquet storage tiers

`sentra tiers-build` derives compact, rebuildable zstd parquet copies of the shared audit
tables. It does not change `audit.*` rows or the original responses in `sentra-originals`.
The tiers exist so that data volume can grow beyond the 400 MB database ceiling. Retention
decisions (for example, removing old minute rows from PostgreSQL) are **not** part of this
change and need a separate, reviewed decision.

| Object in private bucket `sentra-tiers` | Content | Retention |
| --- | --- | --- |
| `hr_raw/<pid>.parquet` | `original_heart-rate` readings: `provider`, `ts` (epoch s), `bpm` (uint16, or float64 if a non-integer value is returned) | Hot: last 30 days, rebuilt each run |
| `hr_minute/<pid>.parquet` | Per-minute heart rate: vendor 60 s rollups (`vendor_60s_rollup`: mean/min/max) and Sentra minutes from raw readings (`sentra_from_raw`: mean/min/max/n). The two are kept as separate rows and never merged. | Warm: all history |
| `measurements.parquet` | Every other measurement: participant, provider, dataset, record key, vendor metric path, `ts`/`end_ts`, civil date, `value` (float64), unit, value kind, availability. `vendor_value` is filled only for non-numeric values such as enums. | All history |
| `sessions.parquet` | `audit.sessions`: type, start/end, score state, provisional | All history |
| `size_report.json` | Bytes and person-days per tier, plus a 10-employee / 30-day projection | Latest run |

Missing values stay null. Nothing is zero-filled, interpolated or deduplicated across
sources. Only identical readings at the same instant collapse to one row in `hr_raw`.
Participants appear only as pseudonymous IDs.

## Guards

- **Read-only role:** reads run as `sentra_viewer` (the reader refuses any other session
  user) inside `READ ONLY` repeatable-read transactions.
- **Egress:** before any rows leave PostgreSQL, the estimated size × 1.2 is reserved through
  `public.sentra_reserve_viewer_egress` on a separate viewer connection, in chunks of 90 MB or less.
  Reservations persist even if the read-only snapshot fails. A stale, missing or
  exhausted budget stops the run. Each run is also capped at `--max-read-mb` (default
  500 MB).
- **Objects:** before uploading, `Limits.check` must accept current object usage plus the
  **full** size of the new tiers. Replaced objects are not netted out. No object may
  exceed the bucket's 50 MB file limit.
- **Writes:** uploads use the collector storage account and go only to `sentra-tiers`.
  `x-upsert` is never sent for `sentra-originals`, so originals stay immutable, and there
  is no delete policy.

## Operator steps

```powershell
.venv/Scripts/python.exe -m pip install "pyarrow>=18"
.venv/Scripts/sentra.exe tiers-migrate
.venv/Scripts/sentra.exe tiers-build --local .private/tiers   # dry run: files only, no object capacity used
.venv/Scripts/sentra.exe tiers-build                           # upload to sentra-tiers
```

`tiers-migrate` applies `sql/006_parquet_tiers.sql` once with the admin credentials and
records it in `collector_private.schema_versions`. `tiers-build` prints the size report.
Use `--employees` and `--days` to change the projection.

## Expected size (synthetic, before the first real run)

The table comes from a synthetic build with these inputs: one Fitbit participant with a
heart-rate reading every 5 s; vendor minute heart rate; four minute rollups and 60 daily
values per participant-day for two participants; and three sessions per day. Random
values compress worse than real heart rate, so treat these figures as an upper-side
estimate. The real per-person-day numbers come from `size_report.json`.

| Tier | Bytes per person-day | 10 employees × 30 days |
| --- | --- | --- |
| hr_raw (30-day hot) | ≈ 41 KB | ≈ 12.3 MB |
| hr_minute | ≈ 31 KB | ≈ 9.3 MB |
| measurements | ≈ 32 KB | ≈ 9.6 MB |
| sessions | < 0.1 KB | < 0.1 MB |
| **Total** | | **≈ 31 MB** |

For comparison, the shared database used 287.56 MB for about 2 participants × 32 days
(≈ 4.5 MB per person-day including indexes). The same 10 × 30 period would need
≈ 1.35 GB in PostgreSQL, which is above the 400 MB ceiling. The tiers would take about
31 MB of the 700 MB object ceiling.
