"""Canonical observations from the parquet tiers (hr_raw, hr_minute, measurements).

Columns: subject_id, metric, t (naive Asia/Beirut local), t_end, value, resolution, raw_ref.
Heart rate per minute uses the best available source and never mixes them in one minute:
raw readings (30-day hot tier) > Sentra minutes from raw > vendor 60 s rollups.
"""
from pathlib import Path

import pandas as pd

from .metric_map import MAPPING, WHOOP_ASLEEP_PARTS

LOCAL = 'Asia/Beirut'
COLUMNS = ['subject_id', 'metric', 't', 't_end', 'value', 'resolution', 'raw_ref']


def local(epoch_seconds):
    return pd.to_datetime(epoch_seconds, unit='s', utc=True).dt.tz_convert(LOCAL).dt.tz_localize(None)


def _heart_rate(tiers):
    frames = []
    for folder, kind in (('hr_raw', 'raw'), ('hr_minute', 'minute')):
        for path in sorted((Path(tiers) / folder).glob('p*.parquet')):
            df = pd.read_parquet(path)
            df['subject_id'] = path.stem
            df['kind'] = kind if kind == 'raw' else df['source'].astype(str)
            df['value'] = df['bpm'].astype('float64') if kind == 'raw' else df['mean'].astype('float64')
            frames.append(df[['subject_id', 'ts', 'value', 'kind']])
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    hr = pd.concat(frames, ignore_index=True).dropna(subset=['value'])
    hr['minute'] = hr.ts // 60 * 60
    rank = hr.kind.map({'raw': 0, 'sentra_from_raw': 1, 'vendor_60s_rollup': 2})
    best = rank.groupby([hr.subject_id, hr.minute]).transform('min')
    hr = hr[rank == best]
    return pd.DataFrame({'subject_id': hr.subject_id, 'metric': 'heart_rate', 't': local(hr.ts), 't_end': pd.NaT,
                         'value': hr.value, 'resolution': hr.kind.map(lambda k: 'sample' if k == 'raw' else 'minute'),
                         'raw_ref': None})


def from_measurements(m):
    """Map a measurements-tier frame onto canonical observations; unmapped rows are dropped."""
    if m.empty:
        return pd.DataFrame(columns=COLUMNS)
    m = m[m['value'].notna()].copy()
    for column in ('provider', 'dataset', 'metric'):
        m[column] = m[column].astype(str)
    keys = list(zip(m.provider, m.dataset, m.metric))
    asleep = m[(m.provider == 'whoop') & (m.dataset == 'sleep') & m.metric.isin(WHOOP_ASLEEP_PARTS)]
    target = [MAPPING.get(k) for k in keys]
    m['canonical'] = [t[0] if t else None for t in target]
    m['resolution'] = [t[1] if t else None for t in target]
    m['scale'] = [t[2] if t else None for t in target]
    m['basis'] = [t[3] if t else None for t in target]
    m = m[m.canonical.notna()]
    if not asleep.empty:
        parts = asleep.pivot_table(index=['participant', 'record_key', 'ts', 'end_ts'], columns='metric',
                                   values='value', aggfunc='first').reset_index()
        parts = parts.dropna(subset=[p for p in WHOOP_ASLEEP_PARTS if p in parts] or ['record_key'])
        if all(p in parts for p in WHOOP_ASLEEP_PARTS) and len(parts):
            extra = pd.DataFrame({'participant': parts.participant, 'record_key': parts.record_key, 'ts': parts.ts,
                                  'end_ts': parts.end_ts, 'civil_date': None, 'canonical': 'daily_sleep_min',
                                  'resolution': 'daily', 'basis': 'end', 'scale': 1 / 60_000,
                                  'value': parts[list(WHOOP_ASLEEP_PARTS)].sum(axis=1)})
            m = pd.concat([m, extra], ignore_index=True)
    start = local(m.ts.astype('float64'))
    end = local(m.end_ts.astype('float64'))
    civil = pd.to_datetime(m.civil_date, errors='coerce')
    t = start.where(m.basis != 'end', end).where(m.basis != 'civil', civil)
    out = pd.DataFrame({'subject_id': m.participant.astype(str), 'metric': m.canonical, 't': t,
                        't_end': end.where(m.resolution != 'daily'), 'value': m.value.astype('float64') * m.scale.astype('float64'),
                        'resolution': m.resolution, 'raw_ref': m.record_key.astype(str)})
    # A value whose day cannot be placed (missing interval or civil date) is not guessed.
    return out[out.t.notna()].reset_index(drop=True)


def load(tiers):
    tiers = Path(tiers)
    path = tiers / 'measurements.parquet'
    measurements = pd.read_parquet(path) if path.is_file() else pd.DataFrame()
    parts = [df for df in (_heart_rate(tiers), from_measurements(measurements)) if len(df)]
    obs = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
    for column in ('t', 't_end'):
        obs[column] = pd.to_datetime(obs[column]).astype('datetime64[ns]')
    obs['value'] = obs['value'].astype('float64')
    return obs[COLUMNS].sort_values(['subject_id', 'metric', 't']).reset_index(drop=True)
