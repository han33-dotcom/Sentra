# Stage 1: foundation and authorization

**Stage 1 acceptance checks passed on 8 October 2026; awaiting user review.** Google Health API is enabled in
`sentra-510913`. Both participants' team-data agreement was confirmed by the user
on 7 October 2026. Google Health and WHOOP authorization, populated samples and
renewal are demonstrated. No health data, credentials
or consent documents are committed. No Supabase, scheduler or viewer is deployed.

On 8 October 2026, the user created the Google Web application client and saved
its JSON in the ignored private directory. `sentra check-config google_health`
passed the project, callback and credential-structure checks without displaying
credentials. After user setup, direct Console inspection confirmed External/Testing,
two test users and exactly the three read-only Google Health scopes below. The
participant completed browser authorization. A real identity-linkage check and
step-data request succeeded with HTTP 200 and **3 records**. Explicit token renewal
succeeded, and a fresh process using the persisted renewed token again received
HTTP 200 and **3 records**. Both sample pages reported more pages, so history
completeness is not demonstrated. The encrypted responses/manifests decrypt and
their original-byte hashes and counts match. No health values, identity values or
credentials are included in this evidence report.

The WHOOP client file passed validation, and the participant completed browser
authorization using `http://localhost:8765/callback`. A real cycle request returned
HTTP 200 and **1 record**. Explicit token renewal persisted replacement credentials,
and a fresh process using them again returned HTTP 200 and **1 record**. Both pages
reported more data; no pagination or complete history is demonstrated. Encrypted
source hashes and record counts match for both providers. The 16 synthetic tests,
dependency consistency and Git whitespace/private-file exclusion checks passed.
An additional Google sample automatically renewed its expired access token and
returned HTTP 200 with **3 records**, demonstrating the normal renewal path.

## Install and review

Use Python 3.11 or newer. From the repository root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\sentra.exe --help
Copy-Item -LiteralPath config/example.toml -Destination config/local.toml
New-Item -ItemType Directory -Path .private -Force
```

The existing `.venv` is already installed on this workspace. `config/local.toml`
and `.private` have been created, and the agreement flags are true based on the
user's confirmation. The encryption key was initialized in Windows Credential
Locker. Both provider clients and authorizations are present and validated. Do not
overwrite your local configuration if it already exists. No activation or
PowerShell execution-policy change is needed. For another Windows checkout,
use the tested dependency snapshot:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Review [schema.md](schema.md) and [SQL](../sql/001_foundation.sql). PostgreSQL syntax
is parsed locally; execution, constraints and permission behavior need a real
database in Stage 3. These files are not applied automatically.

The CLI supports configuration checks, OAuth authorization, one small sample and
one explicit renewal check. It does not import history or run daily jobs.

## Participant agreement and private files

Assign `p01` to Fitbit/Google Health and `p02` to WHOOP. Keep a private record of
which person owns each ID and exactly which team members may view/download which
datasets. Record retention and withdrawal arrangements outside Git. OAuth consent
is separate from this team agreement. The user confirmed agreement for both;
the team must retain the details privately and revisit them if team access changes.

Set `team_data_agreement = true` for each agreed participant in
`config/local.toml`. Revocation means set it false and stop using that connection;
disconnect in the provider account as appropriate. No automated deletion occurs.
Supervisor approval remains necessary before treating samples as research findings.

Client JSON files live in `.private`, which Git ignores. These initial setup
files contain client secrets in plaintext: use a private OS account/directory,
never a shared/synced folder, and do not copy them into chat, Notion, screenshots,
logs or extracts. Tokens and sample responses are encrypted with Fernet; the
key stays in the OS credential store and is never printed. Supported stores are
Windows Credential Locker, macOS Keychain and Linux Secret Service. Only Windows
has been checked here. A missing/plaintext/chained backend fails closed.

```powershell
.\.venv\Scripts\sentra.exe init-vault
```

The key is per local OS user. Do not copy encrypted files to another computer
and expect them to decrypt. Loss of this key requires provider reconnect and
loses access to the local encrypted samples. Shared secure token persistence,
backup and collector-only access are Stage 3 work; Actions will not use this
desktop keyring. The future viewer must never have this key or token files.

## Google Health: configure the enabled Sentra project

1. Open [Google Auth Platform for Sentra](https://console.cloud.google.com/auth/overview?project=sentra-510913).
   Configure the consent application as **Sentra**, use the owner's contact
   details, select External and keep Testing for the initial sample. Do not
   enable billing or a free trial.
2. In Audience, add the Google account used by your Fitbit/Google Health app as
   a test user. This may differ from the Cloud owner account.
3. In Data Access, add exactly these scopes:

   ```text
   https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly
   https://www.googleapis.com/auth/googlehealth.sleep.readonly
   https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly
   ```

4. In Clients, create an OAuth client of type **Web application**. Register this
   exact authorized redirect URI (including host, port and path):

   ```text
   http://localhost:8765/callback
   ```

5. Download its client JSON privately to `.private/google-client.json`. It must
   contain a `web` section with `client_id`, `client_secret`, `project_id` and `redirect_uris`.
   The CLI verifies the project matches `sentra-510913` in local configuration.
   Do not paste its contents into chat. No browser JavaScript origin is required
   for this server-side local callback. Do not use the documentation's example
   `https://www.google.com` callback for this program.
