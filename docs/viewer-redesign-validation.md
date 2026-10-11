# Viewer redesign and ongoing collection review — 10 October 2026

## Sprint 5 closeout

The user approved merging the complete ETL MVP and redesigned viewer into `main`,
with a rewritten README covering this work. The bounded October 7–9 backfill has
since completed; both automatic controls remain paused. The 400 MB ceiling and
20 MB reserve are applied to collector configuration. The remaining control,
configuration, tests and documentation are included in the Sprint 5 closeout.
Hosted viewer capacity settings remain a separate deployment setting. The evidence
below records the earlier viewer publication; [Stage 7](stage-7-audit-plan.md)
records the subsequent backfill and superseding collection decision.

## Earlier viewer publication; operational changes were pending

The user approved the redesign. Viewer code, tests, theme and metric-definition
documentation were committed locally as `f8191aa` on `ETL-pipeline`.
Collection-control changes and their documentation remain uncommitted for
separate review. With explicit publication approval, `f8191aa` was pushed to
`origin/ETL-pipeline` and deployed to the existing private Streamlit viewer.
No merge to `main` occurred. No branch,
worktree, dependency, database migration, permission change or wearable import was
created. No collector/admin credential was added to viewer configuration.

- Explicit `cloud-window --ongoing --start YYYY-MM-DD --approved` supports daily
  collection without an end date. Legacy bounded windows remain supported.
  Pause works at an import/egress stop without transferring health data; enabling
  still requires capacity. Existing schedule, planning, quota/auth guards and
  secure credential/refresh/writer locks remain in use.
- Provider/dataset/path definitions supply readable labels, documented units,
  explanations, classifications and official references. No suffix-based guesses.
- Overview computes daily/session tables from existing record context. No second
  database copy. Midnight sleep belongs to its Beirut wake day. WHOOP recovery
  links only by returned sleep ID. Multiple sources are visible and omitted from
  numeric charts when ambiguous. Missing days are neither interpolated nor zeroed.
- Daily activity, Sleep, Workouts and Data availability show labelled charts,
  sample-day coverage, simple returned ranges, successful collection timing and
  measurement timing. Sleep includes the associated WHOOP recovery series where
  available. These are exploratory descriptions, not health or causal findings.
- Readable CSV preserves source values, units, timing, classification, state and
  provenance. Audit details retains full context, all returned scalar fields,
  detailed CSV and unchanged original gzip downloads under the existing access
  checks. Minute/original heart-rate data remains available through bounded audit
  filters rather than being loaded wholesale into the overview.
- Obsolete Stage 7 elapsed-three-day requirements were replaced by human ongoing
  observation. Historical Stage 6 evidence remains unchanged.

## Verification

- Pinterest reference revision: pale sidebar with four keyboard-accessible views,
  white chart/record panels, charcoal summary cards, compact date axes and dark
  table headers with white text. Notes/definitions remain expandable; private
  exports and source access remain available. No dependency or query changes.
- Synthetic browser checks passed at the normal desktop viewport and 390×844:
  panels stack on phones, tables scroll horizontally, and arrow keys navigate
  views with a visible focus indicator. Temporary viewport override was reset.
- Review findings reproduced and fixed: chart choice now survives navigation but
  clears with selection/identity changes; session times retain UTC offsets across
  Beirut's repeated DST hour. Chart tests verify empty missing dates and points
  without connecting lines or generated observations.
- CSS targets the pinned Streamlit 1.65 DOM; recheck it on a Streamlit upgrade.
- Full unittest discovery: **117 tests, zero failures, five opt-in live skips**.
- Publication verified on 10 October 2026 at **12:31:48 UTC** (15:31:48 Beirut).
  Remote branch equals local `f8191aa`. The existing rejected session remained
  denied; fresh allowlisted Google OIDC sign-in succeeded. Real Google daily
  and WHOOP sleep/associated-recovery views rendered without viewer errors.
- Hosted downloads saved and matched prepared bytes exactly: Google readable
  CSV **75,845 bytes / 139 rows / 23 columns**; WHOOP readable CSV **68,842 bytes /
  142 rows / 23 columns**; WHOOP detailed audit CSV **28,432 bytes**. Selected
  participant/provider checks passed; WHOOP sleep recovery was present.
- Hosted original gzip **1,734 bytes** matched prepared bytes; decompressed JSON
  parsed and its SHA-256 matched the original content hash in the filename.
  Participant switching and sign-out removed prepared download frames; signed-out
  view contained zero dataframes. Personal values stayed out of logs/screenshots.
- Separately enabled viewer live tests: **two passed**. Synthetic rolled-back SQL
  filtering/permissions and durable egress reservation verified; no retained
  synthetic health data.
