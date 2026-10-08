# Stage 5 — private audit viewer plan

Approved stage, 8 October 2026. Keep `ETL-pipeline`; implement inline. The user's
instruction to complete authorized work within a stage overrides repeated design
approval and automatic skill commits/worktrees. Stage 4 documentation approval
was committed and pushed as `9cf2856`. Stage 5 commit and branch publication received
explicit approval after review; private hosted acceptance remains pending.

## Design

One Streamlit Community Cloud private app, with Google OIDC sign-in and an exact
verified-email allowlist checked before database access and every download.
Identity sign-in uses a separate OAuth client with only `openid email profile`;
the viewer receives no wearable OAuth tokens, collector credentials or vault key.
Reuse the restricted `sentra_viewer` login and private Storage account. No global
health-data caches, local health files, signed public object links or polling.

Filters use participant ID, provider, dataset, metric, Beirut calendar dates and
literal text search. Read bounded selected rows; refuse oversized results instead
of exporting a silently truncated selection. Keep units, vendor values, source
references, resolution, provisional status and score state. Display evidence of
collection coverage separately from observed measurements and sampling gaps.
Charts plot one numeric metric/unit without mixing resolutions or claiming gaps
prove missing sensor readings. CSV and unchanged gzip originals are prepared only
after an authorized explicit action. All downloads obey the same allowlist.

Add narrow SQL functions for viewer usage/observation status and a capped egress
reservation; deny raw private-table access. Preserve current quotas and pause.
Use session-only bounded results, explicit refresh and fail-closed sanitized errors.
Provide Notion link and data-dictionary instructions without writing participant
data or sending invitations/messages to others.

## Tasks / acceptance

- [x] Authorization/configuration, date/filter contracts, protected in-session downloads; synthetic RED → GREEN checks.
- [x] Bounded least-privilege database/Storage reader, sanitized audit status and usage migration; SQL/live permissions and selected-filter comparisons.
- [x] Streamlit tables, charts, coverage/sampling/status, filters, CSV/original downloads; denied/allowed/expired identity UI tests and local browser inspection.
- [x] Reproducible viewer-only secret preparation, pinned hosting requirements and Notion/data dictionary guide.
- [x] Full checks and independent review; prepare Stage 5 commit message, wait for approval before publication.
- [ ] After approved publication: private hosting, authorized teammate inspection/download and unauthorized visitor denial demonstrated. Do not claim hosted acceptance before these checks.

## Review focus

- A signed-in but unlisted or unverified user must trigger zero database/object reads.
- Midnight/DST boundaries, civil dates and overlapping sleep intervals must match exports.
- Oversized results, stale budgets and unavailable usage must fail without partial downloads.
- A prepared file must never become an unauthenticated server media URL.
- Changing filters/logout must clear prepared data; exact numeric values survive CSV.

## Execution ledger

- Branch verified `ETL-pipeline`. README stage/commit rules apply; no AGENTS.md found.
- Official Streamlit docs verified one private app, private GitHub permissions,
  viewer invitations can propagate, app hibernation after 12 idle hours, managed
  secrets and Python selection. Built-in OIDC authenticates identity, not team
  authorization; exact allowlist is therefore required.
- User initially provided two authorized emails and later explicitly added the owner
  Google account, correcting its exclusion. Three accounts are now saved only in ignored
  `.private/viewer/team.json` and viewer secrets. Streamlit hosting sign-in is complete;
  no app created.
- No daily collection or observation enablement, paid services or quota increases.
- Separate Web identity client downloaded by the user, validated and moved from the
  project root into ignored `.private/viewer/google-identity-client.json`. Local
  viewer-only secrets prepared; localhost callback registered. Hosted callback pending.
- Migration 005 deployed to existing Free Supabase. Actual viewer login denied health
  writes and private credential/control tables. Selected Google/WHOOP CSV fields and
  original hashes matched; stored record counts unchanged. Synthetic live fixtures rolled back.
- Independent review found a lost egress reservation after read rollback and retained
  prepared downloads on an incomplete date edit. Both reproduced with failing tests,
  then fixed: reserve through a separate autocommit connection; clear selection results
  before stopping for an incomplete date. Live rollback regression passes.
- Final suite: 101 tests, all passed, including both opt-in hosted check groups
  (`SENTRA_LIVE_TESTS=1`, `SENTRA_TEST_CLOUD=1`). Compileall, dependency consistency,
  SQL parsing and whitespace checks passed. Known credential/email literal scan passed
  for all 22 changed/untracked review files. No real data fixtures committed.
- Pinned Linux/Python 3.11 wheel resolution dry-run passed; actual hosted dependency
  installation remains pending deployment. Cross-platform pip evaluates some host markers.
- Local synthetic browser inspection showed filters, table, chart, source resolution and
  prepared CSV/gzip links. Rendered payloads matched exact numeric CSV text and synthetic
  original bytes; links use session-delivered data URLs, without server media URLs.
  Browser download capture timed out; actual saved-file acceptance remains pending.
  Screenshot is ignored `.private/viewer/synthetic-preview.png` and contains only fake data.
- Local real viewer reaches Google sign-in with identity scopes only. After the user
  approved adding the owner account, its real Google OIDC session opened the dataset catalog.
  Hosted privacy, account denial and teammate saved-file
  checks remain required; do not mark Stage 5 complete or advance Stage 6.
