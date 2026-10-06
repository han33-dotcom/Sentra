"""API: key required, pseudonyms only, WHOOP webhook signature checked, triggers reach the worker."""
import base64
import hashlib
import hmac
import json
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wp import api, db, worker
from wp.ingest import sync

KEY = "test-key"


@pytest.fixture
def client(wp_home, monkeypatch):
    monkeypatch.setenv("WP_API_KEY", KEY)
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", "whoop-secret")
    api._cache.clear()
    return TestClient(api.app)


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_key_required(client):
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/status", headers={"X-API-Key": "nope"}).status_code == 401


def test_status_never_exposes_labels_or_emails(client):
    with db.session() as con:
        sync.register(con, "mohamad")
        con.execute("UPDATE accounts SET email='someone@example.com'")
    body = client.get("/api/v1/status", headers={"X-API-Key": KEY}).json()
    text = json.dumps(body)
    assert body["accounts"][0]["subject_id"].startswith("s_")
    assert "mohamad" not in text and "example.com" not in text


def test_daily_reads_processed_output(client, wp_home):
    assert client.get("/api/v1/daily", headers={"X-API-Key": KEY}).status_code == 404
    out = wp_home / "data" / "processed" / "live"
    out.mkdir(parents=True)
    pd.DataFrame({"subject_id": ["s_1", "s_1", "s_2"], "date": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-02"]),
                  "fatigue_level": ["green", "amber", "green"]}).to_parquet(out / "daily_features.parquet")
    r = client.get("/api/v1/daily", params={"subject": "s_1", "since": "2026-09-02"}, headers={"X-API-Key": KEY})
    assert r.status_code == 200 and [x["fatigue_level"] for x in r.json()] == ["amber"]


def test_sync_now_queues_a_trigger(client):
    r = client.post("/api/v1/sync", params={"provider": "google"}, headers={"X-API-Key": KEY})
    assert r.status_code == 202
    assert worker.pop_triggers() == {"google"}


def _signed(body: bytes, secret="whoop-secret", ts=None):
    ts = ts or str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()).decode()
    return {"X-WHOOP-Signature": sig, "X-WHOOP-Signature-Timestamp": ts, "Content-Type": "application/json"}


def test_whoop_webhook(client):
    body = json.dumps({"user_id": 1, "id": "x", "type": "recovery.updated", "trace_id": "t"}).encode()
    assert client.post("/webhooks/whoop", content=body, headers=_signed(body, secret="wrong")).status_code == 401
    old = str(int((time.time() - 3600) * 1000))
    assert client.post("/webhooks/whoop", content=body, headers=_signed(body, ts=old)).status_code == 401
    assert worker.pop_triggers() is None
    assert client.post("/webhooks/whoop", content=body, headers=_signed(body)).status_code == 204
    assert worker.pop_triggers() == {"whoop"}
