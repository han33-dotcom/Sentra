# Read API and Docker Compose

Ported from `archive/monorepo-v0:wearables-pipeline/wp/api.py`. The SQLite ingestion,
sync worker, WHOOP webhook, sync trigger and Windows `.bat` scripts were **not** ported.
Hasan's GitHub Actions collector (`collect.yml`, paused) is the only collector.

```
GitHub Actions collector -> Supabase audit tables --(operator: sentra tiers-build)--> sentra-tiers bucket
      --(processing container, viewer role)--> /data/processed --(API container, read-only)--> clients
```

## API

All `/api/v1` routes need `X-API-Key: <SENTRA_API_KEY>` (at least 32 characters, compared in
constant time). Only `GET` routes exist.

| Route | Returns |
| --- | --- |
| `GET /health` | Liveness and which processed files exist; no rows, no auth |
| `GET /api/v1/metadata` | Wellness notice, thresholds and their status (`v0 — pending medical expert sign-off`), covered days |
| `GET /api/v1/subjects` | Pseudonymous participant IDs (`p01` …) |
| `GET /api/v1/daily?subject=p01&since=YYYY-MM-DD&limit=500` | Daily wellness features plus the notice |
| `GET /api/v1/cohort?since=YYYY-MM-DD` | k-anonymous cohort days; days below k are suppressed |

Only IDs matching `p[0-9]{2,4}` are accepted or returned. The API has no database,
storage or provider credentials. It reads the processed volume mounted read-only.

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