- Real read-only selected data comparison: **252 mapped source values equal**
  across Google Health and WHOOP; 51/20 records, four sleep sessions per provider,
  and eight/six workout sessions. Health values stayed private; no provider fetch.
- Streamlit AppTest: authorized rendering, readable/exact audit/original download
  preparation, identity expiry/denial and selection clearing passed.
- Additional private local AppTest rendering with real selected records passed
  for both providers: seven daily rows and four sleep sessions each, readable CSV
  preparation completed without UI errors. Local test identity was synthetic;
  this is not evidence of a new hosted OIDC login. No health values/screenshots
  were printed or included in public artifacts.
- New pure tests cover explicit ongoing/pause, null versus absence, ambiguous
  sources, unscored state, malformed durations, HRV units, exact-value CSV,
  sleep-ID linkage, provider-wide failure and repeated-hour workout duration.
- Independent reviewer found three important issues; each was reproduced with a
  failing test, fixed and verified: pause blocked at quota, provider-wide failure
  hidden by prior success, DST duration omitted by wall-time ordering.
- `pip check` passed; `git diff --check` found no whitespace errors. Git reports
  expected local LF/CRLF conversion notices. Existing Streamlit test-mode context
  warnings are not runtime exceptions.
- Local runtime: Python 3.11.5 / Streamlit 1.65.0 / PyArrow 25.0.1. Hosted runtime
  remains Python 3.11.17 / effective PyArrow 24.0.0, so local UI evidence does not
  replace the required post-publication hosted checks.
- Synthetic-only browser proof uses ignored `.private/redesign_preview.py`, bound
  to localhost and isolated from configuration/database/provider credentials.

## Lossless storage investigation (no migration applied)

PostgreSQL measured all **140,727** existing measurement rows. Splitting repeated
timing/resolution/source context from each row reconstructed every JSONB row
exactly (`bool_and(full_row = residual || context)` was true):

| Representation | PostgreSQL JSONB payload bytes |
| --- | ---: |
| Current complete measurement rows | 141,192,955 |
| Residual measurement fields | 58,810,879 |
| Unique context objects (61,793) | 40,892,805 |
| Proposed payload before IDs/index overhead | 99,703,684 |

Measured payload difference is **41,489,271 bytes (29.4%)** before references and
indexes. The actual existing measurement relation including indexes is 137,428,992
bytes; JSONB payload sizes are a representation experiment, **not projected final
relation size or realized disk savings**. No files/history/originals were removed.

A migration would need a new context table, compact leaf rows and a compatibility
view reproducing the current columns, while preserving per-field exceptions,
provenance, original units and numeric values. All writer/upsert, reader, export,
backup/restore and access-role contracts must be adapted/tested. Stage a bounded
rollback-capable rehearsal with output/count equality and measured physical
relation/index size before approval. Preserve encrypted backups and the current
representation until verified; coexistence needs headroom. Normalizing context
alone will not guarantee indefinite capacity. This revision does not apply it.

## Operational gates still pending

On 10 October: database **269,145,779 bytes**, originals **657,222 bytes**; latest
conservative egress after checks **2,020,577,882 bytes**. Baseline was verified
8 October at 14:07:12 UTC; reservations were retained, not reset.
GitHub private repository and `SENTRA_COLLECTION_ENABLED=false`,
`SENTRA_ZERO_SPEND_CONFIRMED=true` were verified through REST. Account-wide Actions
**$0 budget / Stop usage: Yes** was freshly verified in the signed-in dashboard.
SQL control remains `{"enabled":false}`. No activation time exists.

Supabase dashboard currently requires sign-in to verify the current Free plan and
organization usage. The existing Free confirmation is not a fresh billing check.
Google Testing refresh expiry remains an operating dependency around 15 October
07:05 UTC; WHOOP refresh rotation stays managed under existing locks.

GitHub schedules execute the default branch, currently `main`; its tracked
workflow checks out that default ref. Therefore the reviewed ongoing planner
must also reach `main` through separately approved publication before scheduling
can use it. The private viewer runs `ETL-pipeline`. Do not merely enable a GitHub
variable against the old bounded planner. After approval/publication, fresh
billing/capacity/auth checks precede SQL/GitHub enabling and an approved successful
daily run. Report exact enabling time then, not before.

Hosted redesigned allowed-account OIDC, data views and download behavior passed
the checks above. A fresh real unlisted-account sign-in was not induced; the
initial rejected session is not evidence of that specific scenario. The known
replacement-project and off-machine key recovery limits remain as documented
in Stage 6. No provider fetch, collection enabling or storage migration occurred.

Viewer commit: `f8191aa feat: redesign private wearable explorer` (published).
The ongoing collection-control changes still await separate review/commit.
