# Storage and Supabase usage plan

The project uses Supabase Pro with a 4.5 GB internal monthly transfer stop and no additional spend. One separately approved removal reconstructed all 774 readings and preserved the original response. Each future removal requires its own preview, recovery evidence and approvals. [Bounded removal](https://github.com/han33-dotcom/Sentra/issues/46#issuecomment-6992737541) · [November sprint closeout](sprint-closeout.md)

## Why

The following October sizing proposal records the plan, limits and usage at that time.

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
4. **Incremental, partitioned tiers.** Implemented as versioned monthly logical
   partitions backed by immutable content-addressed objects. Full source fingerprints
   invalidate any corrected, moved or omitted month, including older history; a
   three-day archive cutoff is unsafe. Only changed database partitions are read and
   new object hashes uploaded. See [tier publication](parquet-tiers.md) for bounds,
   compatibility, retry, hot expiry and the remaining cache/cleanup limitations.
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

- **Attribute reservations.** `sql/013_egress_purpose.sql` records collector, viewer,
  tiers, backup, verify, processing, enrollment, followups and operations reservations.
  `shared-status` includes `egress_reserved_by_purpose`. These are conservative reserved
  allowances, not measured network traffic. The pre-migration reserved total remains
  `prior_unattributed`; the dashboard baseline stays separate. Nothing resets the ledger
  or changes ceilings, freshness, independent viewer reservations or retry accounting.
  Old clients retain their two-argument functions; updated clients fall back only when
  the new function is absent, never after a failed reservation. Apply after 005; no
  collection authorization is implied.
- **Incremental tiers** (step 4), and a refresh only after a new collection run
  (already in place).
- **Board instead of database queries.** The board reads one JSON file of about 1 MB or
  less. Heavy viewer audit queries stay opt-in.
- **Fewer full backups.** Run full encrypted backups weekly, not per change, and
  `shared-verify --originals` monthly. Both download everything.
- **Keep current safeguards.** The approved 4.5 GB stop and the weekly baseline refresh stay
  as they are.

## Implementation status (#46)

Phases 1 (table) and 2 (build and lossless verification) are implemented in
`sql/009_compact_series.sql` and `src/sentra/compaction.py`. **Nothing deletes measurement
rows.**

- `audit.series` holds one row per participant, provider, dense dataset, metric and original
  response. Fields shared by every reading are stored once. Per-reading fields (record key,
  value, vendor value, times, civil date, vendor time, collected-at, source pointer) are
  parallel arrays, so every column of every row is kept.
- `audit.series_rows` re-expands it column for column like `audit.measurements`.
- `sentra shared-compact --participant p01 --provider google_health --dataset minute_steps`
  compacts up to 200 pending responses per run in one transaction. Before writing, it asks
  the capacity guard for the worst case (no saving). It then compares the row count and an
  exact per-row fingerprint with the source rows. The fingerprint uses JSON text, so numeric
  scale, nulls, jsonb and timestamps must all match. Any difference rolls the whole batch back.
- `sentra shared-compact-verify …` re-checks everything compacted so far and reports measured
  sizes. A later correction to measurement rows, including a reading that moves to a newer
  original response, shows up as a mismatch. While any copy is mismatched, both commands
  **exit 1**, so a mismatched copy is never taken as lossless evidence.
- `sentra shared-compact --repair …` rebuilds those stale responses from their current rows,
  with the same lock, capacity guard and batch verification. A response with no rows left
  loses its series copy only if no current compact-only reading depends on it. Rebuilds
  refuse to remove the only current projection. Measurement rows are never changed.

**Measured (3 Nov 2026, local throwaway PostgreSQL 16, not Supabase):** 65 days of one
participant's real minute step readings were loaded in the collector's exact row shape:
20,702 rows, 64-character record keys and the vendor time JSON.

| | Measurement rows | Compact series |
| --- | --- | --- |
| Rows | 20,702 | 65 |
| Table with indexes | 16.4 MB | 2.4 MB (**6.8× smaller**) |
| Row data only | 10.8 MB | 2.1 MB (5.1×) |
| Lossless check | — | 65/65 responses, 20,702/20,702 rows, 0 mismatches |

**The saving is about 7×, not the 100× estimated above.** Keeping the full per-reading
context (vendor time JSON, hash record keys, source pointers) is what makes it lossless. The
remaining bulk is that context, and it can be re-derived from the hash-verified originals in
`sentra-originals`. Going further therefore needs a team decision on whether to keep that
context only in the originals. Separately, the dense `audit.records` rows (one per minute,
with normalized JSON) are not compacted yet and must be measured on Supabase before phase 3
is sized.

**Tiers read the compact copy (phase 1).** Where `sql/009` is installed, each measurement tier
reads `audit.measurements` plus the `audit.series_rows` readings that meet two conditions:
their per-field row no longer exists, **and** their record in `audit.records` still names the
same original response. Nothing is read twice, and a per-field row always wins, including a
later correction not yet repaired in the compact copy. A newer response that omits a reading
replaces the record and drops that reading's per-field row. Its obsolete compact copy is then
never published.

**Phase 3 must therefore keep `audit.records`.** A record's `source_response_id` is the
proof that a compact reading is still current. If records are ever compacted or removed
too, an equivalent marker must be kept first. Published tiers, and therefore the board, stay the same
when verified per-field dense rows are removed. The opt-in PostgreSQL tests in
`tests/test_compaction_db.py` cover three cases: removal, a later correction, and a reading
omitted by a newer response, written through the collector's `put_records`. Without `sql/009`, tiers read
`audit.measurements` as before.

Full backups include `audit.series` once sql/009 is installed. It is verified by row count and
fingerprint and restored with its ids, so a verified backup also covers readings kept only in
the compact copy. A restore stops before writing if the target lacks sql/009.

**The private viewer uses the same current-reading rule.** Its dataset catalog, metric
discovery, filtered measurements and full-record selection include compact-only readings
when 009 is installed, with per-field corrections taking precedence and the current record
response required. Without 009 it uses the original per-field queries. Expanded selections
retain the existing row/byte limits, access checks, snapshot and egress reservations.

**Compact collector writes are opt-in (sql/012).** Apply after 008 and 009. The migration
creates `collector_private.compact_control` with `enabled=false`; collector/viewer/enrollment
roles cannot change the switch. With it disabled or absent, the existing write path remains.
With it enabled, each bounded dense input batch writes exact parallel arrays. Retries,
corrections and omissions replace only those record keys transactionally; sparse datasets
keep per-field rows. All `audit.records` and original responses remain. Counts, growth,
capacity snapshots, projection verification and enrollment recency read current logical
measurements. The enrollment role still receives only its bounded metadata summary.

Roll out while collection is paused: finish the additive copy/verification first, retain
its evidence, deploy compatible readers/writers, and apply 012. Enable the switch only as
part of the coordinated storage rollout; it does not authorize restarting collection or
bulk phase-3 deletion. After compact writes begin, use `shared-verify` for record/projection
checks. Additive `shared-compact`/`--repair` refuses while the switch is enabled, and refuses
rebuilding any response with current compact-only readings even after disabling it. Turning
the switch off restores per-field writes for future corrections; it does not erase arrays.
Full backups cover compact data; operational controls remain separately configured on
recovery, with 012 defaulting off. Synthetic PostgreSQL tests compare all 22 columns and
exercise role permissions, retries, correction/omission, rollback and capacity rejection.

At this checkpoint, the following items were open before phase 3:
- Egress purpose attribution is implemented by sql/013 and compatible clients; apply the migration to begin the breakdown.
- Phase 3 deletion stays gated as below.

## Phases and approvals

| Phase | Change | Deletes data? | Approval |
| --- | --- | --- | --- |
| 1 | `audit.series` table + collector writes dense datasets there + viewer/tiers read it; egress `purpose` | No | Implementation-agent self-review + CI |
| 2 | Migration builds series from existing dense rows + lossless verification report | No | Implementation-agent self-review + CI |
| 3 | Delete verified per-field dense rows + `VACUUM FULL` | **Yes** (originals and series keep the data) | Both owners, recorded in the PR, collection paused |
| 4 | Monthly partitioned, incremental tiers | No | Implementation-agent self-review + CI |
| 5 | Re-enable daily collection and the daily board | No | Team decision |

Until phase 3 is done, `activity-level` stays on request and daily collection stays
paused.

## Bounded phase-3 removal command

`shared-removal-preview` and `shared-removal-apply` use the existing private operator
configuration. They lock the collector and affected tables; the operator connection
is needed to lock the admin-only compact-write control without expanding runtime
roles. Collection must be explicitly paused and compact writes still disabled.
No command in this flow enables either control.

1. Complete and verify a full encrypted backup, including compact series and all
   installed private tables, after recording the paused control state. Recover it
   into an isolated target and verify original objects and table counts. The backup
   must be less than 24 hours old. Preserve the exact encrypted manifest.
2. Create a private preview, for example:
   `sentra shared-removal-preview --participant p01 --provider google_health --dataset minute_steps --limit 20 --output .private/operations/removal-plan.json`.
   Each plan covers at most 200 original responses, 100,000 rows and 32 MB of row
   payload. It expires after 24 hours. The preview selects responses that have
   both copies, checks all 22 logical columns against the current compact rows,
   and records the paused-control timestamp.
3. Save private recovery evidence as JSON with `status: restored_and_verified`,
   `backup_manifest_sha256` (the encrypted manifest's SHA-256),
   `source_project_url`, `target_project_url`, `isolation_verified: true`, `counts`
   (the complete offline verification table-count mapping), `originals_verified`
   (verified object count), and `retention_decision_url` (the recorded Sentra issue
   or PR decision). These are attestations from the actual recovery run, not a
   substitute for performing it. Include any additional dated recovery evidence;
   the complete JSON is bound to the owners' approval.
4. Both designated owners, `han33-dotcom` and `MohamadNasrallah`, review the actual
   backup/recovery and retention decision. Each posts a separate comment on the
   same Sentra PR with this exact line, using the plan SHA-256 and the canonical
   evidence digest (`sentra.compact_removal.digest(evidence)`):
   `APPROVE SENTRA PHASE3 <plan-sha256> EVIDENCE <evidence-sha256>`.
   Agents do not create owner approval comments or substitute their code review.
5. Apply with `sentra shared-removal-apply --plan .private/operations/removal-plan.json
   --backup .private/backups/<backup-id>/manifest.enc --evidence .private/operations/recovery.json
   --approval <first-owner-comment-url> --approval <second-owner-comment-url>`.
   The command fetches and verifies both actual GitHub comments, authenticates the
   backup offline, proves every selected current row is in it, then rechecks the
   paused state, preview fingerprint and lossless compact copy inside one locked
   transaction. Changed data, missing evidence or any mismatch rolls back.

Only the approved duplicate per-field rows are removed. Records, source originals,
sparse data and compact arrays remain. Retrying an already applied plan fails
closed rather than broadening its scope. No `VACUUM` runs automatically: DELETE
alone does not reduce allocated database size. Measure actual post-removal size;
any `VACUUM FULL` requires its separately reviewed operator maintenance window.
Do not publish private plans, backup contents, participant scopes or recovery files.

## November 18 approved backup headroom

The owner authorized raising the internal monthly transfer ceiling from 3.5 GB to
4.5 GB and the private backup-storage ceiling from 200 MB to 500 MB, followed by
one encrypted full backup and offline verification. The provider allowance remains
5 GB on Free, leaving 500 MB outside the internal ceiling. This is not agreement
to retention periods, collection restart, another wellness refresh or deletion.

The bounded aggregate-only preflight estimated 992,779,032 bytes of reservations;
private files occupied approximately 251 MB. Under the proposed ceiling the
estimate left approximately 536 MB of transfer headroom at that instant. Recheck
before execution because viewer/enrollment reads consume the same ledger. These
figures are preflight evidence, not a successful backup.

Rollout order:

1. Release the matching collector, backup, viewer and enrollment code.
2. Apply reviewed migration 015 after 013 and verify that baseline, reserved-byte
   and purpose totals are unchanged. Preserve the seven-day baseline freshness check.
3. Set `shared.monthly_egress_bytes` in the private operator config and
   `viewer.limits.monthly_egress_bytes` in hosted viewer secrets to 4500000000.
   Update private deployment copies consistently. Deploy the enrollment service,
   whose bounded reservations now use the same approved ceiling.
4. Verify collection is paused and check fresh transfer/disk capacity before one
   full backup. The 500 MB backup guard counts the whole private directory as well
   as the current backup; existing files are retained on a stop. Disk-free checks,
   encryption, chunk limits and all remote reservation accounting remain enabled.
5. Verify every backup member offline and record only aggregate coverage, counts,
   fingerprints and the outcome on SEN-29. Keep keys and archive contents private.

The 400 MB database ceiling, 20 MB reserve, 700 MB object ceiling, 100 MB viewer
per-call cap and destructive-storage gates are unchanged. A verified archive still
needs an isolated recovery rehearsal and the decisions listed in the retention policy.

### Rollout and verified backup observed November 18

Implementation PR #114, release #115 (`a6f3061e2c3ffbadc95000a46563d28369e18f8b`)
and ancestry sync #116 passed required CI and merged. Migration 015 preserved all
baseline, reserved-byte and purpose rows. Operator, hosted viewer and paused
collector configuration now use 4.5 GB. Render served `/health` and `/join` with
HTTP 200 after deployment. The rebooted Streamlit app accepted the updated limit
and denied the inactive test identity, which was then signed out. Its platform
used Python 3.11 and replaced pinned PyArrow 25.0.1 with 24.0.0 during deployment;
that platform behavior is separate from repository CI evidence.

The one authorized full backup completed at 23:00:26 UTC on November 17
(November 18 in Beirut), after starting at 22:47:02 UTC. Offline verification
passed for 16 tables, 251,971 rows, 220 original responses and 662 encrypted
members, with empty `not_covered` and `not_installed` lists. The archive occupied
31,798,384 bytes; the private root occupied 282,417,425 bytes. Reservations were
992,910,104 bytes, within the additional 1.1 GB run cap. Manifest SHA-256:
`33569268be28dcb2ec289d1cee05ced2bd0147de9fe6a3929041c0b3907f402e`.
Collection remained paused and no deletion ran. This verifies the supported
archive inventory, not provider-managed backups, retention agreement or recovery.

The isolated recovery preflight estimates 883,232,170 bytes of reservations and
327,713,382 bytes of database growth allowance. A separately configured Free
organization/project is used so its reservations do not compete with the live
organization's remaining headroom. No live ledger is reset. See the
[recovery record](recovery-rehearsal.md) for outcome and remaining scenarios.

The subsequent isolated recovery passed: all 16 tables and all 220 destination
originals matched the source snapshot. Compact arrays reconstructed 774 readings.
Final database usage was 307,066,547 bytes. See the dated recovery record for
reservations, timings, access/allocator checks and unverified scenarios. This
does not authorize duplicate-row deletion or agree the retention proposal.
