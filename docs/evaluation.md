# Sprint evaluation: expected vs actual

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). One shared table for the
November 2–16 sprint. Each row is an acceptance item, what was expected, what was actually
recorded, and where the evidence is. It records only results that exist in a merged PR, an
issue's completion evidence or a test in this repository. Owners correct their own rows.

Two kinds of verification are kept apart:
- **Tests**: synthetic fixtures in the repository, run in CI on Linux and Windows. Never real data.
- **Real/hosted**: observed on the deployed services or real accounts, recorded privately by the
  owner; only aggregate, non-identifying results appear here.

"Pending" means not yet recorded, not failed. A task is Done only when a teammate verifies its
acceptance on the issue; this table does not close anything.

Last updated: November 12, 2026, from `develop` at `464222e`.

## Privacy and access (SEN-27, SEN-26, SEN-32)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Deny by default | Unknown, inactive or ambiguous accounts see nothing and cause no protected read | Denied before any protected read; removed officers denied on the next render | #51, #55, #64; `test_access.py`, `test_viewer_access.py`, `test_privacy_matrix.py` | Yes | Pending (hosted procedure below) |
| Organization isolation | An organization user never sees another organization's participants | Holds on all ten viewer pages, including both Trends views, Follow-ups and Reports (page and downloaded file), even when the reader returns everyone | `test_privacy_matrix.py` (officer and reviewer of org A, officer of org B) | Yes | Pending |
| Sharing scope | `group_only` participants count only in group statistics, never individually | Never shown individually on any page; counted in the overview | `test_privacy_matrix.py`, `test_organization_pages.py` | Yes | Pending |
| Small groups | Each group statistic needs ≥ 5 eligible contributors of its own; small counts not revealed | Statistics below 5 show "Not shown" and "<5"; organization users never see counts 1–4 | #62; `test_organization.py`, `test_privacy_matrix.py` | Yes | Pending |
| Withdrawal | Takes effect immediately in views; no automatic deletion | Hidden on the next render, including the follow-up note and history. A withdrawal before the follow-up read snapshot also filters out both | #35, #64, #72; `test_privacy_matrix.py`, `test_follow_ups_db.py`, `test_organization_access_db.py` | Yes | Pending |
| Sharing reduced to group-only | Individual details disappear immediately | Hidden on the next render, including follow-up notes and history | `test_privacy_matrix.py` | Yes | Pending |
| Excluded fields | No names, contact details, provider account IDs or location in published outputs | The board carries only `id`, `name` (= pseudonym), `device`, `days`; extra source columns never reach it | `test_privacy_matrix.py::ExcludedFieldsTests`; [participation permissions](participation-permissions.md) | Yes | Pending |
| One shared access check | Viewer, API, downloads and notes use one module | Viewer pages and Follow-ups use `sentra.access`. Follow-ups also enforce organization and current consent in the database. Downloads, audit tools and the read API are team-only | #51, #55, #72; [read API](read-api.md) | Yes (viewer) | Pending |
| Participation document | Data categories, recipients, sharing and withdrawal defined; team agreement; advisor route | Document merged | #33; [participation permissions](participation-permissions.md) | — | Team agreement and advisor outcome pending (SEN-26) |

## Organization application (SEN-34, SEN-39, SEN-40, SEN-41, SEN-31, SEN-42)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Hosted dashboard | Approved account signs in and uses all explore pages; sign-out clears private state | Hosted walkthrough on released code, November 3: pages rendered, sign-out left no data tables | #36; SEN-34 completion evidence | Yes | Recorded (released code before #62/#65) |
| Overview and profiles | Participation states counted separately; group statistics per device with k = 5; profiles only within sharing | Implemented as expected | #62; `test_organization*.py` | Yes | Pending (needs release and hosted check) |
| Observations | What changed, which readings, limitations; wellness vs collection vs medical kept apart; provisional labels | Implemented; stale or future data draws no conclusion | #65; `test_observations.py` | Yes | Pending |
| Trends | Selectable periods, personal baseline comparison, group exploration with k = 5 per statistic, gaps kept | Implemented; organization users see only devices that reach 5 and no hidden-day counts; department comparisons deferred | #68; `test_trends.py`, `test_organization_pages.py`, `test_privacy_matrix.py` | Yes | Pending |
| Follow-ups | Assignee, open/ongoing/resolved history, narrow write path, same boundaries | Merged into `develop`. The viewer uses a separate write role. Hosted rollout requires migration 010 and private role configuration | #72; `test_follow_ups_db.py`, `test_privacy_matrix.py` | Yes | Pending |
| Reports | Permitted summaries, trends, explanations and limitations; same boundaries for downloads | Implemented in review: preview with Markdown and PDF downloads from the same content, rebuilt from the current access decision each load; follow-ups as counts only; demonstration copy limited to people who agreed | SEN-42; `test_reports.py`, `test_report_pages.py`, `test_privacy_matrix.py`; [reports](reports.md) | In PR | Pending |

