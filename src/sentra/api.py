"""Read-only API over processed wellness outputs (ported from archive/monorepo-v0 wp/api.py).

    uvicorn sentra.api:app --host 0.0.0.0 --port 8000

Every /api/v1 route needs `X-API-Key: <SENTRA_API_KEY>`. Subjects are pseudonymous participant
IDs (p01 ...). The API reads only files written by the processing job; it has no database or
provider credentials, starts no collection and changes nothing.
"""
import hmac
import json
import os
import re
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query

PSEUDONYM = re.compile(r'p[0-9]{2,4}')
TABLES = ('daily_features', 'cohort_daily')

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


_cache: dict = {}


def _table(name: str) -> pd.DataFrame:
    path = processed_dir() / f'{name}.parquet'
    if not path.is_file():
        raise HTTPException(404, f'{name} not produced yet; run the processing job')
    mtime = path.stat().st_mtime_ns
    hit = _cache.get(name)
    if not hit or hit[0] != mtime:
        _cache[name] = (mtime, pd.read_parquet(path))
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


@app.get('/health')
def health():
    meta = _metadata()
    files = {name: (processed_dir() / f'{name}.parquet').is_file() for name in TABLES}
    return {'status': 'ok', 'processed': files, 'days': meta.get('days')}


@app.get('/api/v1/metadata', dependencies=[Depends(require_key)])
def metadata():
    meta = _metadata()
    return {'notice': meta.get('notice'), 'thresholds_status': (meta.get('thresholds') or {}).get('_status'),
            'thresholds': meta.get('thresholds'), 'days': meta.get('days'), 'subjects': meta.get('subjects')}


@app.get('/api/v1/subjects', dependencies=[Depends(require_key)])
def subjects():
    return sorted(s for s in _table('daily_features').subject_id.astype(str).unique() if PSEUDONYM.fullmatch(s))


@app.get('/api/v1/daily', dependencies=[Depends(require_key)])
def daily(subject: str | None = None, since: str | None = Query(None, description='YYYY-MM-DD'),
          limit: int = Query(500, ge=1, le=5000)):
    d = _table('daily_features')
    d = d[d.subject_id.astype(str).str.fullmatch(PSEUDONYM.pattern)]
    if _subject(subject):
        d = d[d.subject_id == subject]
    d = _since(d, since)
    return {'notice': _metadata().get('notice'), 'rows': _records(d.sort_values(['subject_id', 'date']).tail(limit))}


@app.get('/api/v1/cohort', dependencies=[Depends(require_key)])
def cohort(since: str | None = Query(None, description='YYYY-MM-DD')):
    c = _since(_table('cohort_daily'), since)
    return {'notice': _metadata().get('notice'), 'rows': _records(c)}
