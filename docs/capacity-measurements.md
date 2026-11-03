# Capacity measurements and growth forecast (#50)

Status: **measurement log started.** The recommendation for the next participant batch is the
later deliverable. It needs several days of observed collection after restart (#47).
Projections stay labelled as projections until measured.

## What is measured, and how

| Question | Command / source | Notes |
| --- | --- | --- |
| Database, objects, egress now | `sentra shared-measure` | Appends one aggregate snapshot to the ignored `.private/measurements/capacity.jsonl` and prints growth per day between the first and latest snapshot |
| Per-table size | same snapshot (`audit_table_bytes`) | includes indexes |
| Collection success | same snapshot (`runs`: status counts per participant/provider over the last 14 days) | `succeeded`, `paused`, `skipped`, `failed`, `capacity_stop` |
| Initial import cost per dataset | `sentra shared-growth` | initial-import averages, kept separate from ongoing growth |
| Usable coverage | processing outputs: `assessment_state` and `usable_day` ([indicator-contract.md](indicator-contract.md)) | registrations, connections, usable days and baseline readiness are counted separately |
| Refresh cost | `size_report.json` `read_bytes` and object sizes per tier build | one per refresh |
| Compaction saving | `sentra shared-compact-verify …` | measured series vs. measurement rows ([storage-plan.md](storage-plan.md#implementation-status-46)) |

Snapshots contain counts, sizes and run outcomes per pseudonym only, never readings. The log
stays beneath `.private` and is not committed. Copy only the aggregate numbers into this file
or the task.

**Cadence while collection runs:** one `shared-measure` per day after the collection window,
plus one before and after each compaction batch, backup and refresh. Egress budgets reset
monthly, so compare egress only within a month.

## Baseline (before restart)

| Date | Measure | Value | Source |
| --- | --- | --- | --- |
| 11 Oct 2026 | Database used | 310.2 MB of the 400 MB guard | storage-plan.md |
| 11 Oct 2026 | Egress month-to-date | 2.52 GB of the 3.5 GB guard | storage-plan.md |
| 11 Oct 2026 | Objects | 4.0 MB | storage-plan.md |
| 9 Oct 2026 probe | `activity-level` | ≈ 22.9 MB per participant-day | data-dictionary.md |
| 3 Nov 2026 | Lossless compaction of dense minute rows | 6.8× smaller with indexes (real steps, 65 days, local PostgreSQL) | storage-plan.md |
| 3 Nov 2026 | Assessment coverage on real history (4 participants, 161 usable days) | 132 complete, 29 partial; 25 former "green" days lacked inputs or baseline | PR for #45 |
| 14 Oct 2026 | Archive tier per person-day (older pipeline, 4 people) | raw HR ≈ 77 KB, minute HR ≈ 9 KB, measurements and sessions ≈ 2 KB | local size report |

These numbers are older than the current code or come from local data. They are the
starting point, not a forecast.

## To fill after restart

| Measure | Day 1 | Day 7 | Day 14 |
| --- | --- | --- | --- |
| Database bytes per participant-day (ongoing) | | | |
| Egress per day (collection + refresh + viewer) | | | |
| Runs succeeded / failed / paused | | | |
| Usable days and complete assessments per participant | | | |
| Refresh `read_bytes` | | | |

## Recommendation (pending)

A measured recommendation for the next batch will state participants per device mix, the
headroom left under each guard, and the assumptions it depends on. Around 100 participants
remains a direction, not a commitment.
