"""Opt-in compact collector projection; records and originals remain authoritative.

Each bounded input batch becomes a few array rows, without rebuilding a whole response
after every page fragment. Replacements remove exactly those record keys from all older
array rows in the same transaction as the record update. No bulk migration/deletion here.
"""
from collections import defaultdict
from decimal import Decimal

from psycopg.types.json import Jsonb

from .compaction import ARRAYS, SHARED, is_dense
from .datasets import canonical
from .errors import SentraError


def enabled(db):
    installed = db.execute("select to_regclass('collector_private.compact_control') is not null").fetchone()[0] is True
    if not installed:
        return False
    row = db.execute('select enabled from collector_private.compact_control where singleton').fetchone()
    if row is None:
        raise SentraError('Compact write control is missing; no records written.')
    return row[0] is True


def dense_records(records):
    # Match sequential upsert semantics if a caller supplies the same key twice.
    return list({(r['participant_id'],r['provider'],r['dataset'],r['record_key']):r
                 for r in records if is_dense(r['dataset'])}.values())


def replacement_bytes(db, records):
    total = 0
    for scope, keys in _scopes(records).items():
        total += db.execute('''select coalesce(sum(pg_column_size(s.*)),0) from audit.series s
            where participant_id=%s and provider=%s and dataset=%s and record_keys && %s''',
            (*scope, keys)).fetchone()[0]
    return int(total)


def _scopes(records):
    scopes = defaultdict(list)
    for r in records:
        scopes[(r['participant_id'],r['provider'],r['dataset'])].append(r['record_key'])
    return scopes


def replace(db, records):
    """Caller owns the transaction and capacity check; every parallel array keeps its indices."""
    for scope, keys in _scopes(records).items():
        where = 'participant_id=%s and provider=%s and dataset=%s'
        db.execute(f'delete from audit.series where {where} and record_keys <@ %s', (*scope, keys))
        # Keep all untouched keys, including their exact numeric scale, JSON nulls and timestamps.
        arrays = ','.join(f'{a}=array(select s.{a}[i] from generate_subscripts(s.record_keys,1) i '
                          'where not s.record_keys[i]=any(%s) order by i)' for a in ARRAYS)
        db.execute(f'update audit.series s set {arrays} where {where} and record_keys && %s',
                   (*([keys]*len(ARRAYS)), *scope, keys))
    groups = {}
    for r in records:
        seen = set()
        for m in r['measurements']:
            if m['metric'] in seen:
                raise SentraError('Duplicate measurement metric; compact batch rolled back.')
            seen.add(m['metric'])
            resolution = Decimal(str(m['resolution_seconds'])) if m['resolution_seconds'] is not None else None
            shared = (r['participant_id'],r['provider'],r['dataset'],m['metric'],m['source_response_id'],
                      *(m[k] for k in SHARED), resolution)
            # Decimal text, unlike numeric equality, distinguishes 60 from 60.0.
            key = canonical([*shared[:-1],str(resolution) if resolution is not None else None])
            if key not in groups:
                groups[key] = (shared, [[] for _ in ARRAYS])
            values = (r['record_key'], Decimal(str(m['value'])) if m['value'] is not None else None,
                      Jsonb(m['vendor_value']),m['measured_at'],m['interval_start'],m['interval_end'],
                      Jsonb(m['civil_date']),Jsonb(m['vendor_time']),m['collected_at'],m['source_pointer'])
            for target,value in zip(groups[key][1],values):
                target.append(value)
    casts = ('text','numeric','jsonb','timestamptz','timestamptz','timestamptz','jsonb','jsonb','timestamptz','text')
    placeholders = ','.join(['%s']*(5+len(SHARED)+1) + [f'%s::{t}[]' for t in casts])
    for shared, arrays in groups.values():
        db.execute(f'''insert into audit.series(participant_id,provider,dataset,metric,source_response_id,
            {','.join(SHARED)},resolution_seconds,{','.join(ARRAYS)}) values ({placeholders})''',
            (*shared,*arrays))
