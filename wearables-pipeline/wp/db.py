"""SQLite storage. Same tables port 1:1 to Postgres/TimescaleDB later.

Three layers:
  raw_datapoints  - every API record exactly as received (bronze, never edited)
  observations    - canonical long table, one row per measurement (silver)
  sessions        - sleep / exercise sessions (silver)
Processing outputs (daily features, flags) are written as parquet files (gold).
"""
import sqlite3
from contextlib import contextmanager

from . import config

DDL = """
CREATE TABLE IF NOT EXISTS accounts (
    label        TEXT PRIMARY KEY,          -- e.g. 'mohamad', 'friend1'
    subject_id   TEXT NOT NULL UNIQUE,      -- pseudonym used everywhere else
    age          INTEGER,                   -- from the Google Health profile (used for HR limits)
    email        TEXT,                      -- Google account; pre-selects it on the consent page
    status       TEXT NOT NULL DEFAULT 'active',  -- active | needs_reconnect
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at TEXT,
    last_error   TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    label        TEXT NOT NULL,
    data_type    TEXT NOT NULL,
    synced_until TEXT,                      -- ISO UTC; next sync starts here minus overlap
    last_count   INTEGER,
    updated_at   TEXT,
    PRIMARY KEY (label, data_type)
);

CREATE TABLE IF NOT EXISTS raw_datapoints (
    name        TEXT PRIMARY KEY,           -- API resource name, globally unique -> idempotent upserts
    label       TEXT NOT NULL,
    data_type   TEXT NOT NULL,
    payload     TEXT NOT NULL,              -- full JSON
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS observations (
    subject_id     TEXT NOT NULL,
    source         TEXT NOT NULL,           -- google_health | fitabase | ...
    device         TEXT,
    metric         TEXT NOT NULL,           -- canonical metric name (see canonical.py)
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    start_utc      TEXT NOT NULL,
    end_utc        TEXT,
    utc_offset_min INTEGER,                 -- local = utc + offset
    resolution     TEXT,                    -- sample | interval | daily | session
    method         TEXT,                    -- auto | manual | derived
    quality_flag   TEXT DEFAULT 'ok',
    raw_ref        TEXT,                    -- raw_datapoints.name
    PRIMARY KEY (subject_id, source, metric, start_utc, raw_ref)
);
CREATE INDEX IF NOT EXISTS ix_obs_subject_metric_time ON observations(subject_id, metric, start_utc);

CREATE TABLE IF NOT EXISTS sessions (
    raw_ref        TEXT PRIMARY KEY,
    subject_id     TEXT NOT NULL,
    kind           TEXT NOT NULL,           -- sleep | exercise
    start_utc      TEXT NOT NULL,
    end_utc        TEXT NOT NULL,
    utc_offset_min INTEGER,
    detail         TEXT                     -- JSON summary
);
"""


def connect(path=None):
    config.ensure_dirs()
    con = sqlite3.connect(path or config.DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(DDL)
    for col in ("age INTEGER", "email TEXT", "provider TEXT DEFAULT 'google'"):   # older databases
        try:
            con.execute(f"ALTER TABLE accounts ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    return con


@contextmanager
def session(path=None):
    con = connect(path)
    try:
        yield con
        con.commit()
    finally:
        con.close()
