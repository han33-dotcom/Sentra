"""WHOOP API v2 connector (https://developer.whoop.com/api).

Same idea as Google: one app (secrets/whoop_client.json), each person signs in once, we keep a
refresh token (needs the `offline` scope) and pull new records on every sync.
WHOOP gives per-night / per-day summaries only (no second-by-second heart rate).
"""
import json
import secrets as pysecrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .. import config, db
from ..canonical import unit

AUTH = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer"
SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement"
SOURCE = "whoop"
ENDPOINTS = {"cycle": "/v2/cycle", "sleep": "/v2/activity/sleep", "recovery": "/v2/recovery",
             "workout": "/v2/activity/workout"}


class NeedsReconnect(Exception):
    pass


def _client():
    p = config.SECRETS_DIR / "whoop_client.json"
    if not p.exists():
        raise SystemExit(f"Missing {p}")
    c = json.loads(p.read_text())
    c.setdefault("redirect_uri", "https://www.google.com")
    return c


def token_path(label):
    return config.TOKENS_DIR / f"whoop_{label}.json"


def auth_link(label):
    c = _client()
    state = (label + "-" + pysecrets.token_hex(4))[:32]   # WHOOP wants a state of 8+ characters
    if len(state) < 8:
        state = state.ljust(8, "x")
    return AUTH + "?" + urlencode({"client_id": c["client_id"], "redirect_uri": c["redirect_uri"],
                                   "response_type": "code", "scope": SCOPES, "state": state})


def _save(label, t):
    info = {"access_token": t["access_token"], "refresh_token": t.get("refresh_token"),
            "expires_at": time.time() + int(t.get("expires_in", 3600)) - 60}
    old = token_path(label)
    if not info["refresh_token"] and old.exists():
        info["refresh_token"] = json.loads(old.read_text()).get("refresh_token")
    config.ensure_dirs()
    token_path(label).write_text(json.dumps(info))
    return info


def connect(label, code):
    c = _client()
    code = parse_qs(urlparse(code).query).get("code", [code])[0]
    r = requests.post(TOKEN, data={"grant_type": "authorization_code", "code": code, "client_id": c["client_id"],
                                   "client_secret": c["client_secret"], "redirect_uri": c["redirect_uri"]}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"WHOOP token exchange failed: {r.status_code} {r.text}")
    _save(label, r.json())
    with db.session() as con:
        from .sync import register
        register(con, label)
        con.execute("UPDATE accounts SET provider='whoop' WHERE label=?", (label,))


def _access(label):
    p = token_path(label)
    if not p.exists():
        raise NeedsReconnect(f"no WHOOP token for {label}")
    info = json.loads(p.read_text())
    if time.time() < info["expires_at"]:
        return info["access_token"]
    c = _client()
    r = requests.post(TOKEN, data={"grant_type": "refresh_token", "refresh_token": info["refresh_token"],
                                   "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "scope": "offline"}, timeout=30)
    if r.status_code != 200:
        raise NeedsReconnect(f"WHOOP refresh failed: {r.status_code} {r.text[:200]}")
    return _save(label, r.json())["access_token"]


def _get(label, path, params=None, tries=5):
    for i in range(tries):
        r = requests.get(API + path, params=params, headers={"Authorization": f"Bearer {_access(label)}"}, timeout=60)
        if r.status_code == 401:
            raise NeedsReconnect("401 from WHOOP")
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 ** i))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def list_records(label, kind, since, until=None):
    params = {"limit": 25, "start": f"{since:%Y-%m-%dT%H:%M:%S.000Z}"}
    if until:
        params["end"] = f"{until:%Y-%m-%dT%H:%M:%S.000Z}"
    while True:
        body = _get(label, ENDPOINTS[kind], params)
        yield from body.get("records", [])
        tok = body.get("next_token") or body.get("nextToken")
        if not tok:
            return
        params["nextToken"] = tok


# ------------------------------------------------------------------ mapping ---------------------------
def _local_day(ts, offset):
    """WHOOP timestamps are UTC + a timezone_offset like '+03:00' -> local calendar day as YYYY-MM-DDT00:00:00Z."""
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if offset:
        sign = 1 if offset[0] == "+" else -1
        h, m = offset[1:].split(":")
        t = t + sign * timedelta(hours=int(h), minutes=int(m))
    return f"{t:%Y-%m-%d}T00:00:00Z"


def _offset_min(offset):
    if not offset:
        return None
    sign = 1 if offset[0] == "+" else -1
    h, m = offset[1:].split(":")
    return sign * (int(h) * 60 + int(m))


