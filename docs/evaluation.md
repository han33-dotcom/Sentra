# Sprint evaluation: expected vs actual

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). One shared table for the
November 2–16 sprint. Each row is an acceptance item, what was expected, what was actually
recorded, and where the evidence is. It records only results that exist in a merged PR, an
issue's completion evidence or a test in this repository. Owners correct their own rows.

Two kinds of verification are kept apart:
- **Tests**: synthetic fixtures in the repository, run in CI on Linux and Windows. Never real data.
- **Real/hosted**: observed on the deployed services or real accounts, recorded privately by the
  owner; only aggregate, non-identifying results appear here.

"Pending" means not yet recorded, not failed. A task is Done when every acceptance criterion has recorded evidence under
[local delivery](local-delivery.md). Agents verify accessible criteria; only inaccessible
observations need human instructions. This table does not close anything.

Last updated: November 18, 2026. Implementation and hosted observations are distinguished below; a later release does not retroactively change a tested deployment.

## Privacy and access (SEN-27, SEN-26, SEN-32)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Deny by default | Unknown, inactive or ambiguous accounts see nothing and cause no protected read | Denied before any protected read; removed officers denied on the next render | #51, #55, #64; `test_access.py`, `test_viewer_access.py`, `test_privacy_matrix.py` | Yes | Sequential no-role/inactive denial passed November 17; see scope below |
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
| Overview and profiles | Participation states counted separately; group statistics per device with k = 5; profiles only within sharing | Implemented as expected | #62; `test_organization*.py` | Yes | Team overview/profiles rendered November 17; organization-account matrix pending |
| Observations | What changed, which readings, limitations; wellness vs collection vs medical kept apart; provisional labels | Implemented; stale or future data draws no conclusion | #65; `test_observations.py` | Yes | Hosted stale-data explanation observed November 17 |
| Trends | Selectable periods, personal baseline comparison, group exploration with k = 5 per statistic, gaps kept | Implemented; organization users see only devices that reach 5 and no hidden-day counts; department comparisons deferred | #68; `test_trends.py`, `test_organization_pages.py`, `test_privacy_matrix.py` | Yes | Team Trends rendered November 17; no eligible real group statistic |
| Follow-ups | Assignee, open/ongoing/resolved history, narrow write path, same boundaries | Merged into `develop`. The viewer uses a separate write role. Migration 010 and the private hosted write-role configuration are applied; sequential synthetic group-note acceptance passed | #72; `test_follow_ups_db.py`, `test_privacy_matrix.py` | Yes | Officer create/update, assigned-reviewer update, cross-organization history exclusion and deactivation denial passed November 17 |
| Reports | Permitted summaries, trends, explanations and limitations; same boundaries for downloads | Merged/released in #82/#100: preview with Markdown and PDF downloads from the same content, rebuilt from the current access decision each load; follow-ups as counts only; demonstration copy limited to people who agreed | SEN-42; `test_reports.py`, `test_report_pages.py`, `test_privacy_matrix.py`; [reports](reports.md) | Yes | Reports preview and both download controls rendered November 17; permitted demonstration remains pending |

## Enrollment and collection (SEN-28, SEN-38, SEN-44, SEN-47)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Self-service enrollment | Participant joins on their own phone; sharing and demonstration choices; provider connection; return to change or withdraw | Implemented and released; hosted enrollment live on released `main` | #52, #54, #64, #71; SEN-28 completion evidence | Yes | One real Google phone signup and a sharing update recorded privately (owner) |
| Restart readiness | Connections, limits, storage and budgets checked without provider requests | Readiness inspection implemented; November 3 checks recorded | #53; SEN-44 completion evidence | Yes | Partly recorded; provider dashboard checks and restart authorization pending |
| Five active participants | Five consenting, connected, actively contributing participants | Not yet; collection remains paused | SEN-38, SEN-47 | — | Pending |

## Data, storage and recovery (SEN-29, SEN-30, SEN-45, SEN-46, SEN-48, SEN-49, SEN-50)

