# Stage 7 — bounded research dataset

## Current decision, 10 October 2026

The human deferred continuous collection and scaling until project use cases are
chosen. Raise the database ceiling to 400 MB, retain the 20 MB reserve (effective
380 MB import guard), and request October 7–9 for both participants using bounded
manual recovery. October 10 is excluded because it is incomplete in Beirut.
Keep GitHub scheduling and the SQL daily control paused throughout and afterward.
Retain existing history and source responses; no resolution increase or storage
migration. Requested coverage does not prove uninterrupted measurements or data
availability for every metric. Record actual completion and capacity below.

### Bounded backfill evidence

Verified at 2026-10-10 12:58:25 UTC (15:58:25 Beirut). Both recovery runs succeeded
with no failures: Google completed 57 jobs (6,789 changed / 3,392 unchanged
records); WHOOP completed 12 jobs (7 changed / 8 unchanged). All 69 requested
October 7–9 jobs have durable complete checkpoints. Existing plus new requested
coverage includes October 3–9 across all collection datasets; Google minute
coverage is October 1–9. Original-resolution HR remains the prior representative
day and was not fetched again.

Some API requests returned no records. Examples include Google sleep, HRV,
respiratory rate and sleep temperature on October 9; oxygen saturation and VO2
max returned none across the three days. WHOOP workout returned none on October 9.
These empty responses are retained; no zeros, unsupported labels or sensor
completeness are inferred.

Database use is 287,561,395 bytes, original objects 732,439 bytes. The 400 MB
ceiling / 20 MB reserve is applied in local collector configuration, encrypted
cloud setup and the GitHub collector-config secret; other limits and token keys
are preserved. SQL control and GitHub scheduling remain disabled. Viewer-role
reads see all 69 new response manifests. Local viewer settings/defaults accept
400 MB, but the hosted viewer's capacity display still has its older setting
until separate code/settings publication. The user subsequently approved the
Sprint 5 closeout commit and merge into `main`, including these settings, control
changes and documentation. That publication does not activate collection.

Verification: 117 automated tests ran successfully (five opt-in integration
checks skipped); the revised exact batch boundary check also passed. Private
metadata evidence is retained in ignored `.private/backfill-verify.json`.

## Earlier decision (superseded)

Decision updated on 10 October 2026: the human replaced the formal three-day
audit with their own ongoing observation, and authorized once-daily collection
at **00:00 Asia/Beirut**. No formal elapsed-day acceptance requirement applies
and there is no wait before the approved viewer redesign. This is not a retention policy.

## Collection boundaries

- Publish the reviewed ongoing/pause control only after explicit approval of the
  completed revision. Approval to begin does not approve an unseen commit.
- Recheck Free plan, GitHub account-wide $0/Stop usage, organization egress,
  database/object capacity and credential gates before enabling. Record actual
  activation timestamps in UTC/Beirut and the first successful approved run.
- Keep the midnight schedule, per-dataset missed-interval recovery, previous-three-day
  correction rechecks, provider isolation and token/writer locks.
- No polling, webhooks, extra history import, resolution increases or paid services.
- Ongoing mode has an explicit start and no end. Quota/auth stops still apply.
  Pause in both GitHub and SQL. Legacy bounded three-day windows remain supported.
- Retain all history, fields and unchanged originals. Presentation changes save no
  PostgreSQL space. Review reversible lossless storage changes separately.

## Capacity and evidence

The 10 October read measured 269,145,779 database bytes and 657,222 original-object
bytes, against effective 330 MB database / 680 MB object guards. Minute-data growth
remains approximately 17.32 MB per requested day plus other datasets. Remaining
headroom does not support indefinite collection at this representation. Stop
safely; never delete history or auto-upgrade.

The team can inspect retained history and new arrivals in the private viewer.
Track returned/missing/unscored/provisional/failed/unsupported-with-evidence states,
definitions/units, requested versus observed resolution, corrections, delivery
timing, capacity and candidate project questions. Two different devices and sparse
samples cannot establish population accuracy, health predictions or causation.

**Status:** local implementation prepared for review; collection remains paused pending reviewed
publication and fresh operational gates. No formal observation period or completed
longitudinal findings are claimed. See [revision evidence](viewer-redesign-validation.md).
