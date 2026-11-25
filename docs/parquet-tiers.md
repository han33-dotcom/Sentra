# Parquet storage tiers

`sentra tiers-build` derives compact, rebuildable zstd parquet copies of the shared audit
tables. It does not change `audit.*` rows or the original responses in `sentra-originals`.
Measurement tiers also read the lossless compact copy (`audit.series_rows`, sql/009) for any
dense reading whose per-field row was removed, so they do not change when those rows are
([storage-plan.md](storage-plan.md#implementation-status-46)).
The tiers exist so that data volume can grow beyond the 400 MB database ceiling. Retention
decisions (for example, removing old minute rows from PostgreSQL) are **not** part of this
change and need a separate, reviewed decision.

| Object in private bucket `sentra-tiers` | Content | Retention |
| --- | --- | --- |
| `hr_raw/<pid>.parquet` | `original_heart-rate` readings: `provider`, `ts` (epoch s), `bpm` (uint16, or float64 if a non-integer value is returned) | Hot: last 30 days, rebuilt each run |
| `hr_minute/<pid>.parquet` | Per-minute heart rate: vendor 60 s rollups (`vendor_60s_rollup`: mean/min/max) and Sentra minutes from raw readings (`sentra_from_raw`: mean/min/max/n). The two are kept as separate rows and never merged. | Warm: all history |
| `measurements.parquet` | Every other measurement: participant, provider, dataset, record key, vendor metric path, `ts`/`end_ts`, civil date, `value` (float64), unit, value kind, availability. `vendor_value` is filled only for non-numeric values such as enums. | All history |
| `sessions.parquet` | `audit.sessions`: type, start/end, score state, provisional | All history |
| `size_report.json` | Bytes and person-days per tier, plus a 10-employee / 30-day projection; versioned object hashes/locations identify the complete monthly set | Latest run |

The table describes the processor's local compatibility layout. New publications use
`monthly-v1`: logical names `months/YYYY-MM/<tier-or-person>.parquet` map to immutable
`monthly/<sha256>.parquet` objects in the private bucket. Undated observations have
an explicit `undated` partition. `fetch()` verifies the complete manifest and object
hashes, then materializes the established layout locally for processing.

Each refresh computes bounded per-tier/month row counts and two-half row-hash sums
inside one read-only repeatable-read database snapshot. Within a changed month the builder compares fingerprints for measurements, sessions and the two heart-rate inputs together. It reads changed groups and reuses verified unchanged groups from the compact private cache.
Corrections, omissions and moves between months invalidate their old/new partitions,
including old history outside the collector's ordinary correction window. No
three-day cutoff is used to decide that an archive can never change. A layout-version
change or `--full` forces a complete source rebuild. Hot raw data ages out of current
publication without rereading historical raw samples; warm minute archives remain.

Only new object hashes are uploaded. The complete `size_report.json` is replaced
last, so an interrupted upload leaves the previous complete publication readable.
A shared PostgreSQL advisory lock serializes both command-line and wellness writers.
The source inventory is capped at 1,200 partitions, the downloaded/derived cache at
500 MB, and each object at the existing 50 MB bucket limit. Database reads retain
the per-run and monthly egress guards. A capacity check before any write covers all
new objects, the report and the pending board together.

Old root and alternating-slot publications remain readable; their first incremental
refresh rebuilds all source partitions. Old slots and unreferenced immutable objects
are not automatically deleted. Their actual storage continues to count against the
guard; cleanup requires a separately reviewed retention operation. Historical raw
objects may therefore remain until that operation even after leaving the hot view.
Digest scans still inspect source rows on the database, and processing still reads
the complete compact cache. This reduces database transfer and uploads, not all
server work. The November stored-data refresh has [measured transfer costs](sprint-closeout.md). Recurring costs for ten participants remain unmeasured.

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
  size of every new content-addressed object plus publication metadata. Existing obsolete objects are not netted out. No object may
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
Use `--employees` and `--days` to change the projection, or `--full` to rebuild every source partition.

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
