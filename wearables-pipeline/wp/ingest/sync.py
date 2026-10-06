"""Incremental, idempotent sync.

Why this design handles the "every 15 min" problem:
  * The watch uploads in bursts when it syncs with the phone. A burst can contain hours of
    5-second heart rate, and can arrive late.
  * Each run asks for everything since (last cursor - OVERLAP_HOURS). Re-reading the overlap
    catches late bursts; upserting on the record's unique `name` makes duplicates harmless.
  * So running every 15 min, every hour, or once a day gives the SAME final data;
    only the delay changes.
"""
import hashlib
import json
import time
from datetime import datetime, timedelta

from .. import config, db
from .google_health import DATA_TYPES, GoogleHealthClient, NeedsReconnect, SkipType, utcnow
from .mappers import map_point, record_key

OBS_COLS = ["subject_id", "source", "device", "metric", "value", "unit", "start_utc", "end_utc",
            "utc_offset_min", "resolution", "method", "quality_flag", "raw_ref"]

# Upserts that only touch a row when something in it really changed. Re-reading the overlap window
# therefore costs no writes, and con.total_changes counts genuinely new or corrected data. That count
# is what tells the worker "a device sent something new -> refresh the processed outputs".
_OBS_KEY = ("subject_id", "source", "metric", "start_utc", "raw_ref")
_OBS_VALS = [c for c in OBS_COLS if c not in _OBS_KEY]
UPSERT_OBS = (
    f"INSERT INTO observations({','.join(OBS_COLS)}) VALUES ({','.join('?' * len(OBS_COLS))}) "
    f"ON CONFLICT({','.join(_OBS_KEY)}) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _OBS_VALS)
    + " WHERE " + " OR ".join(f"observations.{c} IS NOT excluded.{c}" for c in _OBS_VALS))
_SESS_VALS = ("subject_id", "kind", "start_utc", "end_utc", "utc_offset_min", "detail")
UPSERT_SESSION = (
    "INSERT INTO sessions(raw_ref,subject_id,kind,start_utc,end_utc,utc_offset_min,detail) "
    "VALUES (:raw_ref,:subject_id,:kind,:start_utc,:end_utc,:utc_offset_min,:detail) "
    "ON CONFLICT(raw_ref) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in _SESS_VALS)
    + " WHERE " + " OR ".join(f"sessions.{c} IS NOT excluded.{c}" for c in _SESS_VALS))
UPSERT_RAW = ("INSERT INTO raw_datapoints(name,label,data_type,payload) VALUES (?,?,?,?) "
              "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, fetched_at=datetime('now') "
              "WHERE raw_datapoints.payload IS NOT excluded.payload")

# Rows inserted or changed by any sync in this process (read by the worker before/after a round).
ROWS_CHANGED = 0


def subject_for(label):
    return "s_" + hashlib.sha256(label.encode()).hexdigest()[:8]


def register(con, label):
    con.execute("INSERT OR IGNORE INTO accounts(label, subject_id) VALUES (?, ?)", (label, subject_for(label)))
    con.execute("UPDATE accounts SET status='active', last_error=NULL WHERE label=?", (label,))


def _cursor(con, label, dt):
    row = con.execute("SELECT synced_until FROM sync_state WHERE label=? AND data_type=?", (label, dt)).fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0]) - timedelta(hours=config.OVERLAP_HOURS)
    return utcnow() - timedelta(days=config.BACKFILL_DAYS)


# 1-second heart rate is ~40k points/day: its raw JSON adds ~15 MB/day and nothing the canonical
# row doesn't already hold, so we keep only the canonical row for it.
NO_RAW = {"heart-rate"}


def store_points(con, label, subject, dt, points, source=None):
    """Raw JSON + canonical rows for an iterable of API data points. Idempotent.
    Adds the number of rows that were really new or different to ROWS_CHANGED."""
    global ROWS_CHANGED
    n, before = 0, con.total_changes
    raw, obs, sess_rows = [], [], []

    def flush():
        con.executemany(UPSERT_RAW, raw)
        con.executemany(UPSERT_OBS, obs)
        con.executemany(UPSERT_SESSION, sess_rows)
        raw.clear(); obs.clear(); sess_rows.clear()

    keep_raw = dt not in NO_RAW
    for dp in points:
        if keep_raw:
            raw.append((record_key(dt, dp), label, dt, json.dumps(dp)))
        rows, sess = map_point(subject, dt, dp)
        obs.extend([[r[c] for c in OBS_COLS] for r in rows])
        if sess:
            sess_rows.append(sess)
        n += 1
        if len(obs) >= 5000:
            flush()
    flush()
    ROWS_CHANGED += con.total_changes - before
    return n