6. Sign into the Google Health mobile app using that Google account and confirm
   your Fitbit data is linked/synced. Then run:

   ```powershell
   .\.venv\Scripts\sentra.exe check-config google_health
   .\.venv\Scripts\sentra.exe authorize google_health
   .\.venv\Scripts\sentra.exe sample google_health
   .\.venv\Scripts\sentra.exe refresh google_health
   .\.venv\Scripts\sentra.exe sample google_health
   ```

Authorize opens the system browser. The participant chooses the account and
grants access; the agent does not enter passwords or click consent on their
behalf. The listener binds only to `127.0.0.1`, waits up to five minutes, validates
state and uses PKCE. Callback codes and token responses never appear in logs.

Google offline access is requested with `access_type=offline`; reconnect uses
`prompt=consent` to obtain a refresh token. Testing refresh tokens expire after
seven days. Publishing status must be changed only through an appropriate account
review; do not claim unattended collection beyond token expiry works in Testing. If publishing
is unavailable, a weekly participant reconnect is a real operational dependency.
Refresh tokens can also be revoked. Change `publishing_status` only after the
Console status changes, then reauthorize to obtain new credentials.

Sample checks identity linkage without saving/displaying identity values, then
requests at most five step records from **yesterday in Asia/Beirut**, restricted
to Google/Fitbit wearables. It saves unchanged response bytes, compressed and
encrypted, with an encrypted manifest. This is API data, not physical sensor data.
One HTTP 200 with zero records proves an authenticated request but not that any
measurement was retrieved. A populated sample is required for the real-data
demonstration. Missing yesterday data needs sync/window investigation, not a
fictional success. No next page is fetched in this stage.

