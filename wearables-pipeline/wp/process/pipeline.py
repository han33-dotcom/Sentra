"""Stage 2: what we do with the data after extraction.

observations (canonical, any source)
  -> 1. clean        drop impossible values, duplicates
  -> 2. minute grid  one row per subject-minute: HR mean/min/max, steps, MET, sleep stage, worn?
  -> 3. daily        one row per subject-day: sleep, resting HR, sleeping HR, activity, strain, stillness
  -> 4. baselines    each person vs their own previous 28 days (robust z-scores)
  -> 5. flags        transparent v0 rules (thresholds.json, to be set with the medical expert)
  -> 6. cohort       group-level view with k-anonymity (what an HSE manager would see)
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ..canonical import SLEEP_STAGE

TH = json.loads((Path(__file__).resolve().parent.parent / "thresholds.json").read_text())
ASLEEP = [SLEEP_STAGE[k] for k in ("light", "deep", "rem", "asleep_unspecified")]


# ------------------------------------------------------------------ helpers --
def _local(ts, offset_min):
    if pd.api.types.is_datetime64_any_dtype(ts) and getattr(ts.dt, "tz", None) is None:
        t = ts                                   # already naive local (e.g. Fitabase)
    else:                                        # ISO strings with Z from the API -> naive UTC
        t = pd.to_datetime(ts, utc=True, format="mixed").dt.tz_localize(None)
    return t + pd.to_timedelta(offset_min.fillna(0), unit="min")


def longest_run(minutes: pd.Series, flag: pd.Series) -> int:
    """Longest streak of consecutive minutes where flag is True (gaps in time break the streak)."""
    if not flag.any():
        return 0
    m = minutes[flag.values]
    new_block = m.diff().ne(pd.Timedelta(minutes=1))
    return int(new_block.cumsum().value_counts().max())


# ------------------------------------------------------------------ 1. clean -
def clean(obs: pd.DataFrame):
    obs = obs.copy()
    obs["t"] = _local(obs["start_utc"], obs["utc_offset_min"])
    if "end_utc" in obs:
        end = obs["end_utc"]
        obs["t_end"] = _local(end, obs["utc_offset_min"]) if end.notna().any() else pd.NaT
    lo, hi = TH["hr_valid_range_bpm"]
    bad = (obs.metric == "heart_rate") & ~obs.value.between(lo, hi)
    report = {"rows_in": len(obs), "hr_out_of_range": int(bad.sum())}
    obs = obs[~bad].drop_duplicates(["subject_id", "metric", "t"])
    report["rows_out"] = len(obs)
    return obs, report


# ------------------------------------------------------------- 2. minute grid
def minute_grid(obs: pd.DataFrame) -> pd.DataFrame:
    obs = obs.assign(minute=obs.t.dt.floor("min"))
    key = ["subject_id", "minute"]
    hr = obs[obs.metric == "heart_rate"].groupby(key).value.agg(hr_mean="mean", hr_min="min", hr_max="max", hr_n="count")
    steps = obs[obs.metric == "steps"].groupby(key).value.sum().rename("steps")
    met = obs[obs.metric == "met"].groupby(key).value.mean().rename("met")

    # sleep stages can be long intervals (Google) or single minutes (Fitabase): expand to minutes
    s = obs[obs.metric == "sleep_stage"].copy()
    if len(s):
        dur = ((s.t_end - s.t).dt.total_seconds() // 60).fillna(1).clip(lower=1).astype(int)
        # every stage of one sleep session belongs to the day you woke up (session end), like the vendor
        if "raw_ref" in s and s.raw_ref.notna().any():
            s["wake_day"] = s.groupby("raw_ref").t_end.transform("max").dt.normalize()
        else:
            s["wake_day"] = pd.NaT
        s = s.loc[s.index.repeat(dur)]
        s["minute"] = s.minute + pd.to_timedelta(s.groupby(level=0).cumcount(), unit="min")
        sleep = s.groupby(key).agg(sleep_code=("value", "last"), wake_day=("wake_day", "last"))
    else:
        sleep = pd.DataFrame(columns=["sleep_code", "wake_day"])

    parts = [x for x in (hr, steps, met, sleep) if len(x)]   # WHOOP-only people have no minute data
    cols = ["hr_mean", "hr_min", "hr_max", "hr_n", "steps", "met", "sleep_code", "wake_day"]
    if parts:
        g = pd.concat(parts, axis=1).reset_index().sort_values(key)
    else:
        g = pd.DataFrame({"subject_id": pd.Series(dtype=object), "minute": pd.Series(dtype="datetime64[ns]")})
    for col in cols:
        if col not in g:
            g[col] = pd.NaT if col == "wake_day" else float("nan")
    g["worn"] = g.hr_n.fillna(0) > 0
    g["asleep"] = g.sleep_code.isin(ASLEEP)
    return g


# ------------------------------------------------------------------ 3. daily -
def daily(g: pd.DataFrame, obs: pd.DataFrame, ages: dict | None = None) -> pd.DataFrame:
    ages = ages or {}
    g = g.copy()
    g["date"] = g.minute.dt.normalize()
    # a night's sleep belongs to the day you wake up: shift by +6h (18:00 -> 18:00 window)
    # (sources without session ids, e.g. Kaggle: use an 18:00 -> 18:00 window instead)
    g["sleep_day"] = pd.to_datetime(g.wake_day).fillna((g.minute + pd.Timedelta(hours=6)).dt.normalize())
    still = g.steps.fillna(0).eq(0)
    # "resting" minute = awake, worn, no steps this minute and the previous 5
    g["rest_min"] = g.worn & ~g.asleep & still & (
        still.groupby(g.subject_id).transform(lambda x: x.rolling(6, min_periods=6).sum()) == 6)
    h0, h1 = (int(x[:2]) for x in TH["shift_window_local"])
    g["in_shift"] = g.minute.dt.hour.between(h0, h1 - 1)

    rows = []
    for (sid, day), d in g.groupby(["subject_id", "date"], sort=False):
        age = ages.get(sid, TH["default_age"])
        hr_limit = 180 - age
        worn = d[d.worn]
        rows.append({
            "subject_id": sid, "date": day,
            "wear_min": int(d.worn.sum()),
            "steps": float(d.steps.sum()) if d.steps.notna().any() else np.nan,
            "active_min": int((d.met >= TH["active_met"]).sum()) if d.met.notna().any() else np.nan,
            "sedentary_min": int(((d.met < TH["sedentary_met"]) & ~d.asleep).sum()) if d.met.notna().any() else np.nan,
            "hr_mean": worn.hr_mean.mean(), "hr_max": worn.hr_max.max(),
            "rhr_est": d.loc[d.rest_min, "hr_mean"].quantile(0.10) if d.rest_min.sum() >= 30 else np.nan,
            "sustained_hr_max_run": longest_run(worn.minute, worn.hr_mean > hr_limit),
            "hr_limit_bpm": hr_limit,
            "longest_still_in_shift": longest_run(d.minute, (d.worn & d.in_shift & d.steps.fillna(0).eq(0) & ~d.asleep)),
        })
    day_df = pd.DataFrame(rows, columns=["subject_id", "date", "wear_min", "steps", "active_min", "sedentary_min",
                                         "hr_mean", "hr_max", "rhr_est", "sustained_hr_max_run", "hr_limit_bpm",
                                         "longest_still_in_shift"])

    # sleep features on the wake-up day
    sl = g[g.sleep_code.notna()]
    if len(sl):
        sd = sl.groupby(["subject_id", "sleep_day"]).agg(
            sleep_min=("asleep", "sum"),
            restless_min=("sleep_code", lambda x: int((x == SLEEP_STAGE["restless"]).sum())),
            awake_in_bed_min=("sleep_code", lambda x: int((x == SLEEP_STAGE["awake"]).sum())),
            in_bed_min=("sleep_code", "size"),
            sleep_hr=("hr_mean", lambda x: x[sl.loc[x.index, "asleep"]].mean()),
        ).reset_index().rename(columns={"sleep_day": "date"})
        sd["sleep_eff"] = sd.sleep_min / sd.in_bed_min
        day_df = day_df.merge(sd, on=["subject_id", "date"], how="outer")

    # vendor daily metrics (live Google data): resting HR, HRV ... override our estimates when present
    vend = obs[obs.resolution == "daily"]
    if len(vend):
        v = vend.assign(date=vend.t.dt.normalize()).pivot_table(index=["subject_id", "date"], columns="metric",
                                                                 values="value", aggfunc="last").reset_index()
        # outer: days that only have device summaries (e.g. WHOOP) still count
        day_df = day_df.merge(v, on=["subject_id", "date"], how="outer")
    if "daily_sleep_min" in day_df:   # devices without a stage timeline (WHOOP) report nightly totals
        day_df["sleep_min"] = day_df["sleep_min"].fillna(day_df.daily_sleep_min) if "sleep_min" in day_df \
            else day_df.daily_sleep_min
    day_df["rhr"] = day_df["resting_heart_rate"].fillna(day_df.rhr_est) if "resting_heart_rate" in day_df else day_df.rhr_est
    day_df["valid_day"] = day_df.wear_min.fillna(0) >= TH["valid_day_min_wear_minutes"]
    # the device's own nightly metrics exist only if it was worn overnight -> the day is usable
    # for recovery/fatigue even when we did not pull its minute-level heart rate
    vendor = [c for c in ("resting_heart_rate", "daily_hrv_rmssd", "daily_sleep_min") if c in day_df]
    day_df["usable_day"] = day_df.valid_day | (day_df[vendor].notna().any(axis=1) if vendor else False)
    return day_df.sort_values(["subject_id", "date"]).reset_index(drop=True)


# -------------------------------------------------------------- 4. baselines -
BASELINE_FEATURES = ["rhr", "sleep_hr", "sleep_min", "steps", "hr_mean", "daily_hrv_rmssd",
                     "daily_respiratory_rate", "nightly_skin_temp_c"]
VENDOR_NIGHTLY = {"daily_hrv_rmssd", "daily_respiratory_rate", "nightly_skin_temp_c"}
# a very stable person has a tiny spread -> tiny changes look huge; floor the scale
MIN_SCALE = {"rhr": 1.5, "sleep_hr": 1.5, "hr_mean": 2.0, "sleep_min": 20, "steps": 800, "daily_hrv_rmssd": 3.0,
             "daily_respiratory_rate": 0.5, "nightly_skin_temp_c": 0.3}


def baselines(day_df: pd.DataFrame) -> pd.DataFrame:
    """Robust personal baseline: median and MAD of the previous `baseline_days` valid days
    (today is never part of its own baseline). z = (today - median) / scale."""
    df = day_df.copy()
    n, m = TH["baseline_days"], TH["baseline_min_days"]

    def _med(w):
        w = w[~np.isnan(w)]
        return np.median(w) if len(w) >= m else np.nan

    def _mad(w):
        w = w[~np.isnan(w)]
        return np.median(np.abs(w - np.median(w))) if len(w) >= m else np.nan

    for f in [c for c in BASELINE_FEATURES if c in df]:
        if f.startswith("sleep") or f in VENDOR_NIGHTLY:
            x = df[f]                                   # present only when the night was recorded
        elif f == "rhr" and "resting_heart_rate" in df:
            x = df[f].where(df.valid_day | df.resting_heart_rate.notna())
        else:
            x = df[f].where(df.valid_day)
        prev = x.groupby(df.subject_id).shift(1)
        grp = prev.groupby(df.subject_id)
        med = grp.transform(lambda s: s.rolling(n, min_periods=1).apply(_med, raw=True))
        mad = grp.transform(lambda s: s.rolling(n, min_periods=1).apply(_mad, raw=True))
        scale = np.maximum(1.4826 * mad, MIN_SCALE.get(f, 0) or 1e-9)
        df[f"{f}_base"] = med
        df[f"{f}_z"] = (df[f] - med) / scale
    return df


# ------------------------------------------------------------------ 5. flags -
def flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    z = TH["z_alert"]
    df["flag_short_sleep"] = df.get("sleep_min", pd.Series(np.nan, index=df.index)) < TH["short_sleep_minutes"]
    df["flag_rhr_up"] = df.get("rhr_z", pd.Series(np.nan, index=df.index)) >= z
    df["flag_sleep_hr_up"] = df.get("sleep_hr_z", pd.Series(np.nan, index=df.index)) >= z
    df["flag_hrv_down"] = df.get("daily_hrv_rmssd_z", pd.Series(np.nan, index=df.index)) <= -z
    df["flag_sustained_hr"] = df.sustained_hr_max_run >= TH["sustained_hr_min_minutes"]
    df["flag_long_inactivity"] = df.longest_still_in_shift >= TH["long_inactivity_minutes"]
    df["fatigue_points"] = df[["flag_short_sleep", "flag_rhr_up", "flag_sleep_hr_up", "flag_hrv_down"]].sum(axis=1)
    df["fatigue_level"] = pd.cut(df.fatigue_points, [-1, 0, 1, 4], labels=["green", "amber", "red"])
    return df


# ----------------------------------------------------------------- 6. cohort -
def cohort(df: pd.DataFrame) -> pd.DataFrame:
    k = TH["cohort_k_anonymity"]
    d = df[df.usable_day]
    c = d.groupby("date").agg(
        workers=("subject_id", "nunique"),
        pct_short_sleep=("flag_short_sleep", "mean"),
        pct_fatigue_amber_or_red=("fatigue_points", lambda x: (x >= 1).mean()),
        pct_sustained_hr=("flag_sustained_hr", "mean"),
        median_sleep_h=("sleep_min", lambda x: x.median() / 60),
        median_steps=("steps", "median"),
    ).reset_index()
    hidden = c.workers < k   # never show a group smaller than k people
    c.loc[hidden, c.columns[2:]] = np.nan
    c["suppressed"] = hidden
    return c


def run(obs: pd.DataFrame, out_dir: Path, ages=None, log=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obs, rep = clean(obs)
    log(f"1 clean      {rep}")
    g = minute_grid(obs)
    log(f"2 minute     {len(g):,} subject-minutes, {g.subject_id.nunique()} subjects, worn {g.worn.mean():.0%}")
    d = daily(g, obs, ages)
    log(f"3 daily      {len(d):,} subject-days, valid (>= {TH['valid_day_min_wear_minutes']} min worn): {d.valid_day.sum():,}")
    d = baselines(d)
    log(f"4 baselines  rhr baseline available on {d.rhr_base.notna().sum():,} days")
    d = flags(d)
    log(f"   usable days (worn >= 10h OR device produced nightly metrics): {d.usable_day.sum():,}")
    log(f"5 flags      fatigue levels: {d[d.usable_day].fatigue_level.value_counts().to_dict()}")
    c = cohort(d)
    log(f"6 cohort     {len(c)} days, {c.suppressed.sum()} suppressed (<{TH['cohort_k_anonymity']} people)")
    for df, name in ((g, "minute"), (d, "daily_features"), (c, "cohort_daily")):
        _write_atomic(df, out_dir / f"{name}.parquet")
    return g, d, c, obs


def _write_atomic(df: pd.DataFrame, path: Path):
    """Write next to the target, then swap, so the API never reads a half-written file."""
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