def map_records(subject, kind, rec, sleep_index):
    """-> (observation rows, session row or None). Daily values are dated on the local day you woke up
    (sleep, recovery) or the day the cycle started (strain)."""
    rows, sess = [], None
    sc = rec.get("score") or {}
    scored = rec.get("score_state") == "SCORED"

    def row(metric, value, day, key):
        if value is None:
            return
        rows.append(dict(subject_id=subject, source=SOURCE, device="WHOOP", metric=metric, value=float(value),
                         unit=unit(metric), start_utc=day, end_utc=None, utc_offset_min=None,
                         resolution="daily", method="auto", quality_flag="ok", raw_ref=key))

    if kind == "sleep":
        key = f"whoop|sleep|{rec['id']}"
        sess = dict(raw_ref=key, subject_id=subject, kind="sleep", start_utc=rec["start"], end_utc=rec["end"],
                    utc_offset_min=_offset_min(rec.get("timezone_offset")), detail=json.dumps(sc))
        if scored and not rec.get("nap"):
            day = _local_day(rec["end"], rec.get("timezone_offset"))
            st = sc.get("stage_summary") or {}
            ms = lambda k: (st.get(k) or 0) / 60000  # noqa: E731
            row("daily_sleep_min", ms("total_light_sleep_time_milli") + ms("total_slow_wave_sleep_time_milli")
                + ms("total_rem_sleep_time_milli"), day, key)
            row("daily_in_bed_min", ms("total_in_bed_time_milli"), day, key)
            row("daily_deep_sleep_min", ms("total_slow_wave_sleep_time_milli"), day, key)
            row("daily_rem_sleep_min", ms("total_rem_sleep_time_milli"), day, key)
            row("daily_awake_min", ms("total_awake_time_milli"), day, key)
            row("daily_respiratory_rate", sc.get("respiratory_rate"), day, key)
            row("whoop_sleep_performance_pct", sc.get("sleep_performance_percentage"), day, key)
    elif kind == "recovery" and scored:
        key = f"whoop|recovery|{rec['cycle_id']}"
        sl = sleep_index.get(rec.get("sleep_id"))
        if sl:
            day = _local_day(sl["end"], sl.get("timezone_offset"))
            row("resting_heart_rate", sc.get("resting_heart_rate"), day, key)
            row("daily_hrv_rmssd", sc.get("hrv_rmssd_milli"), day, key)
            row("daily_spo2", sc.get("spo2_percentage"), day, key)
            row("nightly_skin_temp_c", sc.get("skin_temp_celsius"), day, key)
            row("whoop_recovery_score", sc.get("recovery_score"), day, key)
    elif kind == "cycle" and scored:
        key = f"whoop|cycle|{rec['id']}"
        day = _local_day(rec["start"], rec.get("timezone_offset"))
        row("whoop_strain", sc.get("strain"), day, key)
        row("daily_avg_hr", sc.get("average_heart_rate"), day, key)
        row("daily_max_hr", sc.get("max_heart_rate"), day, key)
        row("daily_kilojoule", sc.get("kilojoule"), day, key)
    elif kind == "workout":
        key = f"whoop|workout|{rec['id']}"
        sess = dict(raw_ref=key, subject_id=subject, kind="exercise", start_utc=rec["start"], end_utc=rec["end"],
                    utc_offset_min=_offset_min(rec.get("timezone_offset")),
                    detail=json.dumps({"sport": rec.get("sport_name"), **sc}))
    return rows, sess


def sync_account(con, label, log=print, fetch=None):
    """Pulls cycles, sleep, recovery, workouts since the last sync (minus 2 days, WHOOP re-scores recent days)."""
    from . import sync
    from .sync import OBS_COLS, UPSERT_OBS, UPSERT_RAW, UPSERT_SESSION
    fetch = fetch or (lambda kind, since: list_records(label, kind, since))
    subject = con.execute("SELECT subject_id FROM accounts WHERE label=?", (label,)).fetchone()[0]
    row = con.execute("SELECT MIN(synced_until) FROM sync_state WHERE label=?", (label,)).fetchone()
    since = (datetime.fromisoformat(row[0]) - timedelta(days=2)) if row and row[0] else \
        datetime.now(timezone.utc) - timedelta(days=config.BACKFILL_DAYS)
    started = datetime.now(timezone.utc)
    try:
        data = {k: list(fetch(k, since)) for k in ("sleep", "recovery", "cycle", "workout")}
    except NeedsReconnect as e:
        con.execute("UPDATE accounts SET status='needs_reconnect', last_error=? WHERE label=?", (str(e), label))
        con.commit()
        log(f"  [{label}] WHOOP NEEDS RECONNECT ({e})")
        return {}
    sleep_index = {s["id"]: s for s in data["sleep"]}
    counts = {}
    for kind, recs in data.items():
        before = con.total_changes
        for rec in recs:
            key = f"whoop|{kind}|{rec.get('id', rec.get('cycle_id'))}"
            con.execute(UPSERT_RAW, (key, label, f"whoop-{kind}", json.dumps(rec)))
            rows, sess = map_records(subject, kind, rec, sleep_index)
            con.executemany(UPSERT_OBS, [[r[c] for c in OBS_COLS] for r in rows])
            if sess:
                con.execute(UPSERT_SESSION, sess)
        sync.ROWS_CHANGED += con.total_changes - before
        con.execute("INSERT INTO sync_state(label,data_type,synced_until,last_count,updated_at) VALUES (?,?,?,?,datetime('now')) "
                    "ON CONFLICT(label,data_type) DO UPDATE SET synced_until=excluded.synced_until, "
                    "last_count=excluded.last_count, updated_at=excluded.updated_at",
                    (label, f"whoop-{kind}", started.isoformat(), len(recs)))
        counts[kind] = len(recs)
        log(f"  [{label}] whoop {kind}: {len(recs)} records since {since:%Y-%m-%d}")
    con.execute("UPDATE accounts SET last_sync_at=datetime('now'), status='active', last_error=NULL WHERE label=?",
                (label,))
    con.commit()
    return counts
