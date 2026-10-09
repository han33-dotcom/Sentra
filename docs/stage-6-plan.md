# Stage 6 — validation and handover plan

Approved 9 October 2026. Execute inline using executing-plans and
verification-before-completion. Keep `ETL-pipeline`; Stage 5 acceptance was
committed/pushed as `ea583b5`. No observation approval was given.

## Scope

Validate the existing pipeline and write one short operating guide. Reuse the
101 existing tests, provider collectors, private viewer and encrypted backup
commands. Add code/tests only for a demonstrated defect or a material uncovered
failure path. No new service, dependency, data scope, schedule or billing change.
Real checks use consented data and private local evidence; failure fixtures are
synthetic. Never publish health values, credentials, identity emails or raw logs.

Files: this evidence ledger, `docs/operating-guide.md`,
`docs/stage-6-validation.md`, and README links/status. If a defect is discovered,
record its callers and regression check here before changing its implementation.

## Checks

- [x] Verify selected branch and approved Stage 5 commit/push.
- [x] Run the full suite with both opt-in live synthetic database groups.
- [x] Bounded real recheck for Google daily steps and WHOOP sleep; fresh-process
  token renewal, idempotence, stored original/projection integrity and paused run.
- [x] Current access/usage/growth and zero-spend gates; retain safe capacity stops.
- [x] Create a small current encrypted backup and restore to a private isolated
  schema inside a rollback transaction; preserve existing data and credentials.
- [x] Compare selected Google/WHOOP values against participant apps, permitting
  rounding and documenting sync/date mismatches without inferring accuracy.
- [x] Write operating guide and explicit demonstrated/blocked/unverified matrix;
  verify commands, documentation and sensitive-file exclusions.
- [x] Review final changes and prepare commit message; wait for commit/push approval.

## Review focus

Coverage proves stored requests, not complete sensor data. Corrections must replace
existing projections without duplicating records. A failed page/provider must not
advance its coverage or block independent work. Token rotations persist intent
and replacements; ambiguous outcomes require reconnect. Downloads must obey
identity and quota controls. Restoration must not replace operational tables or
disclose credentials. Import averages are not observed future daily growth.

## Evidence ledger

- Branch/local/remote verified at `ea583b51f6a154d0ac3f9c537bc5fee0401292ae`.
- Fresh command: `SENTRA_LIVE_TESTS=1 SENTRA_TEST_CLOUD=1 python -m unittest
  discover -s tests -v`: 101 tests passed in 34.794 seconds, no skips. Includes
  synthetic pagination/resume, malformed/looping cursors, corrections, partial
  provider failures, missed-day recovery, token expiry/rotation/handoff, Beirut
  midnight/DST, viewer denial/filter/export bounds, quota failure and backup
  corruption/populated-target rejection. Live synthetic audit writes rolled back;
  conservative egress reservations remain counted. Private log is ignored.
- Ruling: retain the existing branch and stage ledger convention; user stage/
  commit rules override new worktrees and automatic intermediate commits.
- Ruling: use a rollback restoration rehearsal to validate actual SQL without
  leaving another duplicate health schema consuming the tight database allowance.
- Stage 7, daily collection and the three-day observation remain paused.
- Real Google/daily_steps and WHOOP/sleep rechecks of 7 October succeeded after
  natural expired-access-token renewal: cloud versions 4 → 6, active; zero changed
  records. Provider record counts and ordered key/content-hash aggregates unchanged.
  Fresh paused daily process returned paused for both without wearable fetch.
- Actual restricted viewer access checks passed: health reads allowed, writes,
  credentials/control-table reads, role escalation, Storage writes and anonymous
  original access denied. Repository private; collection variable false and
  zero-spend confirmation true. Signed-in GitHub Actions budget still $0 with
  Stop usage Yes. Current Supabase dashboard session unavailable; prior 8 October
  Free verification retained and recheck before observation documented.
- Current selected Google backup: 25 records / 225 fields / nine originals;
  actual isolated restore counts, fingerprints and originals verified. Viewer
  schema usage denied; enclosing rollback left no new schema. Existing data retained.
- Added one synthetic autumn-DST check: 25-hour Beirut day, repeated 23:00 and
  midnight classification agree between collector requests and viewer selection.
  No production code/dependency change. Targeted six planner tests passed.
- Final full suite after the added check: 102 tests passed, both live groups enabled,
  no skips. Compileall and pip check passed; private comparison/helper/configuration
  and secrets exclusions verified. Whitespace and known credential/email literal
  scans passed for all five review files; documented CLI options checked against
  actual help. Fresh selected Google 9-field / WHOOP 26-field CSV and original
  hash checks passed. Final usage: DB 269,145,779 bytes, originals 657,222 bytes,
  reserved egress 1,949,910,810 bytes; observation paused.
- Fresh independent review of Stage 6 diff/docs/commands found no actionable issues;
  six planner tests passed in the review. Reviewer did not inspect private evidence
  or rerun live services. Participant-app comparisons were pending at that review.
- User confirmed both selected app values match on 10 October 2026. Record this
  as user-reported evidence; no exact app values, display precision, timezone or
  actual check time were supplied. Private worksheet records the reported match
  without inventing missing observations. Stage 6 complete; Stage 7 remains paused.
- Message: `test: validate wearable pipeline and add operating guide`.
  No Stage 6 commit/push or observation start until the agreed approval gates.
- Completion update, 10 October: six planner tests passed; whitespace and known
  credential/email checks passed for five review files. Only documentation and
  private reported-outcome metadata changed after the 102-test run; the full live
  suite was not repeated. No health values or credentials added to tracked files.
