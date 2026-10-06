# wearables-pipeline (FYP)

Stage 1 - extraction: pulls Fitbit / Pixel Watch data for each connected Google account
through the Google Health API, every 15 min, into `data/wearables.db`.
Stage 2 - processing: clean -> 1-minute grid -> daily features -> personal baselines ->
flags -> group view. Runs on live data or on the public Kaggle Fitbit dataset.

    # Windows, first time: double-click SETUP_WINDOWS.bat (does everything below for you)
    # Every few days, when the sign-in reminder pops up: double-click REAUTH.bat

    pip install -r requirements.txt

    # Stage 2 on public data (no Google setup needed)
    python -m wp download-kaggle
    python -m wp load-kaggle
    python -m wp process --source kaggle        # charts land in reports/kaggle/

    # Stage 1 on our own accounts (needs secrets/client_secret.json)
    python -m wp import-export C:\Users\user\Desktop\fitbit mohamad   # history already pulled
    python -m wp connect mohamad                # open link, Allow, paste the google.com address back
    python -m wp connect friend1
    python -m wp sync                           # once
    python -m wp worker                         # keep it running: sync every 15 min, refresh outputs on new data
    python -m wp update [--force]               # one round (what the hourly scheduled task does)
    python -m wp trigger whoop                  # ask a running worker to sync now
    uvicorn wp.api:app --port 8000              # read API (needs WP_API_KEY), docs at /docs
    python -m wp accounts                       # status, days until sign-in expires
    pythonw run_sync.py                         # what the scheduled task runs (logs in data/logs)
    python -m wp process --source live --age mohamad=22 friend1=22

    pip install -r requirements-dev.txt && ruff check . && python -m pytest

Thresholds in `wp/thresholds.json` are placeholders until the medical expert session.
`data/` and `secrets/` hold personal health data and credentials: never commit them.

Backend loop, Docker and CI/CD: see the repo root `README.md` and `docs/DEPLOYMENT.md`.
