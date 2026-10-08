# Stage 2 design and implementation ledger

Authorized by the user's Stage 2 brief and explicit request on 8 October 2026.
Work stays in the existing `ETL-pipeline` checkout, preserving Stage 1 changes.
The user's instruction to finish the current stage autonomously takes precedence
over extra skill approval gates, worktree creation and automatic commits.

## Design

Use the working Google Health v4 connection for Fitbit data; do not use the legacy
Fitbit API. WHOOP uses independent v2 cycle/recovery/sleep/workout collectors.
Default history ends at today's Beirut midnight: 30 calendar days of daily data
and sessions, seven days of minute aggregates, one day of original HR samples.
Google vendor daily rollups follow provider civil dates; physical minute rollups
use Beirut day boundaries. Sleep selection follows the provider's end-time filter.
Preserve each unchanged API response, including unknown fields, compressed and
encrypted. Aggregated responses are vendor summaries, not physical sensor signals.

Use standard-library SQLite in memory, individually compressed rows with shared
metric context, and persist encrypted compressed snapshots
inside `.private`. No unencrypted SQLite files or journals. Each connection has
its own store and import lock. Each page transaction stores manifest, normalized
records and next cursor together; encrypted raw objects are written first and
deduplicated by participant/content hash. An interrupted snapshot write leaves
the previous page durable. Resume skips completed jobs; `--recheck` revisits them
and upserts changed records. Stable keys exclude mutable measurement values.

HTTP retries cover read requests, including read-only POST rollups, with four
attempts, bounded Retry-After/backoff and request pacing. Authorization renewal
retains Stage 1's non-retry rotation behavior. A failed job does not prevent other
datasets completing. Expired cursors may restart one job once, with idempotent
record writes. Repeated pagination tokens and excessive page counts stop safely.

All returned fields remain in original responses. Normalization exposes payload scalar
fields with vendor names/values, mapped units/classification where documented,
otherwise explicit unknowns. Session summaries retain nested fields. Recovery
timing is resolved against the current cycle on reads, with both response sources.
Source/timing metadata stay in record context rather than duplicated metric rows.
Recovery never substitutes collection/create time
as measurement time. Recent data is provisional. Fetch coverage records the API
window traversed and does not assert every expected measurement exists.

Local capacity controls bound response size, total private import storage and
free disk headroom. No cloud provisioning, paid dependencies, scheduler or viewer.
Private exports require explicit CLI action and remain under `.private/exports`.
CSV strings are escaped against spreadsheet formula execution. Provider identity
fields are excluded from normalized exports; original-response exports remain
sensitive and unchanged. Manual Fitbit fallback is unnecessary while Google works.

## Implementation plan

1. `datasets.py`: bounded jobs, provider endpoints, time/filter/resolution contracts.
2. `transport.py`: sanitized read requests, pacing/retries/401 renewal/size bounds.
3. `normalize.py`: stable identities, vendor fields, timestamps/units/provenance.
4. `local_store.py`: encrypted snapshot transactions, raw manifests and progress.
5. `collect.py`: pagination/resume/recheck/provider independence; CLI commands.
6. `exports.py`: private CSV/JSON/original-response extracts; operating instructions.

For each component, synthetic behavior tests precede implementation. Run the whole
unittest suite after changes. Then run the authorized initial import, inspect only
nonsecret counts/coverage/size and source integrity, repeat import to prove no
duplicates, and perform a small recheck. A fresh reviewer checks the final code.

## Review focus

- DST changes and vendor civil dates must not fabricate UTC measurement instants.
- Changing a value or removing a field must update the existing identity.
- Crashes/capacity stops must not advance a cursor past durable records.
- API bodies, OAuth credentials and participant identities must not leak in logs.
- Empty/unscored/recent data and HTTP access errors must stay distinguishable.

## Ledger

- Inspection: branch verified; no repository/ancestor AGENTS.md found; Stage 1 reused.
- Ruling: encrypted SQLite snapshots suit two local participants without another
  dependency. Cost if wrong: higher snapshot RAM/write cost; bounded size limits
  stop growth and Stage 3 will migrate to PostgreSQL.
- Ruling: daily vendor rollups preserve provider civil dates, which may differ
  from Beirut when a participant travels. Cost if wrong: day comparisons need
  timezone context; exports retain the provider's original time fields.
- Real request findings: Google daily filters require snake_case; sleep LIST
  rejects a source-family parameter. Sleep imports keep all returned sources.
- Performance ruling: seven-day request batches retain daily window size 1.
  Individually compressed rows and shared context avoid excessive snapshot RAM.
  Streaming compressed exports enforce capacity before each compressed write.
- Fresh review: reported failure-isolation, recovery-timing, fetch-history,
  export-memory and shared-capacity issues were reproduced and repaired; reviewer
  validated targeted fixes with 39 synthetic tests. Final suite: 43 tests passed.
- Acceptance: all current Google/WHOOP import jobs complete; fresh-process reruns
  skipped them without duplicate records; real normalized/original exports and
  source hashes checked. See stage-2-collection.md for counts and limitations.
- Stop: Stage 2 complete; Stage 3 requires the user's explicit approval.
