# Working on Sentra

## Setup (once)

Use Python **3.11**. From the repository root in Windows PowerShell:

```powershell
git clone https://github.com/han33-dotcom/Sentra.git
cd Sentra
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-windows.txt
.venv/Scripts/python.exe -m pip install --no-deps -e ".[dev,viewer]"
.venv/Scripts/python.exe -m pip install "streamlit[auth]==1.65.0" "Authlib==1.8.0" pytest pre-commit
.venv/Scripts/python.exe -m pip check
.venv/Scripts/pre-commit.exe install     # blocks data/secrets before they are committed
```

Cloning gives no access to participant data or tokens. Operator configuration
(`config/local.toml`, `.private/`, Streamlit secrets) and encryption keys are created
locally per the stage guides and are never committed.

## Branches

| Branch | Purpose | Who writes to it |
|---|---|---|
| `main` | Released, demo-ready state. | PRs from `develop` only |
| `develop` | Integration branch. | PRs from work branches |
| `feat/<short-name>` | New dataset, feature or module | You |
| `fix/<short-name>` | Bug fix | You |
| `chore/`, `ci/`, `docs/` | Tooling, pipelines, documentation | You |

`main` and `develop` are protected: no direct pushes, a PR with green `guard` and
`test` checks and one approving review. Work branches are squash-merged and
deleted automatically.

## Flow

1. `git switch develop && git pull`, then `git switch -c feat/<short-name>`.
2. Commit in small steps with conventional messages: `feat: add sedentary-period dataset`,
   `fix: ...`, `ci: ...`, `docs: ...`, `chore: ...`.
3. `git push -u origin feat/<short-name>` and open a PR **into `develop`**. CI must be green.
4. One teammate reviews. Squash-merge.
5. Release (end of sprint / before a demo): PR `develop` → `main`.

Merging or deploying code never authorizes restarting collection. The daily
collector (`.github/workflows/collect.yml`) stays paused until the team agrees and
both controls described in the [operating guide](docs/operating-guide.md) are set.

## Tests

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe scripts/check_no_data.py
```

Tests use synthetic API responses and temporary folders. Live integration tests
(`tests/test_*_live.py`) run only when `SENTRA_LIVE_TESTS=1` or `SENTRA_TEST_CLOUD=1`
is set with operator configuration; CI never sets them. Never put real people's
data in a test; build synthetic responses in the test or under `tests/fixtures/`.

## Where things go

| Change | Place |
|---|---|
| New provider dataset | `src/sentra/datasets.py` (job plan), `normalize.py` / `metric_dictionary.py`, `docs/data-dictionary.md` |
| Storage / schema | `sql/NNN_*.sql`, `src/sentra/cloud_store.py`, `docs/schema.md` |
| Collection / recovery | `src/sentra/cloud_collect.py`, `cloud_run.py`, `daily_plan.py`, `recovery.py` |
| Viewer | `src/sentra/viewer_*.py`, `viewer/app.py` |
| CI / repo rules | `.github/`, `scripts/check_no_data.py` |
