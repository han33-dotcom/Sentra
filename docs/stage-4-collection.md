# Stage 4 — once-daily collection

**Stage 4 acceptance passed on 8 October 2026**, including actual manual GitHub
Actions runs and retries. Commit `9608353` was pushed from `ETL-pipeline` and
published to `main` through [PR #2](https://github.com/han33-dotcom/Sentra/pull/2)
with merge commit `08d27c1`, after explicit user approval. Work continues on the
same `ETL-pipeline` branch. Stage 5 and the three-day observation have not begun.

## What changed

The collector runs in a fresh Python process using encrypted provider credentials
in Supabase and two repository secrets. It streams each unchanged API response
into private compressed Storage, normalizes its records, and checkpoints the
page only after all its record batches are stored. No laptop snapshot is needed.
Separate provider/dataset state determines missing dates. A normal daily run
recovers missing intervals and revisits the previous three Beirut calendar days.
An older-than-30-day gap requires a bounded manual recovery rather than an
unbounded import. Google original-resolution heart rate stays the initial single
representative day; daily minute requests remain vendor 60-second aggregations.

Rechecks compare every preserved vendor field and normalized value, ignoring
fetch-only provenance. Unchanged records keep their existing source references;
the new fetch has its own manifest. Changed responses are retained by content
hash, identical objects are reused, and corrected rows replace their searchable
projections without duplicate metrics. A failed provider does not prevent the
other provider running. Dataset failures leave their own last durable cursor and
coverage; successful datasets can advance independently.

PostgreSQL locks serialize all writers and each provider's refresh operation.
WHOOP replacement refresh tokens are saved before use. Rotation intent is saved
before requesting tokens: an interrupted/ambiguous rotation requires reconnect,
because retrying a possibly invalidated refresh token would be unsafe. Local
copies are marked cloud-owned and cannot refresh, authorize independently, or
overwrite cloud data through `shared-sync`.

Runs record actual start/end times, requested coverage, counts, failures and
storage usage. Request coverage proves that the returned pages were stored; it
does **not** prove every possible measurement is present. Records remain
provisional; passing three days alone does not establish vendor finality. Sleep
still in progress and delayed device syncs arrive in a later eligible run.

## Hosting, schedule and spending

[GitHub supports an IANA timezone on scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule).
The prepared workflow schedules `0 0 * * *`, `timezone: Asia/Beirut`. DST is handled
by GitHub; if a scheduled hour is skipped, execution advances to the next valid
time. [Scheduled runs may be delayed or dropped](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
especially at the start of an hour. Stored coverage recovers missed dates on the
next successful run; midnight execution does not make yesterday's data final.

The workflow uses one standard `ubuntu-24.04` runner, Python 3.11, pinned official
actions, a 45-minute hard job limit and a 15-minute provider processing budget
(bounded in-flight requests may finish afterward). It has read-only repository
permissions, no push/PR triggers, no dependency cache, no data artifacts and no
health values or credentials in its explicit output. Concurrency queues runs
without cancelling an active token rotation. GitHub may replace excess pending
runs; recovery uses stored intervals rather than assuming every trigger executes.

[GitHub Free includes 2,000 standard runner minutes and 500 MB artifact storage](https://docs.github.com/en/billing/reference/product-usage-included).
These allowances are shared with other repositories under the same owner.
[Without a valid payment method, exhausted included usage is blocked](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
If a payment method exists, verify an account-wide Actions **$0 budget** with
[Stop usage when budget limit is reached](https://docs.github.com/en/billing/how-tos/set-up-budgets).
An alert-only budget is insufficient. Do not enable larger runners, paid add-ons
or upgrades. On 8 October, the signed-in billing pages confirmed **GitHub Free**
and an account-wide **Actions $0 budget, Stop usage: Yes**. No budget, payment
method, subscription or billing plan was changed. Publication and manual
acceptance followed explicit approval; scheduled observation remains disabled.

All runner jobs also require `SENTRA_ZERO_SPEND_CONFIRMED=true`. That repository
Actions variable was set true after the account check; this permits manual
acceptance/recovery jobs. The observation schedule remains
disabled. Re-running secret configuration resets both execution gates to false;
reverify billing controls before setting this flag again.

Supabase remains Free. Existing 350 MB database / 700 MB objects / 3.5 GB egress
thresholds and 20 MB import reserve are unchanged. Bounded status writes may use
the reserved database headroom; health imports stop earlier. The verified
organization egress baseline expires after seven days and at a new UTC month.
Reservations are conservative allowances, not billed usage; do not reset them
or treat available free quotas as permission to enlarge the import silently.
See [Stage 3 quota/backup instructions](stage-3-storage.md).

## Setup and current deployment

Migration `sql/004_daily_collection.sql` is deployed: private resumable jobs,
observation control, and a lossless record-comparison function. No existing
records/history were removed. Google `p01` and WHOOP `p02` credentials are handed
over. OAuth client secrets and tokens are encrypted with a **separate cloud key**,
not the OS key that protects local extracts. The viewer has neither key nor
credential-table permission. Repository secrets are configured and verified by
metadata. Current gates: `SENTRA_COLLECTION_ENABLED=false`, `SENTRA_ZERO_SPEND_CONFIRMED=true` after billing verification.

The ignored `.private/cloud/setup.enc` journal holds the cloud configuration/key,
encrypted with the operator's OS key. Back it up securely alongside the existing
key-recovery procedure; never give it to the viewer or commit it. GitHub runtime
secrets contain only the restricted collector database/Storage configuration and
cloud encryption key. They do not contain Supabase admin/service-role credentials,
the local OS key, local health extracts, or viewer credentials.

To reproduce on an already initialized Stage 3 project:

```powershell
.venv/Scripts/sentra.exe cloud-prepare
.venv/Scripts/sentra.exe cloud-connect google_health
.venv/Scripts/sentra.exe cloud-connect whoop
# Operator-only dependency; not installed by the scheduled workflow:
.venv/Scripts/python.exe -m pip install PyNaCl==1.6.2
.venv/Scripts/sentra.exe cloud-github-secrets
```

These commands are resumable and never display credentials. `cloud-prepare`
preserves the existing cloud key and does not reverify/reset the egress baseline.
`cloud-github-secrets` targets this repository (`han33-dotcom/Sentra`) only, checks
that it is private and the existing Git credential has admin access, encrypts
secrets using GitHub's public key, and leaves the schedule disabled. It does not
create a commit, merge, workflow run, branch or paid service.

## Try the result and reconnect

The same environment-only collector runs locally for a bounded acceptance check:

```powershell
.venv/Scripts/sentra.exe cloud-run-local --mode recovery --provider google_health --start 2026-10-07 --end 2026-10-08 --dataset daily_steps
.venv/Scripts/sentra.exe cloud-run-local --mode recovery --provider whoop --start 2026-10-07 --end 2026-10-08
.venv/Scripts/sentra.exe cloud-run-local --mode daily
.venv/Scripts/sentra.exe shared-status
```

The first two requests are already-imported dates; repeats recheck content safely.
The daily command currently records `paused` and makes no wearable request.
Manual `initial` and `recovery` require explicit dates covering 1–30 days, end
exclusive and no later than today in Beirut. `initial` uses the Stage 2 bounded
scope (minute history at most seven days, original HR one day). `recovery` uses
daily collection datasets and excludes original HR. Choose a provider when
filtering a dataset, since Google and WHOOP use different dataset names.

Google Testing authorization can expire after seven days. For an expired,
revoked, interrupted rotation or ambiguous renewal, use:

```powershell
.venv/Scripts/sentra.exe cloud-connect google_health --reauthorize
.venv/Scripts/sentra.exe cloud-connect whoop --reauthorize
```

The affected participant completes the normal browser consent. Reconnect pauses
that connection under the cloud token/writer locks, writes the new credentials,
then resumes cloud ownership. An interrupted reconnect remains blocked; repeat
the same reauthorize command. Other participants need not reconnect. Existing
local `authorize`, `refresh`, `sample` and `initial-import` must not refresh a
cloud-owned copy. Previously created local extracts remain snapshots.

## Publication and manual GitHub runs

[Scheduled workflows run on the default branch, and initial workflow dispatch
requires the workflow there](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).
This repository's default branch is `main`; development stays on `ETL-pipeline`.
The reviewed changes were committed, pushed and merged after explicit approval.
The default branch was not changed; the only workflow is
`.github/workflows/collect.yml`. Future commits/publication still follow the
user's review and approval agreement.

Once published and billing controls are confirmed, open GitHub Actions → Private
wearable collection → Run workflow. Start with `recovery`, explicit dates above,
Google/daily_steps and WHOOP/all in separate manual runs. Repeat and verify stable
record counts and stored source/projection integrity. Also run `daily` while
paused and verify zero collection. Inspect actual execution times and storage
usage in `audit.collection_runs`; Actions logs contain sanitized status/counts.
No downloads are uploaded as artifacts. Ubuntu/GitHub execution is demonstrated
by the successful acceptance runs below. A GitHub retry keeps the execution ID
for checkpoint skips and saves a separate audit row for its attempt number.

## Three-day observation gate

Only after Stages 4–6 and explicit Stage 7 approval, an operator sets the approved
start and enables the GitHub repository variable:

```powershell
.venv/Scripts/sentra.exe cloud-window --start YYYY-MM-DD --approved
```

Set `SENTRA_COLLECTION_ENABLED=true` in repository Actions variables. The SQL
control independently requires exactly three Beirut execution dates, end
exclusive. After that window the collector makes no wearable requests even if
the GitHub variable is still true. Set the variable false to stop scheduled
runner jobs, and `cloud-window --pause` to pause the private control. Ending the
window does not trigger an extra catch-up run: late/final-day measurements may
remain pending and must be documented. Further collection requires review.

## Evidence, 8 October 2026

- Synthetic tests demonstrate pagination resume after storage failure, invalid
  cursor/loop rejection, provider failure isolation, per-dataset missed-day
  recovery, Beirut/DST boundaries, token rotation/ambiguous persistence handling,
  interrupted ownership handoff, and local/cloud ownership protection.
- The opt-in synthetic hosted test passed using rolled-back transactions and
  no real-data fixtures/object uploads. It verified checkpoint ordering,
  provenance-only no-ops, numeric correction/removal, source/projection integrity,
  and competing provider advisory locks.
- Fresh environment-based processes completed Google daily steps (one record)
  and WHOOP cycle/recovery/sleep/workout (six records) for 7 October. A second
  fresh pass reported zero changed records. Google/WHOOP record totals remained
  **61,656 / 137**. Cloud token versions advanced from handoff version 2 to 4,
  showing renewal intent and replacement persisted for each provider.
- The paused daily run made zero requests and recorded paused status for both.
  Viewer health writes, credential reads, escalation, Storage writes and
  anonymous original downloads remained denied.
- Database size was about **268.8 MB**, compressed original objects **0.657 MB**,
  conservative reserved organization egress about **1.78 GB**. Capacity remains
  tight; the shorter observation is not a guarantee every dataset will fit.
- Workflow YAML and additive SQL parsed; timezone/triggers/permissions/concurrency
  checked; pinned Python 3.11 Linux wheels resolved from official PyPI.
  Billing verification, actual Ubuntu dependency installation and manual GitHub
  execution passed.

### Actual GitHub acceptance

All runs used standard GitHub Ubuntu runners and merge commit `08d27c1`, with
zero uploaded artifacts. Times below are **Asia/Beirut on 8 October 2026** and
describe the job's actual start/end, separately from the measurement date.

| Check | GitHub evidence | Job time | Durable collector result |
| --- | --- | --- | --- |
| Google daily steps, 7 October | [Run 37829288194, attempt 1](https://github.com/han33-dotcom/Sentra/actions/runs/37829288194/attempts/1) | 22:05:22–22:05:42 | One dataset complete, one unchanged record, zero changed |
| WHOOP four datasets, 7 October | [Run 37829374055, attempt 1](https://github.com/han33-dotcom/Sentra/actions/runs/37829374055/attempts/1) | 22:06:01–22:06:38 | Four datasets complete, six unchanged records, zero changed |
| Google retry | [Run 37829288194, attempt 2](https://github.com/han33-dotcom/Sentra/actions/runs/37829288194/attempts/2) | 22:07:54–22:08:12 | Completed dataset skipped; no duplicate collection |
| WHOOP retry | [Run 37829374055, attempt 2](https://github.com/han33-dotcom/Sentra/actions/runs/37829374055/attempts/2) | 22:08:16–22:08:37 | Four completed datasets skipped |
| Daily control while observation paused | [Run 37829888248](https://github.com/han33-dotcom/Sentra/actions/runs/37829888248) | 22:10:08–22:10:23 | Both providers paused, zero wearable requests |

Supabase retained all six provider/attempt audit rows with actual collector
timestamps and successful/paused statuses. Completed first-attempt requests each
have their own original-response manifests. Full record counts and aggregated
content hashes matched the pre-run snapshot: **61,656 Google / 137 WHOOP**, no
changed records. Known-credential and health-payload-marker scans of the two
collection job logs passed; no raw log content was published in documentation.
The logs' scan is a bounded check, not a claim to detect every possible sensitive
string. Source data remains private in Supabase.

Final measured database size was **268.9 MB**, compressed originals **0.657 MB**,
and conservative reserved egress about **1.81 GB**. Storage limits, the $0 stopping
budget and disabled observation remain in force. This acceptance covers Google
daily steps and WHOOP's four datasets; it does not claim every Google daily/minute
dataset was re-fetched by GitHub, or that a scheduled midnight run has occurred.
Recovery/partial-failure paths were tested synthetically; broader record/app,
timezone and end-to-end validation belongs to Stage 6.

Final suite/review results are recorded in [the Stage 4 ledger](stage-4-plan.md).
Stage 5 will add the private team viewer/downloads after explicit approval.
