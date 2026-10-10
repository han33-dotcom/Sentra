# Stage 5 — private audit viewer plan

Approved stage, 8 October 2026. Keep `ETL-pipeline`; implement inline. The user's
instruction to complete authorized work within a stage overrides repeated design
approval and automatic skill commits/worktrees. Stage 4 documentation approval
was committed and pushed as `9cf2856`. Stage 5 commit and branch publication received
explicit approval after review. Private hosted acceptance completed 9 October 2026.

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
data. Platform invitations require the user's explicit approval.

## Tasks / acceptance

- [x] Authorization/configuration, date/filter contracts, protected in-session downloads; synthetic RED → GREEN checks.
- [x] Bounded least-privilege database/Storage reader, sanitized audit status and usage migration; SQL/live permissions and selected-filter comparisons.
- [x] Streamlit tables, charts, coverage/sampling/status, filters, CSV/original downloads; denied/allowed/expired identity UI tests and local browser inspection.
- [x] Reproducible viewer-only secret preparation, pinned hosting requirements and Notion/data dictionary guide.
- [x] Full checks and independent review; prepare Stage 5 commit message, wait for approval before publication.
- [x] After approved publication: private hosting, authorized owner inspection/saved downloads and anonymous protected-frame denial demonstrated; local actual unlisted identity and synthetic denial checks also passed.

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
  `.private/viewer/team.json` and viewer secrets. The approved private app is now
  deployed at https://sentra-wearable-audit.streamlit.app from `ETL-pipeline` /
  `viewer/app.py` / commit `70c0b7d`.
- No daily collection or observation enablement, paid services or quota increases.
- Separate Web identity client downloaded by the user, validated and moved from the
  project root into ignored `.private/viewer/google-identity-client.json`. Local
  viewer-only secrets prepared; localhost and actual hosted callbacks registered.
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
- Pinned Linux/Python 3.11 wheel resolution dry-run passed. Hosted build succeeded
  with Python 3.11.17; Streamlit replaced pinned PyArrow 25.0.1 with 24.0.0 for its
  known-segfault mitigation. Cross-platform pip evaluates some host markers.
- Local synthetic browser inspection showed filters, table, chart, source resolution and
  prepared CSV/gzip links. Rendered payloads matched exact numeric CSV text and synthetic
  original bytes; links use session-delivered data URLs, without server media URLs.
  Local browser download capture timed out; hosted Chrome saved-file checks below
  subsequently established acceptance.
  Screenshot is ignored `.private/viewer/synthetic-preview.png` and contains only fake data.
- Local real viewer reaches Google sign-in with identity scopes only. After the user
  approved adding the owner account, its real Google OIDC session opened the dataset catalog.
  The hosted owner Google OIDC session also opened the real catalog and selection.
- User approved Streamlit's initial and additional private-repository GitHub grants,
  restricted managed secrets, private deployment and invitations to the two additional
  team addresses. Sharing remained **Only specific people can view this app**;
  saved viewer list and three-account application allowlist checked. Invitation
  email receipt was not checked. No collector/admin secrets went to Streamlit.
- Hosted Google daily-steps selection for 7 October: CSV 9 fields / 5,702 bytes and
  original gzip 184 bytes. Both saved through Chrome into the owner's Downloads.
  CSV matched the verified backend selection byte-for-byte; original matched stored
  compressed bytes and its decompressed manifest hash. Download-event reporting
  timed out despite successful saves; real files provided the evidence.
- Hosted WHOOP sleep selection for 7 October: saved CSV contained 26 fields from
  one session and matched the backend byte-for-byte. Participant changes cleared
  previous prepared extracts after rerun. Final view was left with results cleared.
- Anonymous HTTP probe of protected `/~/+/` returned 404; authorized frame served
  the working viewer. Root-shell HTTP 200 does not grant data access. Actual local
  unlisted Google-account denial and synthetic identity tests passed; a real hosted
  unlisted-account login was not performed.
- Stage 5 is complete. Acceptance-only documentation changes await commit approval.
  Stage 6 and collection/three-day observation remain unstarted.
