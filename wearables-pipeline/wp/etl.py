"""ETL test: turn the raw database into compact, tiered files. The database is only read, never changed.

data/etl/
  hr_raw/<subject>.parquet        second-by-second heart rate: ts (epoch s), bpm      (hot tier: kept 30 days in production)
  hr_minute/<subject>.parquet     per-minute heart rate: mean, min, max, n            (warm tier: kept forever)
  measurements.parquet            every other measurement in narrow typed columns
  sessions.parquet                sleep and exercise sessions
  daily_features.parquet          the per-day results from the processing step (if present)
  size_report.txt                 bytes per tier and the 400-user projection
"""
import shutil
import sqlite3
import time
from pathlib import Path

import pandas as pd

from . import config

HOT_DAYS = 30


def _ts(s):
    """ISO strings -> epoch seconds (nullable Int64; missing stays missing)."""
    t = pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce").dt.as_unit("s")
    return pd.array([None if pd.isna(x) else int(x.timestamp()) for x in t], dtype="Int64") if t.isna().any() \
        else t.astype("int64")


def run(log=print):
    out = config.DATA_DIR / "etl"
    if out.exists():
        shutil.rmtree(out)
    for d in ("hr_raw", "hr_minute"):
        (out / d).mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    subjects = dict(con.execute("SELECT subject_id, label FROM accounts").fetchall())
    t0 = time.time()
    hr_rows = 0
    span_days = {}

    # ---- heart rate: raw + per-minute, one file per person ----------------------------------
    for sid in subjects:
        hr = pd.read_sql("SELECT start_utc, value FROM observations WHERE subject_id=? AND metric='heart_rate'",
                         con, params=(sid,))
        if hr.empty:
            continue
        hr = pd.DataFrame({"ts": _ts(hr.start_utc), "bpm": hr.value.round().clip(0, 255).astype("uint8")})
        hr = hr.drop_duplicates("ts").sort_values("ts")
        hr_rows += len(hr)
        span_days[sid] = (hr.ts.max() - hr.ts.min()) / 86400
        hr.to_parquet(out / "hr_raw" / f"{sid}.parquet", compression="zstd", index=False)
        m = hr.assign(minute=hr.ts // 60 * 60).groupby("minute").bpm.agg(["mean", "min", "max", "count"]).reset_index()
        m = pd.DataFrame({"ts": m.minute, "mean": m["mean"].round().astype("uint8"), "min": m["min"].astype("uint8"),
                          "max": m["max"].astype("uint8"), "n": m["count"].clip(upper=255).astype("uint8")})
        m.to_parquet(out / "hr_minute" / f"{sid}.parquet", compression="zstd", index=False)
        log(f"  {subjects[sid]}: {len(hr):,} heart-rate readings over {span_days[sid]:.0f} days -> {len(m):,} minutes")

    # ---- everything else: narrow typed table -------------------------------------------------
    o = pd.read_sql("SELECT subject_id, metric, start_utc, end_utc, value, utc_offset_min FROM observations "
                    "WHERE metric <> 'heart_rate'", con)
    o = pd.DataFrame({
        "subject": o.subject_id.astype("category"), "metric": o.metric.astype("category"),
        "ts": _ts(o.start_utc), "end_ts": _ts(o.end_utc),
        "value": o.value.astype("float32"), "utc_offset_min": o.utc_offset_min.astype("Int16")})
    g = o.groupby("subject", observed=True).ts
    other_days = float(((g.max() - g.min()) / 86400).sum()) or 1
    o.sort_values(["subject", "metric", "ts"]).to_parquet(out / "measurements.parquet", compression="zstd", index=False)
    s = pd.read_sql("SELECT * FROM sessions", con)
    s.to_parquet(out / "sessions.parquet", compression="zstd", index=False)
    con.close()
    daily = config.DATA_DIR / "processed" / "live" / "daily_features.parquet"
    if daily.exists():
        shutil.copy(daily, out / "daily_features.parquet")

    # ---- size report ---------------------------------------------------------------------------
    def size(p):
        p = Path(p)
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size

    db = config.DB_PATH.stat().st_size
    raw, minute = size(out / "hr_raw"), size(out / "hr_minute")
    other = size(out / "measurements.parquet") + size(out / "sessions.parquet")
    person_days = sum(span_days.values()) or 1
    per_day_raw, per_day_min = raw / person_days, minute / person_days
    other_per_day = other / other_days
    users, year = 400, 365
    proj_now = db / person_days * users * year
    proj_tiered = per_day_raw * HOT_DAYS * users + (per_day_min + other_per_day) * year * users
    lines = [
        f"ETL run {time.strftime('%Y-%m-%d %H:%M')}  ({time.time() - t0:.0f} s)",
        f"people: {len(subjects)}   person-days: heart rate {person_days:.0f}, other data {other_days:.0f}   heart-rate readings: {hr_rows:,}",
        "",
        f"database now (raw, untouched):      {db / 1e6:9.1f} MB",
        f"etl/hr_raw    (1-s heart rate):     {raw / 1e6:9.1f} MB   {per_day_raw / 1e3:7.1f} KB per person-day",
        f"etl/hr_minute (per-minute HR):      {minute / 1e6:9.1f} MB   {per_day_min / 1e3:7.1f} KB per person-day",
        f"etl/measurements + sessions:        {other / 1e6:9.1f} MB   {other_per_day / 1e3:7.1f} KB per person-day",
        f"etl total:                          {(raw + minute + other) / 1e6:9.1f} MB   ({db / max(raw + minute + other, 1):.0f}x smaller)",
        "",
        f"400 people x 1 year, current database design:   {proj_now / 1e9:8.0f} GB",
        f"400 people x 1 year, tiered (raw kept {HOT_DAYS} days):  {proj_tiered / 1e9:8.1f} GB",
    ]
    (out / "size_report.txt").write_text("\n".join(lines), encoding="utf-8")
    for line in lines:
        log(line)
    return out
