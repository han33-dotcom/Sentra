# Stage 4 — daily cloud collection plan

Branch: `ETL-pipeline`; approved stage, 8 October 2026. Implement inline using
planning, executing-plans and TDD skills, with one independent review at the end.
The user's stage/commit agreement overrides automatic skill commits, separate
worktrees and redundant design approval. No commit/push/merge without approval.

## Design and limits

Reuse verified request contracts, normalization, bounded retries and private
Supabase storage. Stream each page directly to shared storage; runners never
depend on a laptop snapshot. Keep cursors and completed calendar-day intervals
in durable cloud state separately by provider/dataset. Persist objects and all
normalized rows before advancing a page or covered interval. Unchanged records
must avoid metadata-only rewrites during the previous-three-day recheck.

Store provider tokens encrypted with a **separate cloud key**, held by GitHub
Actions secrets and the operator's encrypted setup journal, never the viewer.
Move ownership from local vaults to cloud state with resumable handoff. Serialize
refresh with a database advisory lock and save rotation intent before requesting
replacement tokens; interrupted/ambiguous rotation requires reconnect.

One GitHub standard Ubuntu runner, bounded time, read-only repository token,
no health-data cache/artifacts/logs, no PR execution, workflow concurrency and
database writer locks. Schedule `0 0 * * *` with `timezone: Asia/Beirut`. Default
branch publication is necessary for scheduling/initial manual dispatch. Keep
observation disabled until explicit Stage 7 approval; approved three-day dates
remain unset. After the window, pause new collection pending review.

No schema/representation change may discard returned fields or history. Quota
guards and verified egress baseline remain. Verify current Actions allowance and
zero-spending controls before cloud execution; do not buy a plan or runner.

## Tasks / acceptance

- [x] Planner: per-dataset recovery, three-day rechecks, day/timezone boundaries, bounded manual history import and recovery; original-resolution HR remains the single initial representative day.
- [x] Cloud token vault and safe ownership handoff/reconnect, separate encryption key, rotation locks/intent/version checks; synthetic failure tests.
- [x] Cloud page persistence, unchanged-content comparison, source references, correction upserts, progress only after durable writes and independent provider failures.
- [x] Run status, actual execution time, recent provisional data, storage statistics, observation pause/window and capacity stops.
- [x] Workflow/manual triggers, minimal dependencies, secure secret preparation and setup guide; test workflow syntax/configuration without publishing.
- [x] Run fresh synthetic/live checks and independent review; prepare approved-message handoff for publication.
- [ ] After approved commit/push and any approved default-branch publication: successful manual GitHub run, duplicate execution and real cloud-state verification. Until then, Stage 4 is **not fully accepted**.

## Ledger and rulings

- Branch and clean working tree verified. Existing instructions: README stage review/commit gates; no AGENTS.md found in repository.
- Official GitHub docs verified timezone-aware `schedule` support and default-branch requirement. Free private repository allowance is 2,000 standard runner minutes/month. Without a payment method quota exhaustion blocks usage; if payment exists, a zero-dollar stopping budget must be verified.
- Ruling: complete local implementation and setup before requesting publication approval; no API-created commit or temporary remote branch will bypass the user's commit gate.
- Ruling: the three-day audit does not start in Stage 4; manual acceptance requests may fetch a bounded already-imported day. Cloud progress will retain initial imported coverage.
- Additive migration 004 installed atomically with its digest; observation control remains disabled. No quota baseline reset, history removal or plan upgrade.
- Separate cloud key/config prepared in OS-encrypted ignored journal. Google p01 and WHOOP p02 handed over under locks; local refresh/authorization and stale shared-sync blocked.
- Both repository secrets installed using the repository public key and verified by secret metadata. Repository remains private, default main; no file/commit/workflow publication performed. Schedule and zero-spend verification variables are both false.
- Live bounded recheck: Google daily_steps, 7 October (one record); WHOOP four datasets, same day (six records). Two fresh passes succeeded with zero changed rows. Totals remain 61,656 Google / 137 WHOOP. Both cloud credential versions 4 (handoff version 2 plus intent/replacement renewal). Paused daily command recorded both providers paused with zero wearable requests.
- Hosted synthetic transaction passed: page checkpoint ordering, resume state, provenance-only no-op, decimal correction/metric removal, content and projection verification, provider advisory lock contention. All synthetic database rows rolled back, original uploads mocked; real data never used as test fixtures.
- Independent fresh-context review: no critical issues; one important reconnect crash gap and one minor run-attempt audit issue. Both reproduced with failing tests and fixed. Durable cloud_owned stays true throughout locked reconnect, including all token writes and incomplete prior handoff; GitHub attempt audit IDs are distinct while checkpoint execution IDs stay stable.
- Ruling: unexpected provider exceptions must also be isolated/sanitized — covered by a failing-then-passing test; no raw response/database exception strings are exposed.
- Ruling: import reserve also supports bounded status writes after health-data capacity stops; the outer database threshold still applies. No data is silently deleted/downsampled and no limits raised.
- Ruling: preserve provisional status conservatively rather than declare records final by age. Three execution dates do not guarantee all final-day/late data arrives; no extra end-window collection is implied.
- Workflow YAML/additive SQL parsed; supported IANA timezone, schedule/manual-only events, content-read permission, serialized non-cancelling jobs and zero-spend gate checked. Pinned Linux/Python 3.11 wheels resolved from official PyPI; local pip check passed. Actual Ubuntu installation/runtime remains pending.
- GitHub billing initially signed out; sign-in requested. User completed sign-in during verification. Billing Overview confirmed GitHub Free; Budgets confirmed account-wide Actions $0 budget with Stop usage Yes. No budget/plan/payment settings changed. Private screenshot saved under .private/cloud/github-actions-budget.png. SENTRA_ZERO_SPEND_CONFIRMED set true via REST and verified, while SENTRA_COLLECTION_ENABLED stays false.
- Final verification: 81 tests total; synthetic-only suite 78 passed / 3 opt-in hosted checks skipped. Full opt-in suite result recorded below after completion.
- Full opt-in suite: **81/81 passed**, including three hosted synthetic checks, in 27.9 seconds. No synthetic health records committed to Supabase and no real-health fixtures committed to Git.
- Known credential literal scan passed for all 25 review files; .private cloud/admin configuration and config/local.toml are ignored. pip check, compileall and git diff --check passed. Viewer access checks passed after deploying private daily-state tables.
- Remaining acceptance dependency: workflow publication to default main and a manual GitHub run, requiring the user's commit/push and publication review. Stage 4 implementation is ready, but Stage 4 acceptance and Stage 5 start are not claimed.
- 8 October: user explicitly approved the displayed Stage 4 commit message, pushing ETL-pipeline and merging the reviewed changes into main to perform the manual GitHub acceptance run. Observation and later stages remain unapproved.
