# Dashboard restoration

Task: [#34](https://github.com/han33-dotcom/Sentra/issues/34). Owner: Hassan
(`han33-dotcom`). Human reviewer: `MohamadNasrallah`.

## Hosted configuration and recovery

Verified through the signed-in owner console on November 3, 2026 (Asia/Beirut):

- URL: https://sentra-wearable-audit.streamlit.app
- Repository: `han33-dotcom/Sentra`
- Configured branch: `ETL-pipeline`
- Entrypoint: `viewer/app.py`
- Selected Python: 3.11; startup logs reported Python 3.11.18 after recovery.

The signed-out URL redirected to Streamlit's combined no-access/not-found page.
The owner console still listed the app. Opening it as the owner showed that it
was asleep. Waking it exposed repeated source-clone failures and the message
that `/mount/src/sentra/viewer` did not exist. The configured `ETL-pipeline`
branch was absent from GitHub.

The deployment reference was restored at the already-released `main` commit
`c7c05489dbd1e3f1f0bdb009d90e711e0a55f096`. Remote readback confirmed both refs
pointed to that exact commit. This added no new application commit and did not
publish the restoration feature branch. Rebooting the existing app succeeded:
the source clone completed and Sentra's sign-in page rendered. The owner's real
Google identity sign-in then succeeded and rendered the five-page navigation.
The app reported that the hosted database was unavailable; real-data viewing
remains unverified until the Supabase project/connection is recovered.

Keep `ETL-pipeline` while the hosted app depends on it. Do not include it in
merged-work-branch cleanup. Application fixes still go through reviewed PRs into
`develop` and a reviewed release to `main`. Advancing the deployment reference
must be a deliberate deployment of a released commit. A future migration to
deploy directly from permanent `main` must preserve the private URL, sharing,
viewer-only secrets and exact identity callback; do not delete the current app
as a shortcut to changing the configured branch.

## Restoration behavior after release

- The default seven-day range ends on the latest observed overview day for the
  selected participant/provider (capped at today). Sleep uses its Beirut wake
  day; other intervals use their start day; vendor civil dates stay calendar
  dates. High-volume minute/original-heart-rate datasets stay in bounded audit
  access and do not choose the overview's initial dates.
- Latest available week and last seven calendar days are explicit choices.
  Manual dates persist across views, including a visit to Wellness board.
  Changing participant/provider selects that scope's latest available week.
- The latest measurement day is visible before loading records. Historical,
  unavailable and future dates have explicit wording. Last successful collection
  remains separate from measurement dates.
- The board shows its measurement date separately from its publication timestamp
  in Asia/Beirut with an offset. Reload only rereads the published board; it does
  not collect data or rebuild processing outputs. A recent publication cannot
  make old readings current.
- Existing authorization, bounded reads, download limits and egress reservations
  continue to apply. A missing/stale/exhausted budget stops reads; verify current
  organization usage before recording a baseline. Never bypass that stop.

## Repeatable acceptance walkthrough

1. In the owner console, confirm the source ref exists, the entrypoint is
   `viewer/app.py`, the app is private and the selected runtime is Python 3.11.
   Inspect startup logs without publishing secrets or participant records.
2. Open the hosted URL as an approved account and complete the separate Sentra
   Google identity sign-in. Confirm the five navigation pages are available.
3. Select the latest available week and load a bounded existing selection.
   Inspect Daily activity, Sleep, Workouts and Data availability. Missing values
   must remain explicit. Record only pass/fail evidence in public artifacts.
4. Choose a different manual range, visit Wellness board and return. Check the
   participant/provider/range persisted and that measurement and publication
   times are distinct. Test the current-calendar and latest-available shortcuts.
5. Prepare a permitted extract, sign out and check that tables, board data and
   download frames disappear. Use synthetic tests for expired/unapproved identity
   scenarios; do not claim a real hosted scenario from synthetic evidence.
6. Verify the private host denies an unauthenticated browser. Record remaining
   failures with the responsible operator action. Human acceptance remains
   separate from code merge and release.

## Verification evidence

Synthetic tests cover historical defaults, civil dates and Beirut DST, separation
of measurement and collection times, participant switching, manual dates across
the hidden board filters, board publication timezone, empty/error states,
unapproved/expired identities and sign-out clearing board/prepared-download state.

- `.venv/Scripts/python.exe -m pytest -ra`: 207 passed, five opt-in live tests
  skipped. One existing Starlette/httpx deprecation warning.
- `.venv/Scripts/python.exe scripts/check_no_data.py`: passed.
- `node --test tests/test_board_chart.cjs`: three passed.
- `.venv/Scripts/python.exe -m pip check`: passed.
- `git diff --check`: passed. The generated catalog SQL also parsed with pglast.
- A localhost browser using only synthetic identities/records rendered the
  historical default, Sleep view, charts and board freshness. Desktop and
  390-by-844 screenshots were visually inspected and remain local.
- Hosted startup and real approved-account OIDC passed for the already-released
  code. Authenticated real-data viewing remains blocked by the database connection.

CI results are recorded with the implementation PR. Hosted authenticated data
access and the actual egress baseline require separate verification; the
historical dataset's presence is not evidence of current coverage. Collection
controls were not enabled and no provider requests, migrations or threshold
changes were made during dashboard restoration.
