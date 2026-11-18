# Read API and Docker Compose

Ported from `archive/monorepo-v0:wearables-pipeline/wp/api.py`. The SQLite ingestion,
sync worker, WHOOP webhook, sync trigger and Windows `.bat` scripts were **not** ported.
Hasan's GitHub Actions collector (`collect.yml`, paused) is the only collector.

```
GitHub Actions collector -> Supabase audit tables --(operator: sentra tiers-build)--> sentra-tiers bucket
      --(processing container, viewer role)--> /data/processed --(API container, read-only)--> clients
```

## API

All `/api/v1` routes require authentication. Only `GET` routes exist. API responses,
including denied requests, carry `Cache-Control: no-store`.

- **Team operator:** `X-API-Key: <SENTRA_API_KEY>` (at least 32 characters, compared in
  constant time) retains the existing complete operator scope. Never give this key
  to organization users.
- **Organization officer/reviewer:** `Authorization: Bearer <individual credential>`.
  Each credential identifies one operator-verified account. The API reads that
  account's current roles and consent on every request and calls `sentra.access.resolve`,
  the viewer's shared authorization module. There is no client-selected organization
  or team fallback. Inactive, unknown and ambiguous accounts are denied before data
  files are read. Changing sharing, withdrawing or removing a role affects the next
  request. Previously delivered downloads cannot be recalled.

Organization `/subjects`, `/daily` and metadata cover only currently permitted
individuals. Unknown producer columns are excluded from organization downloads.
The organization cohort is recomputed from that organization's current consenting
contributors, including group-only participants, never from the global cohort file.
Devices remain separate; rows with fewer than five people are omitted and each
statistic's count/value is hidden below five eligible contributors. Organization
metadata never returns global participant counts or date ranges.

| Route | Returns |
| --- | --- |
| `GET /health` | Liveness and which processed files exist; no rows, no auth |
| `GET /api/v1/metadata` | Wellness notice, `assessment_version` of the processed outputs, thresholds and their status (`v0 — pending medical expert sign-off`), covered days |
| `GET /api/v1/subjects` | Pseudonymous participant IDs (`p01` …) |
| `GET /api/v1/daily?subject=p01&since=YYYY-MM-DD&limit=500` | Daily wellness features plus the notice |
| `GET /api/v1/cohort?since=YYYY-MM-DD` | k-anonymous group statistics, one row per date and `device` (`Fitbit`, `WHOOP`; never pooled); rows below k are suppressed and each statistic carries its eligible count `n_<statistic>` ([contract](indicator-contract.md#group-statistics-cohort_daily)). A `cohort_daily` from before device separation returns HTTP 503 until the processing job rebuilds it |

Only IDs matching `p[0-9]{2,4}` are accepted or returned. Data comes from the processed
volume mounted read-only. Team-only operation needs no database credentials.
Optional organization mode uses restricted viewer credentials solely to read current
policy and reserve egress; it never calls provider or Storage APIs, changes consent,
refreshes outputs or starts collection. Each policy read reserves 589,824 bytes,
uses one read-only database snapshot and stops above 1,000 consent rows. Stale or
exhausted egress budgets and unavailable policy fail closed.

The processing job now persists its existing single-provider `device` provenance
in `daily_features`. Old files remain usable by team clients and organization
individual routes, but organization cohort requests return 503 until a separately
authorized processing run produces that column and its required metric inputs.
Unknown/mixed-device people never enter a device statistic. No historical readings,
units, timestamps or threshold meanings change.

## Organization credentials and setup

Organization mode is opt-in. Keep the API bound to loopback; remote exposure needs
an explicitly approved HTTPS deployment. Do not send bearer credentials over an
untrusted connection or place them in URLs. Google viewer sign-in and API credentials
are separate: a service-account login never grants application access.

1. Verify the recipient's identity and existing `org.org_users` authorization.
   Generate a unique credential with Python's `secrets.token_urlsafe(32)` and deliver
   it only to that recipient through the team's secure channel. Never reuse the
   team key, a participant provider token or another account's credential.
2. In the ignored private file `.private/api/credentials.json`, store an object
   mapping each credential's SHA-256 hex digest to `{"email": "officer@example.org",
   "expires_at": 1798761600}`. The timestamp is an example: choose a short agreed
   expiry in UTC epoch seconds (recommended at most 30 days). Store no plaintext
   bearer credentials in this file. Restrict its filesystem permissions to the operator.
3. Set `SENTRA_API_ORG_CONFIG` to the same viewer-only configuration shape as
   `SENTRA_PROCESSING_CONFIG`, preserving the current Free-plan/egress limits.
   The API refuses collector credentials. Mount the credential directory read-only
   and set `SENTRA_API_ORG_CREDENTIALS_FILE` to its container path. The optional
   `docker-compose.api-org.yml` supplies these settings without changing the default
   team-only deployment. It creates no credentials or organization roles.
4. Revoke a credential by removing its digest, or rotate by issuing a new unique
   credential and removing the old digest. Replace the file atomically in the mounted
   directory: it is reopened on each request, so revocation needs no process restart.
   Expired credentials return 401. Invalid/missing configuration returns 503 and
   never falls back to operator access. Both authentication headers together are refused.

The credential file is bounded to 64 KiB and 100 entries; duplicate JSON keys are
refused. Do not put this file, private configuration or real API responses in Git.
No real credential is provisioned by the implementation or its synthetic tests.

## Compose

Compose runs only `processing` and `api`:

- **`processing`:** `python -m sentra.processing.job`. It downloads the latest tiers with
  viewer-only credentials (`SENTRA_PROCESSING_CONFIG`; collector credentials are refused),
  reserves egress, runs the pipeline and repeats every `SENTRA_PROCESS_INTERVAL_HOURS`
  (default 24).
- **`api`:** uvicorn on `127.0.0.1:${API_PORT:-8000}`, with a read-only root filesystem and
  the processed volume mounted read-only.

```powershell
Copy-Item .env.example .env    # fill SENTRA_API_KEY and SENTRA_PROCESSING_CONFIG; .env is git-ignored
docker compose up -d --build
docker compose logs processing
Invoke-RestMethod http://127.0.0.1:8000/api/v1/metadata -Headers @{ 'X-API-Key' = '<key>' }
```

Pinned image dependencies are in `requirements-cloud.txt` and `requirements-api.txt`.

To opt into organization mode after privately preparing the above configuration:
`docker compose -f docker-compose.yml -f docker-compose.api-org.yml up -d --no-deps --build api`.
This does not authorize launching the processing job or changing collection controls.
