"""Wellness processing over canonical observations (ported from archive/monorepo-v0 wp/process/pipeline.py).

observations (canonical, from the parquet tiers)
  -> 1. clean        drop impossible heart rates and duplicates
  -> 2. minute grid  one row per subject-minute: HR mean/min/max, steps, MET, sleep stage, worn?
  -> 3. daily        one row per subject-day: activity, heart rate, vendor nightly summaries
  -> 4. baselines    each person vs their own previous 28 days (robust z-scores)
  -> 5. flags        transparent v0 wellness rules (thresholds.json, pending medical expert sign-off)
  -> 6. cohort       group-level daily view with k-anonymity

Outputs describe differences from a person's own recent pattern for wellness conversations.
They are not medical assessments and must not be presented as a diagnosis.
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .canonical import SLEEP_STAGE

THRESHOLDS = Path(__file__).resolve().with_name('thresholds.json')
TH = json.loads(THRESHOLDS.read_text(encoding='utf-8'))
ASLEEP = [SLEEP_STAGE[k] for k in ('light', 'deep', 'rem', 'asleep_unspecified')]
NOTICE = ('Wellness indicators relative to each person\'s own recent pattern; not a medical assessment or diagnosis. '
          'Thresholds: ' + TH['_status'] + '.')


def _day(series):
    return pd.to_datetime(series).dt.normalize().astype('datetime64[ns]')


def longest_run(minutes: pd.Series, flag: pd.Series) -> int:
    """Longest streak of consecutive minutes where flag is True (gaps in time break the streak)."""
    if not flag.any():
        return 0
    m = minutes[flag.values]
    new_block = m.diff().ne(pd.Timedelta(minutes=1))
    return int(new_block.cumsum().value_counts().max())


# ------------------------------------------------------------------ 1. clean -
def clean(obs: pd.DataFrame):
    lo, hi = TH['hr_valid_range_bpm']
    bad = (obs.metric == 'heart_rate') & ~obs.value.between(lo, hi)
    report = {'rows_in': len(obs), 'hr_out_of_range': int(bad.sum())}
    obs = obs[~bad].drop_duplicates(['subject_id', 'metric', 't', 'raw_ref'])
    report['rows_out'] = len(obs)
    return obs.reset_index(drop=True), report


# ------------------------------------------------------------- 2. minute grid
def minute_grid(obs: pd.DataFrame) -> pd.DataFrame:
    obs = obs.assign(minute=obs.t.dt.floor('min'))
    key = ['subject_id', 'minute']
    intraday = obs[obs.resolution != 'daily']
    hr = intraday[intraday.metric == 'heart_rate'].groupby(key).value.agg(hr_mean='mean', hr_min='min', hr_max='max', hr_n='count')
    steps = intraday[intraday.metric == 'steps'].groupby(key).value.sum().rename('steps')
    met = intraday[intraday.metric == 'met'].groupby(key).value.mean().rename('met')

    s = intraday[intraday.metric == 'sleep_stage'].copy()
    if len(s):
        dur = ((s.t_end - s.t).dt.total_seconds() // 60).fillna(1).clip(lower=1).astype(int)
        # every stage of one sleep session belongs to the day you woke up (session end), like the vendor
        s['wake_day'] = s.groupby('raw_ref').t_end.transform('max').dt.normalize()
        s = s.loc[s.index.repeat(dur)]
        s['minute'] = s.minute + pd.to_timedelta(s.groupby(level=0).cumcount(), unit='min')
        sleep = s.groupby(key).agg(sleep_code=('value', 'last'), wake_day=('wake_day', 'last'))
    else:
        sleep = pd.DataFrame(columns=['sleep_code', 'wake_day'])

    parts = [x for x in (hr, steps, met, sleep) if len(x)]  # WHOOP-only people have no minute data
    cols = ['hr_mean', 'hr_min', 'hr_max', 'hr_n', 'steps', 'met', 'sleep_code', 'wake_day']
    if parts:
        g = pd.concat(parts, axis=1).reset_index().sort_values(key)
    else:
        g = pd.DataFrame({'subject_id': pd.Series(dtype=object), 'minute': pd.Series(dtype='datetime64[ns]')})
    for col in cols:
        if col not in g:
            g[col] = pd.NaT if col == 'wake_day' else float('nan')
    g['worn'] = g.hr_n.fillna(0) > 0
    g['asleep'] = g.sleep_code.isin(ASLEEP)
    return g.reset_index(drop=True)


# ------------------------------------------------------------------ 3. daily -
DAY_COLUMNS = ['subject_id', 'date', 'wear_min', 'steps', 'active_min', 'sedentary_min', 'hr_mean', 'hr_max',
               'rhr_est', 'sustained_hr_max_run', 'hr_limit_bpm', 'longest_still_in_shift']


def daily(g: pd.DataFrame, obs: pd.DataFrame, ages: dict | None = None) -> pd.DataFrame:
    ages = ages or {}
    g = g.copy()
    g['date'] = _day(g.minute)
    g['sleep_day'] = pd.to_datetime(g.wake_day).fillna((g.minute + pd.Timedelta(hours=6)).dt.normalize())
    still = g.steps.fillna(0).eq(0)
    # "resting" minute = awake, worn, no steps this minute and the previous 5
    g['rest_min'] = g.worn & ~g.asleep & still & (
        still.groupby(g.subject_id).transform(lambda x: x.rolling(6, min_periods=6).sum()) == 6)
    h0, h1 = (int(x[:2]) for x in TH['shift_window_local'])
    g['in_shift'] = g.minute.dt.hour.between(h0, h1 - 1)

    rows = []
    for (sid, day), d in g.groupby(['subject_id', 'date'], sort=False):
        age = ages.get(sid, TH['default_age'])
        hr_limit = 180 - age
        worn = d[d.worn]
        rows.append({
            'subject_id': sid, 'date': day,
            'wear_min': int(d.worn.sum()),
            'steps': float(d.steps.sum()) if d.steps.notna().any() else np.nan,
            'active_min': int((d.met >= TH['active_met']).sum()) if d.met.notna().any() else np.nan,
            'sedentary_min': int(((d.met < TH['sedentary_met']) & ~d.asleep).sum()) if d.met.notna().any() else np.nan,
            'hr_mean': worn.hr_mean.mean(), 'hr_max': worn.hr_max.max(),
            'rhr_est': d.loc[d.rest_min, 'hr_mean'].quantile(0.10) if d.rest_min.sum() >= 30 else np.nan,
            'sustained_hr_max_run': longest_run(worn.minute, worn.hr_mean > hr_limit),
            'hr_limit_bpm': hr_limit,
            'longest_still_in_shift': longest_run(d.minute, (d.worn & d.in_shift & d.steps.fillna(0).eq(0) & ~d.asleep)),
        })
    day_df = pd.DataFrame(rows, columns=DAY_COLUMNS)
    day_df['date'] = day_df['date'].astype('datetime64[ns]')

    sl = g[g.sleep_code.notna()]
    if len(sl):
        sd = sl.groupby(['subject_id', 'sleep_day']).agg(
            sleep_min=('asleep', 'sum'),
            restless_min=('sleep_code', lambda x: int((x == SLEEP_STAGE['restless']).sum())),
            awake_in_bed_min=('sleep_code', lambda x: int((x == SLEEP_STAGE['awake']).sum())),
            in_bed_min=('sleep_code', 'size'),
            sleep_hr=('hr_mean', lambda x: x[sl.loc[x.index, 'asleep']].mean()),
        ).reset_index().rename(columns={'sleep_day': 'date'})
        sd['date'] = sd['date'].astype('datetime64[ns]')
        sd['sleep_eff'] = sd.sleep_min / sd.in_bed_min
        day_df = day_df.merge(sd, on=['subject_id', 'date'], how='outer')

    # vendor daily metrics (resting HR, HRV, WHOOP nightly totals ...) override our estimates when present
    vend = obs[obs.resolution == 'daily'].sort_values('t')
    if len(vend):
        vend = vend.assign(date=_day(vend.t))
        # Several sessions on one wake day (e.g. a nap): durations keep the longest, never a sum.
        pivots = [part.pivot_table(index=['subject_id', 'date'], columns='metric', values='value', aggfunc=agg).reset_index()
                  for part, agg in ((vend[vend.metric.str.endswith('_min')], 'max'),
                                    (vend[~vend.metric.str.endswith('_min')], 'last')) if len(part)]
        for v in pivots:
            v.columns.name = None
            day_df = day_df.merge(v, on=['subject_id', 'date'], how='outer')
    if 'sleep_min' not in day_df:
        day_df['sleep_min'] = np.nan  # no sleep returned: stays missing, never zero
    if 'daily_sleep_min' in day_df:
        day_df['sleep_min'] = day_df['sleep_min'].fillna(day_df.daily_sleep_min)
    day_df['rhr'] = day_df['resting_heart_rate'].fillna(day_df.rhr_est) if 'resting_heart_rate' in day_df else day_df.rhr_est
    day_df['valid_day'] = day_df.wear_min.fillna(0) >= TH['valid_day_min_wear_minutes']
    # the device's own nightly metrics exist only if it was worn overnight -> the day is usable
    vendor = [c for c in ('resting_heart_rate', 'daily_hrv_rmssd', 'daily_sleep_min') if c in day_df]
    day_df['usable_day'] = day_df.valid_day | (day_df[vendor].notna().any(axis=1) if vendor else False)
    return day_df.sort_values(['subject_id', 'date']).reset_index(drop=True)


# -------------------------------------------------------------- 4. baselines -
BASELINE_FEATURES = ['rhr', 'sleep_hr', 'sleep_min', 'steps', 'hr_mean', 'daily_hrv_rmssd',
                     'daily_respiratory_rate', 'nightly_skin_temp_c']
VENDOR_NIGHTLY = {'daily_hrv_rmssd', 'daily_respiratory_rate', 'nightly_skin_temp_c'}
# a very stable person has a tiny spread -> tiny changes look huge; floor the scale
MIN_SCALE = {'rhr': 1.5, 'sleep_hr': 1.5, 'hr_mean': 2.0, 'sleep_min': 20, 'steps': 800, 'daily_hrv_rmssd': 3.0,
             'daily_respiratory_rate': 0.5, 'nightly_skin_temp_c': 0.3}


def baselines(day_df: pd.DataFrame) -> pd.DataFrame:
    """Robust personal baseline: median and MAD of the previous `baseline_days` rows
    (today is never part of its own baseline). z = (today - median) / scale."""
    df = day_df.copy()
    n, m = TH['baseline_days'], TH['baseline_min_days']

    def _med(w):
        w = w[~np.isnan(w)]
        return np.median(w) if len(w) >= m else np.nan

    def _mad(w):
        w = w[~np.isnan(w)]
        return np.median(np.abs(w - np.median(w))) if len(w) >= m else np.nan

    for f in [c for c in BASELINE_FEATURES if c in df]:
        if f.startswith('sleep') or f in VENDOR_NIGHTLY:
            x = df[f]
        elif f == 'rhr' and 'resting_heart_rate' in df:
            x = df[f].where(df.valid_day | df.resting_heart_rate.notna())
        else:
            x = df[f].where(df.valid_day)
        prev = x.astype('float64').groupby(df.subject_id).shift(1)
        grp = prev.groupby(df.subject_id)
        med = grp.transform(lambda s: s.rolling(n, min_periods=1).apply(_med, raw=True))
        mad = grp.transform(lambda s: s.rolling(n, min_periods=1).apply(_mad, raw=True))
        scale = np.maximum(1.4826 * mad, MIN_SCALE.get(f, 0) or 1e-9)
        df[f'{f}_base'] = med
        df[f'{f}_z'] = (df[f] - med) / scale
    return df


# ------------------------------------------------------------------ 5. flags -
WELLNESS_SIGNALS = ['flag_short_sleep', 'flag_rhr_above_baseline', 'flag_sleep_hr_above_baseline', 'flag_hrv_below_baseline']


def flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    z = TH['z_alert']
    missing = pd.Series(np.nan, index=df.index)
    # Missing data never raises a flag: NaN comparisons are False.
    df['flag_short_sleep'] = df.get('sleep_min', missing) < TH['short_sleep_minutes']
    df['flag_rhr_above_baseline'] = df.get('rhr_z', missing) >= z
    df['flag_sleep_hr_above_baseline'] = df.get('sleep_hr_z', missing) >= z
    df['flag_hrv_below_baseline'] = df.get('daily_hrv_rmssd_z', missing) <= -z
    df['flag_sustained_high_hr'] = df.sustained_hr_max_run >= TH['sustained_hr_min_minutes']
    df['flag_long_inactivity_in_shift'] = df.longest_still_in_shift >= TH['long_inactivity_minutes']
    df['wellness_signals'] = df[WELLNESS_SIGNALS].sum(axis=1)
    df['wellness_level'] = pd.cut(df.wellness_signals, [-1, 0, 1, 4], labels=['green', 'amber', 'red']).astype(str)
    return df


# ----------------------------------------------------------------- 6. cohort -
def cohort(df: pd.DataFrame) -> pd.DataFrame:
    k = TH['cohort_k_anonymity']
    d = df[df.usable_day]
    c = d.groupby('date').agg(
        workers=('subject_id', 'nunique'),
        pct_short_sleep=('flag_short_sleep', 'mean'),
        pct_wellness_amber_or_red=('wellness_signals', lambda x: (x >= 1).mean()),
        pct_sustained_high_hr=('flag_sustained_high_hr', 'mean'),
        median_sleep_h=('sleep_min', lambda x: x.median() / 60),
        median_steps=('steps', 'median'),
    ).reset_index()
    hidden = c.workers < k  # never show a group smaller than k people
    c[c.columns[2:]] = c[c.columns[2:]].astype('float64')
    c.loc[hidden, c.columns[2:]] = np.nan
    c['suppressed'] = hidden
    return c


def run(obs: pd.DataFrame, out_dir: Path, ages=None, log=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obs, rep = clean(obs)
    log(f'1 clean      {rep}')
    g = minute_grid(obs)
    log(f'2 minute     {len(g):,} subject-minutes, {g.subject_id.nunique()} subjects')
    d = daily(g, obs, ages)
    log(f'3 daily      {len(d):,} subject-days, valid (>= {TH["valid_day_min_wear_minutes"]} min worn): {int(d.valid_day.sum()):,}')
    d = baselines(d)
    log(f'4 baselines  rhr baseline available on {int(d.rhr_base.notna().sum()) if "rhr_base" in d else 0:,} days')
    d = flags(d)
    log(f'5 flags      wellness levels on usable days: {d[d.usable_day].wellness_level.value_counts().to_dict()}')
    c = cohort(d)
    log(f'6 cohort     {len(c)} days, {int(c.suppressed.sum())} suppressed (<{TH["cohort_k_anonymity"]} people)')
    for df, name in ((g, 'minute'), (d, 'daily_features'), (c, 'cohort_daily')):
        _write_atomic(df, out_dir / f'{name}.parquet')
    meta = {'notice': NOTICE, 'thresholds': TH, 'clean': rep, 'subjects': int(d.subject_id.nunique()),
            'days': [str(d.date.min().date()), str(d.date.max().date())] if len(d) else None}
    tmp = out_dir / 'metadata.json.tmp'
    tmp.write_text(json.dumps(meta, indent=2, default=str), encoding='utf-8')
    os.replace(tmp, out_dir / 'metadata.json')
    return g, d, c, obs


def _write_atomic(df: pd.DataFrame, path: Path):
    """Write next to the target, then swap, so a reader never sees a half-written file."""
    tmp = path.with_suffix('.parquet.tmp')
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
