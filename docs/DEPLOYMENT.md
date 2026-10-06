# Deployment

Two ways to run the backend. Use **one** at a time against a given database (SQLite has one writer;
`wp.worker.RunLock` stops overlapping runs inside one data folder).

## A. Windows native (current)

The scheduled task `FYPWearablesSync` runs `run_sync.py` every hour. Each run now does a full round:
sync everyone → if any device sent new or corrected data, rebuild `data/processed/live` and `data/etl` →
sign-in reminders. Status: `data/state/pipeline.json`. Log: `data/logs/sync.log`.

| Do this | How |
|---|---|
| Update now, force a rebuild | `UPDATE_ALL.bat` (= `python -m wp update --force`) |
| Get the latest code from GitHub | `UPDATE_CODE.bat` (git pull + pip install) |
| Re-sign someone in | `REAUTH.bat` |

## B. Docker Compose (pilot / demo server)

```powershell
copy .env.example .env          # set WP_API_KEY, SECRETS_DIR (absolute path is fine)
docker compose up -d --build    # worker + api on http://localhost:8000
docker compose logs -f worker
```

Move the existing database into the Docker volume once (stop the Windows task first: `schtasks /Change /TN FYPWearablesSync /DISABLE`):

```powershell
docker compose up -d --no-start
docker run --rm -v sentra_wp-data:/data -v "${PWD}\wearables-pipeline\data:/src:ro" alpine cp /src/wearables.db /data/
docker compose up -d
```

## Automatic deploys on every merge to main

CI publishes `ghcr.io/<org>/<repo>/backend:sha-xxxxxxx`. The `deploy` job rolls it out on the backend PC through a
self-hosted runner, then waits for both healthchecks.

1. GitHub → repo → Settings → Actions → Runners → **New self-hosted runner** → Windows. Follow the commands,
   give it the extra label `sentra-backend`, and answer **yes** to "run as service".
2. Put the server's `.env` somewhere outside the repo, e.g. `C:\sentra\.env` (with an absolute `SECRETS_DIR`).
3. Repo → Settings → Secrets and variables → Actions → Variables:
   `DEPLOY_ENABLED = true`, `DEPLOY_ENV_FILE = C:\sentra\.env`.
4. Optional: Settings → Environments → `production` → required reviewers, if a human should approve each deploy.

Docker Desktop must be running on that PC. The project name is fixed (`sentra`), so the data volume survives every deploy.

## Real-time WHOOP updates (webhook)

Polling every 15 min already catches everything. For near-instant WHOOP updates:

1. Cloudflare Zero Trust → Tunnels → create a tunnel → public hostname → service `http://api:8000`. Copy the token
   into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`, then `docker compose --profile public up -d`.
2. WHOOP developer dashboard → your app → Webhook URL `https://<hostname>/webhooks/whoop` (model version v2).
3. On `recovery.updated` / `sleep.updated` / `workout.updated` the API drops a trigger and the worker syncs WHOOP
   within ~20 s; the processed outputs follow under the normal refresh rule.

Google Health data has no push channel in our setup, so it stays on the 15-minute poll.

## API

| Route | Auth | Returns |
|---|---|---|
| `GET /health` | none | version, worker heartbeat, last sync / refresh |
| `GET /api/v1/status` | `X-API-Key` | pipeline status + accounts (pseudonyms only) |
| `GET /api/v1/daily?subject=&since=` | `X-API-Key` | daily features + flags |
| `GET /api/v1/cohort?since=` | `X-API-Key` | k-anonymous group view |
| `POST /api/v1/sync?provider=` | `X-API-Key` | queue a sync now (202) |
| `POST /webhooks/whoop` | WHOOP signature | queue a WHOOP sync (204) |

Interactive docs: `http://localhost:8000/docs`.