## Enrollment and collection (SEN-28, SEN-38, SEN-44, SEN-47)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Self-service enrollment | Participant joins on their own phone; sharing and demonstration choices; provider connection; return to change or withdraw | Implemented and released; hosted enrollment live on released `main` | #52, #54, #64, #71; SEN-28 completion evidence | Yes | One real Google phone signup and a sharing update recorded privately (owner) |
| Restart readiness | Connections, limits, storage and budgets checked without provider requests | Readiness inspection implemented; November 3 checks recorded | #53; SEN-44 completion evidence | Yes | Partly recorded; provider dashboard checks and restart authorization pending |
| Five active participants | Five consenting, connected, actively contributing participants | Not yet; collection remains paused | SEN-38, SEN-47 | — | Pending |

## Data, storage and recovery (SEN-29, SEN-30, SEN-45, SEN-46, SEN-48, SEN-49, SEN-50)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Incomplete assessments | Missing inputs or short history never read as calm; states consistent everywhere | "Partial" and "Not enough information" states; versioned board | #56; [indicator contract](indicator-contract.md) | Yes | Pending (board rebuild after release) |
| Indicator definitions | Agreed names, states and meanings; expert package; provisional until reviewed | Contract and evidence documents merged | #56; [medical evidence](medical-evidence.md) | — | Team agreement and expert review pending |
| Consistent updates | Failed processing keeps the previous complete view | Each published tier set and board is complete. An interrupted board upload can leave tiers one run ahead until the next refresh repairs the board | #57, #80; [publication consistency](wellness-board.md#publication-consistency-48) | Yes | Pending |
| Backup readiness | Policy agreed; fresh verified backup; destructive steps gated | Policy proposed. Full encrypted backups include consent, enrollment and installed follow-up tables, with offline verification | #58, #67, #72; [retention policy](retention-policy.md) | Yes | Fresh verified backup pending (operator) |
| Recovery rehearsal | Restore into an isolated project; counts and fingerprints match | Verified isolated restore with synthetic data, including follow-up history and rollback of allocator changes after failure | #58, #67; `test_backup_restore_db.py`; [recovery rehearsal](recovery-rehearsal.md) | Yes (throwaway PostgreSQL) | Pending (operator) |
| Lossless storage | Compact without information loss; measured savings | Compact series with re-expansion; about 7× smaller in a local test | #59; [storage plan](storage-plan.md) | Yes | Migration 009 not applied |
| Growth forecast | Measured costs and a recommendation for the next batch | Measurement log implemented | #60; [capacity measurements](capacity-measurements.md) | Yes | Measurements pending collection restart |

## How the matrix counts a pass

`tests/test_privacy_matrix.py` gives every page a reader that returns every synthetic participant,
as if database scoping had failed. A page passes only if it renders a usable view (no exception and
no on-screen error such as "Viewer request stopped"), pages that list individuals show exactly the
permitted participant, and group pages name nobody. So a page that stops or shows nothing cannot
pass the "nothing restricted is shown" checks. Checked by sabotage on November 10: making Profiles
stop for an officer without individual access fails the withdrawal and downgrade checks (the
earlier version passed it); emptying Profiles fails the isolation check; removing its filter fails
the matrix. Follow-ups checks both the current note and history text against the organization’s scope,
then repeats the same page after a withdrawal or downgrade. A synthetic cross-organization history
leak is detected even when the note text contains no participant ID.

## Retests after dependencies merge

Some rows are verified only for what has merged so far. They are retested when their
dependency lands:

| When this merges | Retest |
| --- | --- |
| Trends (#68, SEN-40) | **Done November 9:** both Trends views added to `PAGES`; matrix passes; removing the Trends filter fails it |
| Follow-ups (#72, SEN-31) | **Done November 12:** Follow-ups added to the matrix, with same-page withdrawal and downgrade checks |
| Reports (SEN-42) | **Done November 12, in its PR:** Reports and its decoded download added to the matrix; removing its individual filters fails 7 checks, ignoring the demonstration choice fails 1 |
| Backup coverage (#67, SEN-29/30) | **Done November 12:** updated the backup evidence and verified synthetic restore using migration 010 |
| A release to `main` and hosted deployment | Run the [hosted check procedure](privacy-checks.md) and fill in the Real/hosted column |
