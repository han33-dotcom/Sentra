"""Read API over the processed outputs + the hooks that tell the worker new data is waiting.

    uvicorn wp.api:app --host 0.0.0.0 --port 8000

Every /api/v1 route needs the header  X-API-Key: <WP_API_KEY>.  Subjects are pseudonyms (s_xxxxxxxx);
labels, emails and tokens never leave this process.

The API never writes to the database. It only drops trigger files that the worker picks up,
so SQLite keeps exactly one writer.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from . import __version__, config, worker

app = FastAPI(title="Sentra backend", version=__version__,
              description="Wearables pipeline: sync status, daily fitness-for-shift features, cohort view.")


def require_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("WP_API_KEY")
    if not expected:
        raise HTTPException(503, "WP_API_KEY is not set on the server")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "missing or wrong X-API-Key")


def _processed(name: str) -> Path:
    return config.DATA_DIR / "processed" / "live" / f"{name}.parquet"


_cache: dict = {}


def _table(name: str) -> pd.DataFrame:
    p = _processed(name)
    if not p.exists():
        raise HTTPException(404, f"{name} not produced yet - the worker has not processed any data")
    mtime = p.stat().st_mtime
    hit = _cache.get(name)
    if not hit or hit[0] != mtime:
        _cache[name] = (mtime, pd.read_parquet(p))
    return _cache[name][1]


def _records(df: pd.DataFrame):
    return json.loads(df.to_json(orient="records", date_format="iso"))


# ------------------------------------------------------------------ public -------------------------------
@app.get("/health")
def health():
    age = worker.heartbeat_age()
    st = worker.load_status()
    return {"status": "ok", "version": __version__,
            "worker_heartbeat_sec": None if age is None else round(age),
            "last_sync_at": st.get("last_sync_at"), "last_process_at": st.get("last_process_at")}


# ------------------------------------------------------------------ protected ----------------------------
@app.get("/api/v1/status", dependencies=[Depends(require_key)])
def status():
    st = worker.load_status()
    accounts = []
    if config.DB_PATH.exists():
        import sqlite3
        con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
        try:
            cols = "subject_id, COALESCE(provider,'google'), status, last_sync_at, last_error"
            accounts = [dict(zip(("subject_id", "provider", "status", "last_sync_at", "last_error"), r, strict=True))
                        for r in con.execute(f"SELECT {cols} FROM accounts")]
        finally:
            con.close()
    return {"pipeline": st, "accounts": accounts}


@app.get("/api/v1/daily", dependencies=[Depends(require_key)])
def daily(subject: str | None = None, since: str | None = Query(None, description="YYYY-MM-DD"),
          limit: int = Query(500, le=5000)):
    d = _table("daily_features")
    if subject:
        d = d[d.subject_id == subject]
    if since:
        d = d[pd.to_datetime(d.date) >= pd.Timestamp(since)]
    return _records(d.sort_values(["subject_id", "date"]).tail(limit))


@app.get("/api/v1/cohort", dependencies=[Depends(require_key)])
def cohort(since: str | None = None):
    c = _table("cohort_daily")
    if since and "date" in c:
        c = c[pd.to_datetime(c.date) >= pd.Timestamp(since)]
    return _records(c)


@app.post("/api/v1/sync", dependencies=[Depends(require_key)], status_code=202)
def sync_now(provider: str = "all"):
    return {"queued": worker.request_sync(provider, "api")}


# ------------------------------------------------------------------ webhooks -----------------------------
def whoop_signature_ok(body: bytes, timestamp: str | None, signature: str | None, secret: str) -> bool:
    """WHOOP signs base64(HMAC-SHA256(secret, timestamp + raw body)); see developer.whoop.com/docs/developing/webhooks."""
    if not (timestamp and signature and secret):
        return False
    if timestamp.isdigit() and abs(time.time() * 1000 - int(timestamp)) > 15 * 60 * 1000:
        return False                     # replayed or badly delayed
    mac = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode(), signature)


def _whoop_secret():
    if os.environ.get("WHOOP_CLIENT_SECRET"):
        return os.environ["WHOOP_CLIENT_SECRET"]
    p = config.SECRETS_DIR / "whoop_client.json"
    return json.loads(p.read_text()).get("client_secret", "") if p.exists() else ""


@app.post("/webhooks/whoop", status_code=204)
async def whoop_webhook(request: Request,
                        x_whoop_signature: str | None = Header(default=None),
                        x_whoop_signature_timestamp: str | None = Header(default=None)):
    body = await request.body()
    if not whoop_signature_ok(body, x_whoop_signature_timestamp, x_whoop_signature, _whoop_secret()):
        raise HTTPException(401, "bad signature")
    try:
        kind = json.loads(body).get("type", "")
    except ValueError:
        kind = ""
    if kind.endswith(".updated") or not kind:      # recovery/sleep/workout updated -> pull it now
        worker.request_sync("whoop", kind)
