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

## Flow

1. Pick or open an issue (Task / Bug template). Sprint = one GitHub milestone per week.
2. Branch from `main`: `feat/<short-name>`, `fix/<short-name>`, `chore/<...>`, `docs/<...>`.
3. Commit in small steps. Message style: `feat(ingest): add Garmin sleep`, `fix(api): ...`, `ci: ...`.
4. Push and open a PR (template fills itself). CI must be green.
5. One teammate reviews. Squash-merge. The branch is deleted automatically.
6. Merging to `main` publishes a new backend image; if deploys are enabled the backend PC updates itself.

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
