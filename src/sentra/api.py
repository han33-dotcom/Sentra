"""Read-only API over processed wellness outputs (ported from archive/monorepo-v0 wp/api.py).

    uvicorn sentra.api:app --host 0.0.0.0 --port 8000

Team requests use X-API-Key. Organization requests use an individual bearer credential
and fresh database roles/consent through sentra.access. Outputs remain read-only;
organization policy reads reserve egress and never collect or change participant data.
"""
import hmac
import json
import os
import re
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .access import Access, K_ANONYMITY
from .api_access import bearer_email, organization_access
from .processing.board import FIELDS
from .processing.pipeline import BASELINE_FEATURES, DAY_COLUMNS, RULES, NOTICE, TH, cohort as build_cohort

PSEUDONYM = re.compile(r'p[0-9]{2,4}')
TABLES = ('daily_features', 'cohort_daily')
DAILY_COLUMNS = (set(DAY_COLUMNS) | {v[0] for v in FIELDS.values()}
                 | {v[0] for v in RULES.values()} | {'assess_' + k for k in RULES}
                 | {f + suffix for f in BASELINE_FEATURES for suffix in ('_base', '_z')}
                 | {'device', 'sleep_min', 'restless_min', 'awake_in_bed_min', 'in_bed_min',
                    'sleep_eff', 'valid_day', 'usable_day', 'wellness_signals', 'rules_assessed',
                    'assessment_state', 'assessment_reasons', 'wellness_level',
                    'flag_sustained_high_hr', 'flag_long_inactivity_in_shift'})

app = FastAPI(title='Sentra read API', version='0.1.0',
              description='Read-only v0 wellness features and k-anonymous cohort view. Not a medical assessment.')


def processed_dir() -> Path:
    return Path(os.environ.get('SENTRA_PROCESSED_DIR', '/data/processed'))


def require_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get('SENTRA_API_KEY', '')
    if len(expected) < 32:
        raise HTTPException(503, 'SENTRA_API_KEY is not set (minimum 32 characters)')
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, 'missing or wrong X-API-Key')


def require_access(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    if authorization is not None:
        if x_api_key is not None:
            raise HTTPException(401, 'Use exactly one authentication method')
        return organization_access(bearer_email(authorization))
    require_key(x_api_key)
    return Access('api-operator', 'team', None)


@app.middleware('http')
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Authorization, X-API-Key'
    return response


_cache: dict = {}


def _table(name: str) -> pd.DataFrame:
    path = processed_dir() / f'{name}.parquet'
    if not path.is_file():
        raise HTTPException(404, f'{name} not produced yet; run the processing job')
    mtime = path.stat().st_mtime_ns
    signature = (str(path.resolve()), mtime, path.stat().st_size)
    hit = _cache.get(name)
    if not hit or hit[0] != signature:
        _cache[name] = (signature, pd.read_parquet(path))
    return _cache[name][1]


def _metadata() -> dict:
    path = processed_dir() / 'metadata.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def _records(df: pd.DataFrame):
    return json.loads(df.to_json(orient='records', date_format='iso'))


def _since(df, since):
    if since is None:
        return df
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', since):
        raise HTTPException(422, 'since must be YYYY-MM-DD')
    try:
        day = pd.Timestamp(since)
    except ValueError:
        raise HTTPException(422, 'since must be YYYY-MM-DD') from None
    return df[pd.to_datetime(df.date) >= day]


def _subject(subject):
    if subject is not None and not PSEUDONYM.fullmatch(subject):
        raise HTTPException(422, 'subject must be a pseudonymous participant ID such as p01')
    return subject


def _daily_scope(access, *, group=False):
    d = _table('daily_features')
    d = d[d.subject_id.astype(str).str.fullmatch(PSEUDONYM.pattern)]
    if not access.is_team:
        allowed = access.contributors if group else access.individuals
        d = d[d.subject_id.isin(allowed)]
        # An unrecognized producer column can never turn into an organization download.
        d = d[[c for c in d.columns if c in DAILY_COLUMNS]]
    return d


@app.get('/health')
def health():
    files = {name: (processed_dir() / f'{name}.parquet').is_file() for name in TABLES}
    return {'status': 'ok', 'processed': files}


@app.get('/api/v1/metadata')
def metadata(access: Access = Depends(require_access)):
    meta = _metadata()
    if not access.is_team:
        d = _daily_scope(access)
        days = pd.to_datetime(d.date)
        return {'notice': NOTICE, 'assessment_version': meta.get('assessment_version'),
                'thresholds_status': TH['_status'], 'thresholds': TH,
                'days': [days.min().date().isoformat(), days.max().date().isoformat()] if len(d) else None,
                'subjects': int(d.subject_id.nunique())}
    return {'notice': meta.get('notice'), 'assessment_version': meta.get('assessment_version'), 'thresholds_status': (meta.get('thresholds') or {}).get('_status'),
            'thresholds': meta.get('thresholds'), 'days': meta.get('days'), 'subjects': meta.get('subjects')}


@app.get('/api/v1/subjects')
def subjects(access: Access = Depends(require_access)):
    return sorted(_daily_scope(access).subject_id.astype(str).unique())


@app.get('/api/v1/daily')
def daily(subject: str | None = None, since: str | None = Query(None, description='YYYY-MM-DD'),
          limit: int = Query(500, ge=1, le=5000), access: Access = Depends(require_access)):
    d = _daily_scope(access)
    if _subject(subject):
        d = d[d.subject_id == subject]
    d = _since(d, since)
    return {'notice': _metadata().get('notice') if access.is_team else NOTICE,
            'rows': _records(d.sort_values(['subject_id', 'date']).tail(limit))}


@app.get('/api/v1/cohort')
def cohort(since: str | None = Query(None, description='YYYY-MM-DD'), access: Access = Depends(require_access)):
    if not access.is_team:
        d = _since(_daily_scope(access, group=True), since)
        required = {'device', 'usable_day', 'sleep_min', 'hr_mean', 'steps',
                    'wellness_level', 'wellness_signals', 'flag_short_sleep', 'flag_sustained_high_hr'}
        if not required.issubset(d.columns):
            raise HTTPException(503, 'Organization cohort provenance is unavailable; rebuild processed outputs')
        if d.empty:
            return {'notice': NOTICE, 'rows': []}
        if d.duplicated(['subject_id', 'date']).any() or d.groupby('subject_id').device.nunique().gt(1).any():
            raise HTTPException(503, 'Organization cohort provenance is inconsistent')
        providers = {'Fitbit': 'google_health', 'WHOOP': 'whoop'}
        devices = {pid: providers.get(rows.device.iloc[0]) if rows.device.notna().all() else None
                   for pid, rows in d.groupby('subject_id')}
        c = build_cohort(d, devices)
        # Never serve the global precomputed cohort, hidden rows or exact sub-k counts.
        c = c[c.workers >= K_ANONYMITY].copy()
        for column in (name for name in c.columns if name.startswith('n_')):
            c[column] = c[column].where(c[column] >= K_ANONYMITY)
        return {'notice': NOTICE, 'rows': _records(c)}
    c = _table('cohort_daily')
    if 'device' not in c.columns:
        # Written before per-device group statistics; its pooled rows must not be served.
        raise HTTPException(503, 'cohort_daily predates per-device group statistics; rerun the processing job to rebuild it')
    c = _since(c, since)
    return {'notice': _metadata().get('notice'), 'rows': _records(c)}