Official references: [setup and token behavior](https://developers.google.com/health/setup),
[identity](https://developers.google.com/health/reference/rest/v4/users/getIdentity),
[data-point listing/filter parameters](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list).

## WHOOP: friend performs account setup

The existing member should open the [developer dashboard](https://developer-dashboard.whoop.com/),
create a developer team and **Sentra** Sandbox app, supply the required contact/app
details, and choose `read:cycles`, `read:recovery`, `read:sleep`, `read:workout`.
No profile, body-measurement or write scope is requested. OAuth additionally
requests `offline` for background refresh. No new subscription or paid approval.

Use the published [Sentra Privacy Policy](https://scented-sailfish-eda.notion.site/Sentra-Privacy-Policy-3f37b9b98086819c925be83723a18bb9)
for the Privacy Policy URL and a monitored app-owner/team email for contacts.
The policy is a separate public page containing no health records or credentials.

Register `http://localhost:8765/callback` as the exact redirect for local testing.
WHOOP's public OAuth guide illustrates HTTPS/custom-scheme redirects without
explicitly guaranteeing this HTTP localhost URI. Check whether the Dashboard
accepts it; this exact URI worked for Sentra's real authorization on 8 October 2026.
If another app rejects the URI, stop and report the exact nonsecret error;
an HTTPS callback will need a reviewed free arrangement. Do not disable TLS checks,
use a public callback recorder or leak codes into a shared URL service.

The app owner puts the credentials into `.private/whoop-client.json` on the machine
performing authorization, using this structure (replace placeholders locally):

```json
{"client_id": "LOCAL_VALUE", "client_secret": "LOCAL_VALUE"}
```

Run on that participant's machine/OS account where the local vault is configured:

```powershell
.\.venv\Scripts\sentra.exe check-config whoop
.\.venv\Scripts\sentra.exe authorize whoop
.\.venv\Scripts\sentra.exe sample whoop
.\.venv\Scripts\sentra.exe refresh whoop
.\.venv\Scripts\sentra.exe sample whoop
```

The callback must reach the **same computer that runs authorize**. Do not send
the generated localhost authorization URL to a remote friend expecting your
computer to receive it. They can perform these steps on their own checkout and
report only the nonsecret command outcomes. Moving their authorization securely
to the hosted collector is Stage 3 work; do not send tokens through chat/Git.

WHOOP sample requests one cycle in yesterday's Beirut window. WHOOP cycle
boundaries are not calendar days; an empty response may need a different sample
window during account verification. Cycles/recovery/sleep/workout fields remain
vendor results, and continuous HR is unsupported.

WHOOP rotates refresh and access tokens. A per-connection local file lock prevents
simultaneous renewal on this machine. Before renewal the vault records an
in-progress/reconnect marker; only after the response is persisted does it return
the new access token. A network/persistence interruption leaves reconnect required;
it does not retry a potentially invalid old refresh token. Google can omit a
replacement refresh token; the old one is retained without resetting its original
Testing expiry. Avoid running sample/refresh commands concurrently. Distributed
locking and rotation storage in Supabase will be implemented in later stages.

Official references: [app setup](https://developer.whoop.com/docs/developing/getting-started/),
[OAuth, offline and rotation](https://developer.whoop.com/docs/developing/oauth/),
[v2 API](https://developer.whoop.com/api/).

## Failures and acceptance evidence

The CLI prints status/counts only, never tokens, callback URLs, identity values or
provider bodies. Do not enable HTTP/OAuth debug logging. HTTP failures are surfaced
without automatic sample/rotation retries. Check client/callback/scopes for an
authorization error, Google profile linkage for a missing identity, reconnect
after 401/expired/revoked credentials, and handle 403 as an access/scope issue.
Do not print the encrypted vault's decrypted contents for troubleshooting.

| Stage 1 acceptance item | Current evidence |
| --- | --- |
| Reviewable schema | Seven tables, classification/units/times/source references and separate credentials; syntax parsed, not deployed |
| Reproducible setup | Python package/config example, Windows dependency snapshot, CLI instructions; installed local environment |
| Synthetic security/failure checks | 16 tests passed; dependency consistency, CLI help and private-file Git ignore checks passed |
| Participant team agreement | User confirmed both agreed; detailed private record remains team responsibility |
| Local credential persistence | Windows Credential Locker key creation/read and encrypted roundtrip passed; synthetic token rotation saved and reread |
| Google real sample and renewal | Demonstrated 8 October 2026: identity linkage, HTTP 200 with 3 step records, explicit renewal persisted, fresh-process HTTP 200 with 3 records; both pages have more data; encrypted source hash/count checks passed |
| WHOOP real sample and renewal | Demonstrated 8 October 2026: localhost callback and browser authorization, HTTP 200 with 1 cycle record, explicit renewal persisted, fresh-process HTTP 200 with 1 record; both pages have more data; encrypted source hash/count checks passed |

Record actual demonstrated dates, record counts, empty/populated result and
successful refresh outcome here without health values or identifiers. Synthetic
tests do not count as real provider demonstrations. **Stage 1 acceptance checks
have passed.** Google Testing's seven-day refresh-token expiry remains an operating
dependency. SQL execution and permissions, shared secure storage, completeness,
daily scheduling and the viewer have not been demonstrated and belong to later stages.
No Stage 2 import starts before explicit approval. It will add pagination,
bounded history, resumable imports, normalization and duplicate/correction handling.
