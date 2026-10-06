# Working on Sentra

## Setup (once)

```powershell
git clone https://github.com/<org>/sentra.git
cd sentra\wearables-pipeline
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pip install pre-commit
cd ..
wearables-pipeline\.venv\Scripts\pre-commit install     # blocks data/secrets before they are committed
```

Credentials (`secrets/`) and the database (`data/`) are shared outside git (ask Mohamad); never commit them.

## Branches

| Branch | Purpose | Who writes to it |
|---|---|---|
| `main` | Released, demo-ready. Every merge publishes `backend:latest` and (if enabled) deploys the backend. | PRs from `develop` (or `hotfix/*`) only |
| `develop` | Integration branch for the sprint. Every merge publishes `backend:develop`. | PRs from feature branches |
| `feat/<short-name>` | One task / issue | You |
| `fix/<short-name>` | Bug fix on `develop` | You |
| `hotfix/<short-name>` | Urgent fix branched from `main`, merged into `main` **and** `develop` | You |
| `chore/`, `docs/`, `ci/` | Tooling, docs, pipelines | You |

Both `main` and `develop` are protected: no direct pushes, PR + green CI + 1 review, squash merge.

## Flow

1. Pick or open an issue (Task / Bug template). Sprint = one GitHub milestone per week.
2. `git switch develop && git pull` then `git switch -c feat/<short-name>`.
3. Commit in small steps. Message style: `feat(ingest): add Garmin sleep`, `fix(api): ...`, `ci: ...`.
4. `git push -u origin feat/<short-name>` and open a PR **into `develop`**. CI must be green.
5. One teammate reviews. Squash-merge. The branch is deleted automatically.
6. Release (end of sprint / before a demo): PR `develop` -> `main`, merge commit, tag `vX.Y.Z`.
   That publishes the backend image and, if deploys are enabled, updates the backend PC.

## Tests

```powershell
cd wearables-pipeline
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
```

Tests use fake API responses and temporary folders only. If you need sample data, generate it in the test
(see `tests/test_worker.py`) or add a tiny synthetic file under `tests/fixtures/`. Never real people's data.

## Where things go

| Change | Place |
|---|---|
| New device / API | `wp/ingest/<vendor>.py`, map to the canonical metrics in `wp/canonical.py`, write with `sync.UPSERT_*` |
| New feature or flag | `wp/process/pipeline.py`; thresholds in `wp/thresholds.json` (medical expert signs off) |
| New endpoint | `wp/api.py` (read-only; ask the worker for work through `worker.request_sync`) |
| Ops / deployment | `docker-compose.yml`, `.github/workflows/`, `docs/DEPLOYMENT.md` |
