# Self-service participant enrollment

Task [#28](https://github.com/han33-dotcom/Sentra/issues/28), with the hosted
connection work in [#47](https://github.com/han33-dotcom/Sentra/issues/47).
Owner: Hassan (`han33-dotcom`); optional additional reviewer: `MohamadNasrallah`.
Code delivery follows [agent-owned delivery](local-delivery.md).

## Participant experience

Send an organization invitation link. On their own phone, the participant reads
the brief explanation, chooses group-only or individual sharing, makes a separate
optional demonstration choice, confirms participation and connects Fitbit/Google
Health or WHOOP. The provider handles their password. They return to Sentra with
separate participation, connection, recent-data and assessment states.

There is no new Sentra password, local callback computer, terminal configuration,
or manual credential handoff for a participant. Opening `/join` without an invitation
lets an existing participant sign in through the same provider to manage their
sharing, reconnect, add another supported provider, sign out, or withdraw.
Sessions last 30 minutes; the same provider login works in another browser.

Participants are recorded in memberships and consent history. Do **not** add a
participant to `org.org_users`, the viewer's team-operator allowlist, or the
private viewer's hosting invitations just to let them enroll. Those grant a
different kind of access. An officer or reviewer can also be a participant, using
the same email if explicitly authorized for that organization role. Participation
does not itself grant that role; synthetic role checks use designated test access.
A participant owning the WHOOP developer app
does not make them a Sentra officer.

An invitation carries its secret in a URL **fragment**, which is not sent in HTTP
URLs. The browser removes it before starting the session and submits it in a
same-origin POST. Do not post invitations in public issues or logs. One link can
have up to five seats for this pilot; repeat sign-in on the same provider does not
use another seat. Organization names and consent records stay in private storage.

The local operator enrollment procedure proposed in PR #37 is background, not
acceptance of this participant flow.

## Architecture and boundaries

`sentra.enrollment_web:app` is a **separate FastAPI service**. The existing
`sentra.api:app` remains read-only and has neither enrollment nor provider secrets.
The Streamlit organization viewer is also separate. Do not deploy the enrollment
service inside Streamlit or add write routes to the wellness read API.

Migration `008_self_service_enrollment.sql` follows migrations 001–007 and creates:

- `sentra_enrollment`, a dedicated non-superuser/non-bypass-RLS database login;
- private, bounded invitations, encrypted browser/OAuth sessions, hashed provider
  identities and short-lived hashed rate buckets;
- narrow grants for membership, append-only consent and encrypted credentials;
- metadata-only status and active-connection-discovery functions.

This role cannot read wearable measurements, normalized records, original
responses, collector controls or organization-user accounts. The browser receives
none of the provider tokens, database credentials or provider profile identifiers.
RLS is forced on the private tables. The backend is trusted to scope each request
to its server-side session; no browser-supplied participant or organization ID is
accepted for management operations. All mutating browser requests require the
configured Origin, and authenticated mutations also require a session CSRF token.
Cookies are HttpOnly, SameSite=Lax, Secure and `__Host-` prefixed over HTTPS.

OAuth state is cookie-bound, expires after ten minutes and is consumed durably
before exchange. Google uses S256 PKCE. Scope/refresh-token checks fail closed.
The exact registered callback URLs are constructed from the configured origin;
there are no browser-supplied return addresses. Session IDs rotate after login.

Google requests `openid` in addition to the existing read-only health scopes.
Its fixed UserInfo endpoint supplies a stable `sub`. WHOOP additionally requests
`read:profile` to obtain its stable `user_id`. Names/email that WHOOP also returns
are discarded immediately; only a provider-specific HMAC of the identifier is
persisted. This is authentication, not a new wearable-data collection category.
Keep the identity HMAC key stable across replicas and restarts, and separate from
the encryption key. A manually connected Fitbit account needs a
[private Fitbit link](#link-an-existing-fitbit-participant) to start hosted participation.

Sources checked November 3, 2026: [Google UserInfo and subject identifiers](https://developers.google.com/identity/openid-connect/reference),
[WHOOP OAuth](https://developer.whoop.com/docs/developing/oauth/),
[WHOOP profile endpoint and scope](https://developer.whoop.com/api/).

## Prepare a deployment

The code and migration do not provision a public host, change provider settings,
apply migrations to the shared database, enroll real participants, or enable
collection. Before distributing real invitations:

1. Review and merge the code through `develop`. Apply 007 and 008 once to the shared
   database using the existing private operator process. Set a strong password for
   `sentra_enrollment` with a bound parameter, never in a command or repository file.
2. Choose an HTTPS enrollment origin and register these exact Web OAuth redirects:
   `https://YOUR_HOST/oauth/google_health/callback` and
   `https://YOUR_HOST/oauth/whoop/callback`. Google needs a Web application client,
   not a desktop client. These may be hosted callback entries on the same existing
   provider clients so credentials remain compatible with collection.
3. Configure Google test-user eligibility or the agreed publishing/verification
   approach, and check WHOOP member limits. The software cannot bypass provider
   restrictions. Google Testing authorizations expire after seven days; participants
   can reconnect themselves. Keep the pilot within the approved enrollment scope.
4. Set `SENTRA_ENROLLMENT_CONFIG` privately. Its JSON shape is:

   ```json
   {
     "origin": "https://YOUR_HOST",
     "db": {
       "host": "YOUR_POOLER.pooler.supabase.com",
       "port": 5432,
       "dbname": "postgres",
       "user": "sentra_enrollment.YOUR_PROJECT",
       "password": "REPLACE",
       "sslmode": "verify-full",
       "sslrootcert": "/run/sentra/database-ca.crt"
     },
     "token_key": "COPY_EXISTING_SENTRA_TOKEN_KEY",
     "identity_key": "REPLACE_WITH_A_SEPARATE_STABLE_RANDOM_KEY_AT_LEAST_32_CHARACTERS",
     "consent_version": "1.0",
     "clients": {
       "google_health": {
         "client_id": "REPLACE",
         "client_secret": "REPLACE",
         "publishing_status": "testing"
       },
       "whoop": {
         "client_id": "REPLACE",
         "client_secret": "REPLACE",
         "publishing_status": "production"
       }
     }
   }
   ```

   Only include enabled provider clients. `token_key` **must match** the existing
   collector encryption key; do not replace or rotate that key as part of setup.
   Keep all configuration, keys, certificates and backups private. Restore both
   keys and private enrollment tables for consistent identity/session recovery.

5. Run `uvicorn sentra.enrollment_web:app --host 127.0.0.1 --port 8010 --no-access-log`
   behind the chosen TLS reverse proxy, or use the standalone `compose.enrollment.yml`.
   The compose file exposes only a loopback port, mounts the database certificate
   read-only and starts no collector or processing container. Configure the actual
   trusted proxy IPs in `SENTRA_ENROLLMENT_PROXY_IPS`; never trust arbitrary forwarded
   headers. Preserve the configured Host. Disable callback URL/query logging at the
   proxy, hosting layer and APM as well as uvicorn. Cap incoming request bodies at
   8 KB and apply per-client request limits there.
6. Create the organization record privately, if absent. Run the following with
   private service configuration in the environment:

   ```text
   python -m sentra.enrollment --organization YOUR_ORG_ID --seats 5 --days 7
   ```

   The returned invitation is private. There is no public invitation-creation API.
   A maximum of 500 live sessions and 20 new sessions per ten-minute hashed client
   bucket bound this pilot's state. Database requests reserve 64 KB against the
   approved 4.5 GB egress budget and stop before the existing 380 MB working ceiling.
   Missing/stale budgets fail closed. Do not raise budgets or enable paid hosting.
7. Verify actual signup, returning sign-in, sharing, both providers, failed/cancelled
   authorization, mobile behavior and withdrawal against the hosted origin before
   advertising it as operational. Private provider app configuration, live OAuth,
   deployed access enforcement and real-device timing need separate verification.

## Link an existing Fitbit participant

Use this flow for a manually connected Fitbit participant who has an existing
Google Health credential and has never had a hosted membership or identity link.
Before issuing a link, the operator verifies the existing participant ID, original
Gmail account and intended organization from private pilot records and confirms
that the participant is eligible to make the hosted consent choices. If the
operator cannot verify the original account or the participant withdrew, stop.

Apply [migration 011](../sql/011_fitbit_link_invites.sql) after 008 using the
reviewed deployment procedure. If the release includes Follow-ups, apply 010
before 011. Apply [migration 016](../sql/016_fitbit_self_service.sql) after 011,
then deploy the updated enrollment service. It grants only the enrollment service
the narrow transition needed for a verified same-account reconnect; it does not
change any existing identity, credential or consent when applied.
Verify that the Google OAuth client can request the Google Account email scope
before issuing a live link. With the same private enrollment configuration used
by the service, run this from a private terminal:

```text
python -m sentra.enrollment --organization YOUR_ORG_ID --link-fitbit EXISTING_PARTICIPANT_ID --days 1
```

Enter the verified Gmail address at the private prompt and share the resulting
single-use link only with the participant. The participant opens it, reviews and
accepts the hosted sharing choices, and signs in with the original Fitbit Google
account. This flow requests only Google identity and email scopes, checks the
verified Gmail address against the operator's keyed digest, and discards the
OAuth token. Gmail and Googlemail variants with or without dots match the same
mailbox. Use the operator workflow for an account with a non-Gmail address.
See [Google's account ownership guidance](https://developers.google.com/identity/sign-in/web/backend-auth)
and [Gmail's address guidance](https://support.google.com/mail/answer/10313).

The callback records one membership and consent on the original participant ID.
Linking and subsequent hosted sign-ins leave the encrypted Fitbit credential
and history intact. Returning sign-in recognizes the stored Google subject.
The participant has the same sharing, withdrawal, provider-connection and reconnect
controls as someone who originally enrolled on the web. An explicit reconnect
requests health access from the same Google account, replaces the old encrypted
credential, and moves it to web self-service in one transaction. A wrong account
or failed save leaves the original connection intact. Reconnect neither creates
a second participant nor starts collection. After withdrawal, a fresh invitation
and accepted choices are required to rejoin, just as for web-created accounts.
An incorrect account, expired or used link, or a participant whose eligibility
changed fails without committing enrollment changes. A successful link consumes
the invitation. The participant can then sign in again from the ordinary account
page. Use an approved participant and a reviewed rollout to verify the live flow.
Collection remains paused through the existing controls.

Returning Google sign-in from the ordinary account page requests only `openid`
with account selection. It proves the already-linked identity, discards OAuth tokens,
and leaves collection credentials and consent unchanged. Unknown identities still
need an invitation. New enrollment and the signed-in account's explicit reconnect
continue to request the health scopes and offline access needed for collection;
this includes linked, formerly operator-managed Fitbit accounts. An unlinked
sign-in explains the one-time setup step. This identity-binding step is necessary
because the original manual connection did not store a verified web-login subject;
it is not a permanent restriction on the participant's capabilities.

## Collection integration

The collector still accepts legacy `participants: {"whoop":"p02"}` configuration.
It also accepts lists per provider, such as `{"whoop":["p02","p03"]}`. Each pair
has separate tokens, locks, checkpoints and run records. For discovery of new
self-enrolled accounts, deliberately set `include_enrolled: true` in the private
collector configuration **after** migration 008 and the readiness review. Discovery
is bounded to 100 connections and filters withdrawn/closed membership episodes.
No signup route starts collection, imports history or enables either existing
collection control. Collection restart and resource limits remain operator decisions.

Initial/recovery import supports `--participant p100`, also available as the
workflow's participant input. Select one new participant and a bounded 1–30-day
past window; adding a participant does not import history automatically. Larger
pilots must explicitly select a participant for manual imports. New participants
need a first bounded import before their daily coverage/correction planner can
operate; daily mode does not invent an unbounded historical catch-up window.

Withdrawal appends consent, closes membership and disables **all** that person's
stored provider credentials transactionally. The token vault and each HTTP retry
check the durable withdrawal state. An already in-flight provider request may
finish; subsequent attempts are refused. No readings, originals or tokens are
deleted as a side effect. A withdrawn participant can sign in to see that state,
but reconnect alone cannot restart participation; a fresh invitation and agreement
are required. Provider access can also be revoked in the provider's account settings.

Status counts distinguish enrolled, connected and recently contributing. Recency
uses actual measurement dates in Beirut (including vendor civil dates), not fetch
success. `assessable: null` and `assessment: not_available` explicitly mean this
service lacks a current verified eligibility feed; it never infers an assessment from
arbitrary readings or registration. Migration 014, after 008, adds bounded metadata
from the published #45/#49 board contract. A complete current day yields true; a
current partial/insufficient day yields false. Missing participants, stale publication
or measurement dates (older than three days), future dates and incompatible assessment
versions remain unknown. No values or medical conclusions enter enrollment storage. Organization-facing views/downloads still require #27's shared access
enforcement; a completed enrollment does not certify that separate release.

With private enrollment configuration, operators can inspect bounded counts:

```text
python -m sentra.enrollment --organization YOUR_ORG_ID --summary
```

This creates no invitation, changes no participation, and prints no identifiers,
readings or credentials. It stops above 100 participants and reserves a separate
64 KB allowance per participant before checking encrypted connection metadata.
`assessable: null` with `assessment_unknown` means processing eligibility is
unavailable; it is not a verified zero eligible participants.

## Current deployment and remaining acceptance

The participant page is https://sentra-enrollment.onrender.com/join, on Render Free in Frankfurt,
with manual deployments from `main`. The existing private viewer remains
https://sentra-wearable-audit.streamlit.app, using its retained `ETL-pipeline`
deployment reference. Both hosts were verified on release `bea825f` on November 18;
later release commits do not automatically establish the enrollment deployment.
Record the exact deployed commit when rolling out migration 016 and manual-account
self-service reconnect. Preserve the private audience,
viewer-only secrets, existing URLs and Google callbacks when deploying.

Real Google signup and returning-account sharing updates were reported on a phone
and verified privately. HTTPS, cookies, origin/body-size enforcement, hosted
database sessions and anonymous mobile OAuth cancellation passed. No participant
phone timing has been supplied. Reconnect/withdrawal with a real person remains separate from synthetic checks.
Task acceptance follows [local delivery](local-delivery.md); only observations
unavailable to the agent require human verification instructions.

Existing deployed acceptance corrections:

- The viewer rechecks organization permissions at the start of every render, so
  sharing/withdrawal changes and removed roles apply on the next page render.
  The team overview also refreshes its consent scope on each render.
  The access decision is reused within that render to bound database work. This
  does not recall data or exports already delivered to an open browser.
- Failed initial requests offer **Try again** and keep the invitation only in
  page memory until a session succeeds. API requests time out after 20 seconds;
  mutations are never automatically replayed. Reopening the original invitation
  is needed if the browser page itself is closed before session creation.
  Initialization requests are serialized so opening an invitation while a
  returning-session request is pending cannot replace the invitation with an
  older session response.
- Reconnect-required accounts are described as needing reconnect, rather than
  described as connected while waiting for data.
- Private aggregate counts preserve the difference between an unavailable
  assessment result and a verified zero.

Further changes require implementation-agent self-review, acceptance, CI and release
under [agent-owned delivery](local-delivery.md), plus verified deployment. Synthetic tests use fake accounts/records and an isolated
loopback PostgreSQL database; they grant no real person organization access.

Operational prerequisites still open:

- **WHOOP:** the app is implemented but is not enabled on the current Google-only
  host. On November 18, the owner authorized adding
  `https://sentra-enrollment.onrender.com/oauth/whoop/callback`; the saved app now
  lists it alongside localhost, preserving existing read-only scopes including
  `read:profile`. Sandbox showed 1 of 10 members and limits of 100 requests/minute
  and 10,000/day. The approved public privacy notice was subsequently saved in the
  provider settings under SEN-26. Hosted enablement and participant authorization remain separate;
  no live sign-in or provider-data request was performed. WHOOP
  requires membership for developer access, so a free account alone is not an
  alternative. See [WHOOP requirements](https://developer.whoop.com/docs/developing/overview/)
  and [redirect/team configuration](https://developer.whoop.com/docs/developing/getting-started/).
- **Assessment:** migration 014 and the bounded enrollment-facing eligibility feed
  from #45/#49 are deployed. Missing or stale publications still mean unknown.
  Do not infer insufficient history, readiness or a wellness result from signup,
  credential presence, last fetch time or arbitrary readings.
- **Availability:** Render Free sleeps after inactivity. A November 3 return
  visit timed out and required a restart; successful warm-page checks do not
  prove reliable cold starts. A retry button cannot repair an unreachable HTML
  host. Retain the zero-spend constraint; no paid upgrade or periodic keepalive
  has been enabled.
  A November 4 check after more than 15 minutes idle returned health HTTP 200 in
  36.95 seconds without a restart. This verifies that wake-up succeeded once,
  while still demonstrating a delay that participants must allow for.
- **Organization-hosted acceptance:** use an explicitly designated organization
  test identity. The earlier participant-only account clarification must be
  respected; participants do not receive officer privileges for this test.

Collection remains paused; these enrollment checks do not enable a first import.

## Verification

Ordinary tests use synthetic HTTP/provider responses. Real database tests are
opt-in and create/drop a new `sentra_enrollment_test_*` database **only** on a
loopback PostgreSQL test server, with stand-ins for Supabase auth/storage:

Install `requirements-api.txt` and `httpx` in the configured development environment
for the HTTP tests. The collector-only environment can skip those optional tests.

```powershell
$env:SENTRA_TEST_ENROLLMENT_DSN = 'host=127.0.0.1 port=55448 dbname=postgres user=postgres'
.venv/Scripts/python.exe -m pytest tests/test_enrollment.py tests/test_enrollment_postgres.py -ra
Remove-Item Env:SENTRA_TEST_ENROLLMENT_DSN
```

Never point this fixture at the real project. Test roles are cluster-wide, so use
an isolated local cluster. Tests exercise replay, CSRF, expiry, seat/identity races,
cross-organization linking, reconnect/account substitution, consent history,
withdrawal during retries, role privileges and credential encryption. CI runs the
protocol/HTTP tests; the disposable PostgreSQL fixture is skipped unless opted in.

### Published eligibility feed (sql/014)

The wellness refresh publishes the board first, then replaces at most 100 eligibility
rows through one collector-only function. The metadata contains participant pseudonym,
day and completeness, plus the publication time/version/digest. Enrollment can execute
only a bounded per-participant summary, and no runtime role can read/write the metadata
tables directly. This adds no access to readings. Failure leaves eligibility unknown or
its prior dated state; retrying an unchanged board repairs the feed without rebuilding
tiers. Older or conflicting publications are rejected. An absent migration retains the
existing unknown state. The feed is derived and can be rebuilt after recovery from the
current board; it is not consent or a new authoritative health record.