| Item | Expected | Actual (recorded) | Evidence | Tests | Real/hosted |
| --- | --- | --- | --- | --- | --- |
| Incomplete assessments | Missing inputs or short history never read as calm; states consistent everywhere | "Partial" and "Not enough information" states; versioned board. Group statistics in processing and the read API are per device, as in the overview, with matching contributor counts; mixed-device participants enter no device statistic; the API refuses a pooled pre-device snapshot | #56, #79; [indicator contract](indicator-contract.md#consistency-checks); `test_processing.py::GroupStatisticConsistencyTests` | Yes | November 17 authorized stored-data refresh and compatible board/assessment readback passed; no collection restarted |
| Indicator definitions | Agreed names, states and meanings; expert package; provisional until reviewed | Contract and evidence documents merged | #56; [medical evidence](medical-evidence.md) | — | Dashboard owner agreed v0 names/states/meanings November 14; expert threshold sign-off remains pending |
| Consistent updates | Changed information refreshed efficiently; repeated runs safe; failed processing keeps the previous complete view | Each published tier set and board is complete. Monthly publication in #106 detects historical corrections/omissions through source fingerprints and reuses verified unchanged objects; an interrupted board upload retains the old complete board and is repaired on retry. Full compact-cache processing and obsolete-object storage remain limitations | #57, #80, #106; [publication consistency](wellness-board.md#publication-consistency-48) | Yes | Pending |
| Backup readiness | Policy agreed; fresh verified backup; destructive steps gated | Policy proposed. Full encrypted backups include consent, enrollment, installed follow-up tables and compact series, with offline verification (#85) | #58, #67, #72; [retention policy](retention-policy.md) | Yes | November 18 capacity exception approved; execution/verification remain to be recorded |
| Recovery rehearsal | Restore into an isolated project; counts and fingerprints match | Verified isolated restore with synthetic data, including follow-up history and rollback of allocator changes after failure | #58, #67; `test_backup_restore_db.py`; [recovery rehearsal](recovery-rehearsal.md) | Yes (throwaway PostgreSQL) | Pending (operator) |
| Lossless storage | Compact without information loss; measured savings | Compact series with re-expansion; about 7× smaller in a local test. Tiers read a compact reading only when its per-field row is gone and its record still names the same response, so removing verified rows cannot change published tiers | #59, #81; [storage plan](storage-plan.md#implementation-status-46); `test_compaction_db.py` | Yes (throwaway PostgreSQL) | Live phase-3 deletion remains gated; see November 17 operations evidence |
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


## November 17 delivery and hosted evidence

Release [#100](https://github.com/han33-dotcom/Sentra/pull/100) put #85, #82, #83,
#84, #98 and #99 on main at `5136885a89bf30f8ce2294d71c4419a3e87ae72f`.
Render's manual deployment of that exact commit succeeded (14:28 UTC); health and
join returned HTTP 200. Free compute, the existing URL and disabled auto-deploys
were retained. The Streamlit deployment alias was fast-forwarded to the same release;
entrypoint `viewer/app.py`, Python 3.11 and private hosting audience were retained.
The approved team account completed Google verification and reached the viewer.

Observed on that release, without storing real-data screenshots:

- Daily activity loaded one bounded historical week. The user saved its readable
  CSV locally; a second bounded source comparison found **233 rows and every field
  identical** (14:58 UTC). Only count/equality evidence is published here.
- Organization overview rendered participation states and suppressed every
  under-threshold group statistic. Profiles explicitly withheld a current wellness
  conclusion for stale data. Trends preserved historical data and withheld rule
  results from the old board contract.
- Reports rendered its selected-period preview and Markdown/PDF download controls.
  Follow-ups rendered an empty read-only view for the team role, as designed.
  This is not an officer-write test, cross-organization account test or approved
  real-data demonstration. No participation/consent record or note was changed.

Reviewed migrations 010/011 were applied at 14:13 UTC. The new restricted follow-up
role could execute its narrow function, could not read health tables or directly
insert notes; the viewer could not insert notes. The credential was saved encrypted
in the existing private operator location. Hosted writer configuration and a separately
designated organization identity are still required; participants are not promoted
for testing. Migrations 012/013/014 and later hosted rollout are separate from these
observations. Code for compact writes (#102), purpose attribution (#103), eligibility
metadata (#104), and guarded removal (#105) is merged into develop.

Operational guards remain effective: collection was paused before and after the
checks. Supabase's November calendar-month uncached usage displayed 0.468 GB; a
conservative 470,000,000-byte baseline update retained the larger existing baseline
and all reservations. Fresh full-backup preflight estimated 1,012,590,124 bytes of
egress against 915,309,961 bytes remaining at that check, while the configured private
folder used 250,531,219 bytes against its 200,000,000-byte backup guard. **No full
backup or removal started; no guard or reservation was reset.** Subsequent bounded
checks further reduce remaining egress. Isolated real recovery, retention agreement,
both-owner deletion approval, exact restart scope, five active consenting contributors
and consecutive-day growth observations remain unverified.

Actual branch settings were read November 17: develop and main both require strict
current `guard`, Linux/Windows Python 3.11 `test`, and `pr-policy` checks, enforce
admins, and disallow force-push/deletion. Required human review is off under policy 4.
Native deletion of merged work branches is enabled. No Slack message/cutover or
Project completion is claimed by this evidence entry. A separate board-refresh
preflight at 15:22 UTC estimated 47,955,372 bytes of database reservations against
809,441,501 bytes remaining. The user authorized one refresh of stored data after
the next release, capped at 100 MB total reservations, with collection paused;
this entry records authorization/preflight, not successful execution.

## November 17 sequential hosted role checks

On release `9b6e8c048b49f04a89839024cc64e06b3c586506`, one owner-designated Google
identity was rotated through no role, officer/reviewer in an empty synthetic
organization, officer in another, and inactive. Hosted group follow-up creation,
officer and assigned-reviewer updates, open/ongoing/resolved status and history,
cross-organization exclusion, fresh reviewer sign-in, deactivation denial and
sign-out cleanup passed. The owner corrected the missing hosted writer secret;
successful hosted writes verified the resulting configuration. Temporary access
was disabled and all four synthetic group follow-ups resolved, retaining history.
Collection stayed paused and no real participant or board was modified.

See [the procedure and scope](privacy-checks.md). One sequential identity removes
the need for additional Google accounts for these checks, but does not test
simultaneous identities. Empty organizations do not establish hosted withdrawal,
individual-data or five-contributor acceptance; those remain separately identified
in the evaluation and are covered by isolated synthetic tests.

## November 17 publication readback and November 18 capacity approval

The one authorized stored-data refresh completed at 15:56 UTC on November 17.
A separate 15:57 UTC readback confirmed `board-2`, `assessment-v1`, `monthly-v1`
and matching publication hashes. Refresh plus verification reserved 67,823,723
bytes, below its 100 MB authorization. Collection stayed paused. The earlier
preflight-only paragraph above is historical; this entry records the actual outcome.

On November 18 the owner authorized the two capacity ceilings and one full backup
described in [storage rollout](storage-plan.md#november-18-approved-backup-headroom).
This is authorization, not evidence of a completed archive or recovery rehearsal.
