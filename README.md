# FYP — Wellness & Safety (Sentra)

Consumer wearables worn by a workforce → fitness-for-shift and safety signals for the institution's HSE team.
Wellness and safety signals only: no diagnosis, no medical-grade claims.

| Folder | What | Runs as |
|---|---|---|
| `wearables-pipeline/` | Backend: device sync (Google Health / Fitbit, WHOOP), processing, ETL, API, worker | Windows scheduled task **or** Docker Compose |
| `website/` | Marketing site (static, scroll-driven 3D) | GitHub Pages |
| `scripts/` | Repo tooling: data guard, GitHub setup | — |
| `docs/` | Deployment and architecture notes | — |
| `.github/` | CI/CD, templates, Dependabot | GitHub Actions |

## Project workspace

- [FYP project home and task board](https://app.notion.com/p/3e87b9b98086806d973efef0204f2e7b)
- [Plan 1](https://app.notion.com/p/3e87b9b98086819296bef0a655f38961)
- [Decisions and open questions](https://app.notion.com/p/3e87b9b9808681eaa878f5634c60801c)

Notion holds the shared plan, tasks, meetings, and decisions. This repository holds code, setup instructions, made-up example data, and reviewed changes. Link a code change from its Notion task.

## First milestone

Both Fitbit Air owners can run the same retrieval process with their own accounts. The team has a data dictionary and a short report on missing data and arrival delay. The team then chooses one FYP question and an evaluation method with supervisor input.

## How the backend stays current

```
 devices ──(phone app sync)──► Google Health API / WHOOP API
                                      │ polled every 15 min            WHOOP webhook ─► POST /webhooks/whoop
                                      ▼                                                        │ drops a trigger
                         worker: sync (idempotent upserts) ◄───────────────────────────────────┘
                                      │ rows really new or corrected?   (sync.ROWS_CHANGED)
                                      ▼ yes
                         outputs marked stale ─► process + ETL (at most every 60 min)
                                      ▼
                  data/processed/live/*.parquet ─► API  /api/v1/daily  /api/v1/cohort  /api/v1/status
```

Re-reading the overlap window writes nothing, so "changed" means a device actually sent something.
Native Windows: the hourly `FYPWearablesSync` task runs the same round (`run_sync.py` → `wp.worker.run_once`).
Docker: `docker compose up -d` runs it continuously (`python -m wp worker`) next to the API.

## Quick start

```powershell
# backend, Windows native (existing setup)
cd wearables-pipeline
.venv\Scripts\python -m wp update          # sync + refresh outputs if anything changed
.venv\Scripts\python -m pytest             # tests (pip install -r requirements-dev.txt once)

# backend, Docker (from the repo root)
copy .env.example .env                     # set WP_API_KEY
docker compose up -d --build
curl http://localhost:8000/health
```

## CI/CD

| When | What runs |
|---|---|
| Every PR / push to `develop` | data guard + gitleaks → ruff + pytest (Ubuntu 3.11/3.12, Windows 3.12) → Docker build + smoke test |
| Merge to `develop` | image published as `backend:develop` (no deploy) |
| Merge to `main` | image published to `ghcr.io/<org>/<repo>/backend:latest` and `:sha-xxxxxxx` → deploy job on the backend PC (opt-in, see `docs/DEPLOYMENT.md`) |
| Change under `website/` on `main` | site deployed to GitHub Pages |
| Tag `v1.2.3` | image also tagged `1.2.3` |

## Rules

- **No personal data in git, ever**: `data/`, `secrets/`, `reports/`, `*.db`, `*.parquet`, exports, tokens. `.gitignore`, the pre-commit hook and CI all enforce it.
- Branching: `feat/*` → PR into `develop` → release PR `develop` → `main`. Both protected (PR + green CI + 1 review). See `CONTRIBUTING.md`.

## Team working rules

- Assign one owner to each Notion task and define what "done" means.
- Work on a branch for each code change and ask a teammate to review it.
- Do not commit raw wearable records, credentials, tokens, or consent documents. Use synthetic examples in the repository.
- Confirm ethics and approved storage requirements with the supervisor before using participant data as research findings.
