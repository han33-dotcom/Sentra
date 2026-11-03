# Self-service participant enrollment

Task [#28](https://github.com/han33-dotcom/Sentra/issues/28), with the hosted
connection work in [#47](https://github.com/han33-dotcom/Sentra/issues/47).
Owner: Hassan (`han33-dotcom`); independent reviewer: `MohamadNasrallah`.

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
the encryption key. Existing legacy accounts are not silently linked to a newly
authenticated identity; verifying/linking those needs an explicit operator migration.

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
   existing 3.5 GB egress budget and stop before the existing 380 MB working ceiling.
   Missing/stale budgets fail closed. Do not raise budgets or enable paid hosting.
7. Verify actual signup, returning sign-in, sharing, both providers, failed/cancelled
   authorization, mobile behavior and withdrawal against the hosted origin before
   advertising it as operational. Private provider app configuration, live OAuth,
   deployed access enforcement and real-device timing need separate verification.

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
service does not yet have verified processing eligibility; it never infers an
assessment from arbitrary readings or registration. Processing eligibility belongs
to #45/#49. Organization-facing views/downloads still require #27's shared access
enforcement; a completed enrollment does not certify that separate release.

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
