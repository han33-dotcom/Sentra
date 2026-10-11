# Stage 5 — private team audit viewer

Implemented on `ETL-pipeline`, 8 October 2026; **private hosted acceptance completed
9 October 2026** using the authorized owner's real Google session.
Open the [private team viewer](https://sentra-wearable-audit.streamlit.app).
The Stage 4 documentation approval was committed/pushed as `9cf2856`; Stage 5
commit message and branch publication received explicit approval after review.
The host runs viewer commit `70c0b7d` from `ETL-pipeline`.
No observation/daily collection was enabled.

## Review and try

Use the hosted link above, sign in with a consented allowlisted Google account,
and follow the same filter/load/download steps described below. Streamlit sharing
is set to **Only specific people can view this app**; the approved two additional
viewer addresses were saved in its sharing list. The application independently
permits the approved three accounts. Email receipt was not checked.

Entrypoint: `viewer/app.py`. Viewer code is in `src/sentra/viewer_*.py`; the narrow
status/egress migration is `sql/005_viewer_status.sql`. Use Python 3.11 locally
and in Community Cloud. From the repository root:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[viewer]"
.venv\Scripts\python.exe -m sentra.viewer_setup migrate
.venv\Scripts\python.exe -m sentra.viewer_setup prepare
.venv\Scripts\python.exe -m streamlit run viewer/app.py --server.address 127.0.0.1
```

Open `http://localhost:8501`, sign in with an authorized Google account, choose a
participant ID/provider/dataset/metric/date range and click **Load selected data**.
The displayed end date is included; CSV timestamp offsets are retained. A vendor
civil date is filtered as its calendar day, without inventing a physical timestamp.
Physical times use Beirut day boundaries, including DST. Sleep/workout intervals
overlapping the date window are included. Literal text search applies to metric,
returned vendor value, unit and availability. It also applies to CSV and source
selection. Changing filters clears results/prepared downloads; refresh explicitly.

Tables include vendor values/units, value kind, interval/point/civil timestamps,
requested resolution, score/provisional state and source references. Charts use one
numeric metric/unit/resolution, plot returned points and may round float display.
CSV keeps exact PostgreSQL numeric text. Text beginning with spreadsheet formula
characters is prefixed with an apostrophe in CSV; original API bytes are unchanged.

**Prepare filtered CSV** exports all matched rows, rather than only visible table
rows. Selections exceeding 10,000 rows or estimated 20 MB are refused with a prompt
to narrow filters; no partial extract is published. The table's own search/sort
is display-only: use sidebar search to change an export. Session tables show records
with matching fields. An original download contains its complete source page,
including other fields/dates for that participant. Requested resolution and range
are shown in its manifest. Gzip decompression/hash verification happens before
preparation. Vendor-generated summaries are not raw physical sensor signals.

## Private account and secret setup

The Google identity client is separate from wearable collector authorization.
It requests only `openid email profile`, without background access/refresh tokens.
Team emails live only in ignored `.private/viewer/team.json`; use the exact Google
account identities covered by participant agreement. A Google account may use a
Hotmail address. No participant names/emails are added to health tables or viewer.

1. Create a Google **Web application** OAuth client, named `Sentra team viewer`.
   Register `http://localhost:8501/oauth2callback`. Save the downloaded JSON as
   ignored `.private/viewer/google-identity-client.json`. Do not reuse the collector
   client. The local client and user-approved three-account allowlist are prepared.
2. `viewer_setup prepare` decrypts only `.private/shared/viewer.enc` and writes
   ignored `.streamlit/secrets.toml`. This plaintext local file contains restricted
   credentials: keep OS access private. It excludes collector/admin credentials,
   wearable tokens, encryption keys and local health files.
3. Google validates identity through Streamlit's OIDC handling (state/nonce).
   The app additionally requires an exact allowlisted email, `email_verified=true`,
   Google's issuer and an unexpired identity token. Streamlit's 30-day identity
   cookie does not extend the token expiry: sign out/in when access expires.
4. Every database read, object preparation and download render rechecks access.
   Denied/expired users get no data queries or files. Sign-out remains available
   so they can choose the correct account. Remove an email from managed secrets
   and restart the app to revoke further access. Data already received/downloaded
   cannot be recalled; other open tabs must rerun to see revocation.

Health data is held only in each authorized session's memory. There are no shared
data caches, health-data disk exports, public object/signed download links or server
media URLs for files. Download bytes are placed in a fixed, escaped HTML iframe's
data link only after authorization, so there is no separate URL an unlisted visitor
can request. No vendor HTML is executed. Downloads remain on the teammate's device;
they are responsible for keeping these private. Unexpected errors are sanitized.

## Reproduce the free private deployment

[Community Cloud sharing](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app)
supports one private app. Apps from private repositories default to private, and
invited viewers can invite others. The application allowlist remains the authority
even when repository developers or other platform-invited viewers reach the app.

1. Publish reviewed code after the user's commit/push approval. Choose the reviewed
   branch in Streamlit; deploying `ETL-pipeline` avoids a needless merge into main.
   Entrypoint: `viewer/app.py`; Python **3.11**. `viewer/requirements.txt` takes
   precedence over the root package definition; it pins viewer/cloud dependencies.
   The deployed runtime is Python 3.11.17. The host replaced pinned PyArrow 25.0.1
   with 24.0.0, citing its known-segfault mitigation; acceptance checks used this
   effective runtime. Preserve this detail when comparing local and hosted behavior.
2. Choose the actual available app subdomain. Register its exact
   `https://APP.streamlit.app/oauth2callback` on the **identity** client, preserving
   the localhost callback, and save its updated JSON privately.
3. Run `python -m sentra.viewer_setup prepare --url https://APP.streamlit.app`.
   Upload only `.private/viewer/secrets.cloud.toml` through the host's managed Secrets
   field. Never upload `.private`, the vault key or collector/admin bundles.
4. Keep **Only specific people can view this app**. The owner must connect private
   GitHub access when requested; Streamlit creates a read-only deploy key, although
   its legacy OAuth permission requests the broader `repo` scope. The owner reviews
   that grant. No automatic invitation emails are sent by Sentra; the operator can
   add consented platform viewers and share the link with the named team.
5. Verify a listed teammate can inspect a known selection and download its CSV and
   original. In a signed-out browser verify private-host denial. Also verify a
   signed-in unlisted account cannot see tables/downloads. Keep deployment logs
   private and do not print secret settings or response payloads for debugging.

The [deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
cover managed secrets and Python selection. Community Cloud apps
[hibernate after 12 idle hours](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
and an authorized viewer can wake them. Hibernation does not stop the separate
GitHub collector. Do not use paid hosting or keep-alive polling. The
[platform limits](https://docs.streamlit.io/deploy/streamlit-community-cloud/status)
include constrained shared resources and host overrides for telemetry/configuration;
local `gatherUsageStats=false` is not a promise that platform analytics are disabled.

## Interpret collection and capacity evidence

Coverage records mean requested intervals/pages were successfully stored. They do
not prove every expected sensor reading was delivered. The app separates returned
nulls, unmapped/non-numeric fields, unscored sessions, provisional records and
failed-fetch run evidence. Unsupported datasets are labelled only when provider
documentation/error evidence establishes that condition; no matching rows alone
does not establish it. WHOOP continuous heart rate remains unavailable through
its public API; empty tables do not fill that gap.

Observed intervals are computed within each metric/unit/resolution from distinct
returned timestamps. Gaps exceeding 1.5 times a stated aggregation interval are
candidates for inspection; device wear, sync delay and other causes remain unknown.
Daily civil summaries and session summaries do not claim continuous sampling.
Recent/provisional status is preserved conservatively; records do not become final
merely through age. Provider-wide run status is separate from dataset last success.

Viewer database/Storage reads reserve conservative egress before network transfer.
Reservations use a separate autocommit connection, so failed read transactions cannot
undo the allowance for bytes already transferred.
The viewer can call only an aggregate status function and the capped reservation
function; it cannot read/modify private budget/control/token tables. Current safety
ceilings remain 350 MB DB / 700 MB objects (20 MB reserve), 3.5 GB monthly egress.
A stale/missing/exhausted baseline stops reads/downloads and directs the operator to
verify organization usage. The app reports snapshots from the last load, not live
billing. No silent deletions, quota increases, upgrades or paid subscriptions.

## Notion documentation

Keep the viewer link on the private Sentra project page; linking it does not grant
access. Add links to this guide and the [data dictionary template](data-dictionary.md).
Document metric/provider/dataset, vendor name/definition, standardized/vendor units,
value kind, timing basis, requested/observed resolution, supported history, observed
coverage/delay, source endpoint and interpretation limits. Link a source manifest ID
or approved private extract rather than copying health records into Notion. Keep
findings labelled preliminary; the three-day observation has not started.

## Verification evidence

- Pure authorization/date/CSV/download/sampling contracts: synthetic RED → GREEN.
- Reader size/search/access/budget and viewer-only secret contracts: synthetic tests.
- Real Streamlit app tests: allowed rendering/prepared downloads, unlisted/logged-out/
  unverified/expired denial without reads, filter clearing and expiry clearing.
- Live synthetic transaction: civil/nested dates, Beirut midnight, interval overlap,
  literal search, actual viewer denial of writes/private tables; health fixtures
  rolled back. Supabase's postgres cannot assume restricted roles, so synthetic
  filter SQL uses the rollback admin transaction; permissions use the actual login.
- Actual selected 7 October rows: 9 Google daily-steps fields, 26 WHOOP sleep fields,
  matching CSV counts/exact numeric text/selection/source IDs and verified originals.
  Google/WHOOP record counts remain 61,656 / 137. No real data committed as fixtures.
- At that check: DB 268.9 MB, originals 0.657 MB, conservative reserved egress 1.818 GB.
  Later checks consume additional allowance. Observation remained disabled.
- All 101 tests passed with both hosted check groups enabled; compile/dependency,
  SQL and known credential/email checks passed. Independent review findings were
  reproduced and fixed, including a live rollback reservation regression.
- Local browser rendered synthetic tables/charts and protected CSV/gzip data links;
  rendered bytes matched fixtures. Real owner-account Google OIDC sign-in succeeded
  locally and on the deployed app, using the separate identity client.
- Hosted Google selection: p01 / google_health / daily_steps / All returned fields /
  7 October 2026. Chrome saved both files to the authorized owner's Downloads:
  CSV 5,702 bytes / 9 fields, original gzip 184 bytes. Saved CSV bytes exactly
  matched the backend selection; decompressed original SHA-256 matched its manifest.
  Browser event capture timed out despite successful file saves, so filesystem
  comparisons established acceptance. Private evidence/downloads remain ignored.
- Hosted WHOOP selection: p02 / whoop / sleep / All returned fields / 7 October
  2026. Chrome saved a CSV containing 26 fields from one sleep session; saved bytes
  exactly matched the backend selection. Switching participant cleared the previous
  prepared Google extracts when the server rerun completed.
- Hosted sharing remained private. An anonymous session received HTTP 404 from the
  protected app frame (`/~/+/`), while the owner could load the real data. The outer
  frontend shell can return HTTP 200 and is not evidence of health-data access.
  Actual local unlisted-account OIDC denial and synthetic unlisted/unverified/
  expired denial checks complement this test; no real hosted unlisted account was used.
- The host received only restricted viewer credentials, the identity client secret
  and the allowlist. No collector/admin secrets or wearable tokens were uploaded.
  Detailed evidence is in the [execution ledger](stage-5-plan.md).

Stage 5 acceptance is complete. Stage 6 will validate broader pipeline
failure/reconnect/backup and end-to-end operations after explicit stage approval.