def sync_account(con, label, client=None, data_types=None, log=print):
    subject = con.execute("SELECT subject_id FROM accounts WHERE label=?", (label,)).fetchone()[0]
    try:
        client = client or GoogleHealthClient(label)
    except NeedsReconnect as e:
        _mark_reconnect(con, label, e, log)
        return {}
    counts = {}
    for dt in data_types or DATA_TYPES:
        since, run_started = _cursor(con, label, dt), utcnow()
        n = 0
        try:
            n = store_points(con, label, subject, dt, client.list_points(dt, since))
        except SkipType as e:
            log(f"  [{label}] {dt}: skipped ({e})")
            continue
        except NeedsReconnect as e:
            _mark_reconnect(con, label, e, log)
            return counts
        except Exception as e:  # one failing type must not stop the others
            log(f"  [{label}] {dt}: ERROR {e}")
            con.execute("UPDATE accounts SET last_error=? WHERE label=?", (f"{dt}: {e}", label))
            continue
        con.execute("INSERT INTO sync_state(label,data_type,synced_until,last_count,updated_at) VALUES (?,?,?,?,datetime('now')) "
                    "ON CONFLICT(label,data_type) DO UPDATE SET synced_until=excluded.synced_until, "
                    "last_count=excluded.last_count, updated_at=excluded.updated_at",
                    (label, dt, run_started.isoformat(), n))
        con.commit()
        counts[dt] = n
        log(f"  [{label}] {dt}: {n} points since {since:%Y-%m-%d %H:%M}Z")
    con.execute("UPDATE accounts SET last_sync_at=datetime('now') WHERE label=?", (label,))
    return counts


def _mark_reconnect(con, label, err, log):
    con.execute("UPDATE accounts SET status='needs_reconnect', last_error=? WHERE label=?", (str(err), label))
    con.commit()
    log(f"  [{label}] NEEDS RECONNECT -> python -m wp connect {label}   ({err})")


def sync_all(log=print, providers=None):
    """Pull new data for every connected account (or only those of the given providers)."""
    with db.session() as con:
        rows = con.execute("SELECT label, COALESCE(provider, 'google') FROM accounts").fetchall()
        for label, provider in rows:
            if providers and provider not in providers:
                continue
            log(f"sync {label} ({provider}) @ {utcnow():%Y-%m-%d %H:%M:%S}Z")
            try:
                if provider == "whoop":
                    from . import whoop
                    whoop.sync_account(con, label, log=log)
                else:
                    sync_account(con, label, log=log)
            except Exception as e:   # one person's failure never stops the others
                log(f"  [{label}] sync failed: {e}")


def run_forever(every_min=None, log=print):
    every = (every_min or config.SYNC_EVERY_MIN) * 60
    while True:
        t0 = time.time()
        try:
            sync_all(log)
        except Exception as e:
            log(f"sync round failed: {e}")
        time.sleep(max(30, every - (time.time() - t0)))


def import_export(folder, label, log=print):
    """Load a previous extraction (folder with data/<type>.json files, as written by the
    Desktop/fitbit health_api.py script) into the database through the same mappers."""
    from pathlib import Path
    folder = Path(folder)
    data = folder / "data" if (folder / "data").is_dir() else folder
    with db.session() as con:
        register(con, label)
        subject = con.execute("SELECT subject_id FROM accounts WHERE label=?", (label,)).fetchone()[0]
        prof = data / "profile.json"
        if prof.exists():
            age = json.loads(prof.read_text()).get("age")
            con.execute("UPDATE accounts SET age=? WHERE label=?", (age, label))
        for dt in DATA_TYPES:
            f = data / f"{dt}.json"
            if not f.exists():
                continue
            pts = json.loads(f.read_text())
            pts = pts.get("dataPoints", []) if isinstance(pts, dict) else pts
            n = store_points(con, label, subject, dt, pts)
            con.commit()
            log(f"  {dt}: {n:,} points")
