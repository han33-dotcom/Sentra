# Stage 6 — end-to-end validation and handover

Started with explicit approval on 9 October 2026, on `ETL-pipeline` after the
approved Stage 5 documentation commit/push `ea583b5`.
**Stage 6 completed on 10 October 2026**, after the user confirmed both selected
participant-app values match. No Stage 7 observation/daily collection was enabled.

Use the [operating guide](operating-guide.md) for setup, runs, reconnects,
downloads, failure interpretation, capacity and backup recovery. Implementation
is unchanged; one synthetic autumn-DST regression test extends existing coverage.
The [execution ledger](stage-6-plan.md) records the checks and decisions.

## Validation evidence

| Required area | Evidence | Practical limit |
| --- | --- | --- |
| Pagination/completeness | Synthetic complete, empty, looping/malformed/expired-cursor and failed-page tests; durable-page resume and unchanged original bytes. | Complete returned pages do not prove every physical measurement exists. Real full-history import evidence is Stage 2, not a new unlimited import. |
| Duplicates/corrections | Live synthetic SQL checks for corrected values, removed fields, provenance-only no-ops and atomic rollback; real bounded rechecks below left record hashes/counts unchanged. | No real vendor correction was deliberately induced. |
| Renewal/reconnect | Both real expired access tokens renewed; cloud versions 4 → 6 and active state persisted. Synthetic ambiguous renewal, expiry, rotation persistence, concurrency and interrupted handoff/reconnect checks passed. | No real participant authorization was revoked to create a failure. Google Testing deadline remains approximately 15 October 2026, 07:05 UTC; reconnect is an operating dependency. |
| Partial failure/missed day | Synthetic provider isolation, per-dataset coverage, failed-page restart and missed-interval planning; paused real daily run completed with both providers paused. | A dropped scheduled run was not deliberately induced; no midnight observation run has occurred. |
| Timestamp/timezone | Beirut midnight, spring 23-hour day, civil date, interval overlap and exact exports tested. New autumn 25-hour/repeated-hour test agrees between collector and viewer. | Vendor civil dates remain civil; participant-app timezone settings were not independently inspected. |
| App comparison | On 10 October the user reported that both selected Google daily steps and WHOOP sleep performance match the participant apps. | User-reported comparison of two values; exact app display precision/timezone was not recorded, and device accuracy is not established. |
| Privacy/downloads | Actual viewer login denied writes, credential/control reads, escalation and Storage writes; anonymous original access denied. Stage 5 hosted owner sign-in and saved files matched selected data/original hash. Synthetic unlisted/expired/unverified users read nothing. | Real unlisted-account OIDC denial was local; anonymous protected-frame denial was hosted. Invitation email receipt was not verified. |
| Storage/zero spending | Current usage/growth measured, safe quota tests passed; GitHub Actions $0 budget / Stop usage Yes rechecked in signed-in browser. Repository remains private and collection disabled. | Supabase Free was verified 8 October; a new dashboard check needs a signed-in session. External organization clients are not metered by Sentra. |
| Backup/restoration | Current encrypted selected backup restored/count- and content-verified in private schema, viewer access denied; transaction rollback removed rehearsal schema. Corruption/incomplete inventory/populated-target refusal tested. | Selected health-only backup; no full replacement-project disaster recovery or real off-machine OS-key recovery. |

## Real bounded requests, 9 October

Fresh environment-based collector processes requested only 7 October (end exclusive
8 October), using existing consented participants and cloud-owned credentials:

| Provider/dataset | Actual collection time, UTC | Result |
| --- | --- | --- |
| Google Health / daily_steps | 18:15:23–18:15:29 | One dataset complete, one unchanged record, zero changed |
| WHOOP / sleep | 18:15:36–18:15:42 | One dataset complete, one unchanged record, zero changed |
| Daily while paused / both providers | 18:15:48–18:15:50 | Both paused, zero completed datasets; no wearable fetch |

Cloud tokens were initially expired and both renewed during these bounded requests.
Stored records remained **61,656 Google / 137 WHOOP**. Ordered record-key/content-hash
aggregates matched before/after. No increased history/resolution or duplicate
physical records were introduced. Fresh viewer checks in Stage 5 verified Google
9-field CSV/original and WHOOP 26-field sleep CSV bytes; selected backend integrity
and source checks were also run. This is not a claim that every Google minute or
daily-health endpoint was re-fetched during Stage 6.

## Capacity and restoration

Measured before backup/final tests: database **269,096,627 bytes**, private original
objects **657,222 bytes**, conservative reserved egress **1,921,399,276 bytes**.
Later verification reserves additional egress. The effective import guard is
330,000,000 database bytes before next-batch estimates; about 60.9 MB remains.
Initial mean estimates are about 17.32 MB/day Google minutes, 0.33 MB/day Google
daily/session data and 0.083 MB/day WHOOP. Three additional days estimate about
322.3 MB total, before correction, recheck, index/bloat and validation overhead.
These are initial-import averages, not observed future growth; a safe stop may
occur before the three-day audit finishes. No threshold was increased.

After backup/final live checks, measured database usage was **269,145,779 bytes**,
originals **657,222 bytes**, and conservative reserved egress **1,949,910,810 bytes**.
Verification did not add health records or original objects. Subsequent viewer
and verification reads consume further egress allowance.

Current small backup contained one participant, 25 daily-step records, 225 scalar
fields, 17 source manifests, nine unique originals, 13 run rows and one connection
state; no sessions for this selection. Its 15 encrypted members were read and
verified. Actual restore SQL validated counts/fingerprints/original hashes, denied
viewer schema access, then an enclosing transaction rolled back the isolated
schema. Existing operational data was preserved. The encrypted backup remains
ignored under `.private/backups`; no health values or backup files are committed.

## Participant-app comparison and remaining limits

The user was asked to compare Fitbit/Google Health daily steps for 7 October and
WHOOP Sleep Performance for the sleep session identified by the private worksheet.
On 10 October they confirmed: **both match**. This is participant-reported evidence;
the assistant did not inspect the mobile apps. No discrepancy was reported.
App timezone settings, exact displayed precision and the actual check time were
not supplied. The ignored `.private/stage-6-app-comparison.json` retains API values,
selected dates/intervals, source references and the reported outcome. No app values
or timestamps were invented, and no health values are published here.

All required Stage 6 areas have validation evidence, with practical limits stated
above. Full replacement-project disaster recovery, off-machine key recovery and
a real hosted unlisted-account login remain unverified. No observation findings
or health accuracy claims are made. Stage 6 changes await commit/push approval.
Stage 7 requires separate explicit approval and capacity/billing checks; it will
observe normal once-daily behavior for three days and report preliminary findings.
