"""Parquet storage tiers derived from shared audit tables; audit rows and originals never change.

Reads run as sentra_viewer (SELECT only, read-only transactions) and reserve egress through
public.sentra_reserve_viewer_egress before any rows leave the database. Objects go to the
private 'sentra-tiers' bucket after the object-capacity guard accepts their total size.

  hr_raw/<pid>.parquet     original-resolution heart rate, last HOT_DAYS days (hot tier)
  hr_minute/<pid>.parquet  per-minute heart rate: vendor 60 s rollups and Sentra minutes from raw (warm)
  measurements.parquet     every other measurement in narrow typed columns
  sessions.parquet         sleep, workout and cycle sessions
  size_report.json         bytes per tier and a bounded projection
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
import json
from pathlib import Path

import psycopg

from .errors import SentraError
from .shared import CapacityStop

TIER_BUCKET = 'sentra-tiers'
HOT_DAYS = 30
PARQUET = 'application/vnd.apache.parquet'
HR_RAW = ('original_heart-rate', '/heartRate/beatsPerMinute')
HR_MINUTE_DATASET = 'minute_heart-rate'
HR_MINUTE_METRICS = {'/heartRate/beatsPerMinuteAvg': 'mean', '/heartRate/beatsPerMinuteMin': 'min',
                     '/heartRate/beatsPerMinuteMax': 'max'}
RESERVE_CHUNK = 90_000_000  # the viewer reservation function accepts at most 100 MB per call
DEFAULT_MAX_READ_BYTES = 500_000_000
MAX_OBJECT_BYTES = 52_428_800  # bucket file_size_limit in sql/006_parquet_tiers.sql

QUERIES = {
    'hr_raw': ('''select participant_id,provider,measured_at,value from audit.measurements
        where dataset=%s and metric=%s and measured_at is not null and value is not null''', HR_RAW),
    'hr_minute': ('''select participant_id,provider,interval_start,metric,value from audit.measurements
        where dataset=%s and metric=any(%s) and interval_start is not null and value is not null''',
        (HR_MINUTE_DATASET, list(HR_MINUTE_METRICS))),
    'measurements': ('''select participant_id,provider,dataset,record_key,metric,value,unit,value_kind,availability,
        measured_at,interval_start,interval_end,civil_date,vendor_value from audit.measurements
        where dataset<>%s and not (dataset=%s and metric=any(%s))''',
        (HR_RAW[0], HR_MINUTE_DATASET, list(HR_MINUTE_METRICS))),
    'sessions': ('''select participant_id,provider,dataset,record_key,session_type,started_at,ended_at,
        score_state,provisional from audit.sessions''', ()),
}


def _pa():
    try:
        import pyarrow, pyarrow.parquet
        return pyarrow
    except ImportError:
        raise SentraError('Parquet tiers need pyarrow: pip install "sentra-audit[tiers]".') from None


class AuditReader:
    """Read-only access: refuses any role but sentra_viewer and reserves egress before reading."""

    def __init__(self, db, limits, *, max_read_bytes=DEFAULT_MAX_READ_BYTES):
        self.db, self.limits, self.max_read_bytes, self.read_bytes = db, limits, max_read_bytes, 0
        try:
            role = db.execute('select session_user').fetchone()[0]
        except psycopg.Error:
            raise SentraError('Tier reader database unavailable; sensitive details omitted.') from None
        if role != 'sentra_viewer':
            raise SentraError('Parquet tiers read only through the read-only sentra_viewer role.')

    def reserve(self, amount):
        try:
            while amount > 0:
                chunk = min(amount, RESERVE_CHUNK)
                self.db.execute('select public.sentra_reserve_viewer_egress(%s,%s)', (chunk, self.limits.monthly_egress_bytes))
                amount -= chunk
        except psycopg.Error:
            raise CapacityStop('Egress allowance unavailable, stale or exhausted; no tier data read.') from None

    def usage(self):
        self.reserve(32_768)
        usage = self.db.execute('select public.sentra_viewer_status()').fetchone()[0]
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('database_bytes', 'object_bytes', 'egress_bytes', 'audit_bytes')):
            raise CapacityStop('Storage usage unavailable; verify project usage before building tiers.')
        return usage

    def read(self, name):
        query, values = QUERIES[name]
        self.reserve(65_536)
        try:
            # One read-only snapshot: the size estimate and the rows cover the same data.
            with self.db.transaction():
                self.db.execute('set transaction isolation level repeatable read, read only')
                count, size = self.db.execute(f'select count(*),coalesce(sum(octet_length(t::text)),0) from ({query}) t', values).fetchone()
                size = int(size) + int(count) * 64
                if self.read_bytes + size > self.max_read_bytes:
                    raise CapacityStop(f'Tier read would exceed the per-run egress cap ({self.max_read_bytes / 1e6:.0f} MB); nothing uploaded.')
                self.reserve(int(size * 1.2) + 65_536)
                self.read_bytes += size
                with self.db.cursor(name='sentra_tiers_' + name) as cursor:
                    cursor.itersize = 5_000
                    cursor.execute(query, values)
                    return cursor.fetchall()
        except psycopg.Error:
            raise SentraError('Tier read failed; sensitive details omitted. Nothing was uploaded.') from None


def epoch(value):
    return int(value.timestamp()) if isinstance(value, datetime) else None


def number(value):
    return float(value) if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else None


def civil_text(value):
    if isinstance(value, str):
        return value[:10] if len(value) >= 10 else None
    if isinstance(value, dict):
        part = value.get('date', value) if isinstance(value.get('date'), dict) else value
        try:
            return f"{int(part['year']):04d}-{int(part['month']):02d}-{int(part['day']):02d}"
        except (KeyError, TypeError, ValueError):
            return None
    return None


def day_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def heart_rate_type(values):
    pa = _pa()
    integral = all(v is not None and float(v).is_integer() and 0 <= v <= 65_535 for v in values)
    return pa.uint16() if integral else pa.float64()


def hr_tables(raw_rows, vendor_rows, now):
    """Per participant: hot raw table (last HOT_DAYS days) and warm minute table."""
    pa = _pa()
    cutoff = epoch(now - timedelta(days=HOT_DAYS))
    raw, minutes = {}, {}
    for pid, provider, measured_at, value in raw_rows:
        raw.setdefault(pid, {})[(provider, epoch(measured_at))] = number(value)  # same instant: one reading
    for pid, readings in raw.items():
        buckets = {}
        for (provider, ts), bpm in readings.items():
            buckets.setdefault((provider, ts // 60 * 60), []).append(bpm)
        for (provider, minute), values in buckets.items():
            minutes.setdefault(pid, []).append({'provider': provider, 'ts': minute, 'source': 'sentra_from_raw',
                'mean': round(sum(values) / len(values), 1), 'min': min(values), 'max': max(values), 'n': len(values)})
    vendor = {}
    for pid, provider, start, metric, value in vendor_rows:
        vendor.setdefault((pid, provider, epoch(start)), {})[HR_MINUTE_METRICS[metric]] = number(value)
    for (pid, provider, ts), stats in vendor.items():
        # Vendor rollups stay separate rows from Sentra minutes; they are never merged.
        minutes.setdefault(pid, []).append({'provider': provider, 'ts': ts, 'source': 'vendor_60s_rollup',
            'mean': stats.get('mean'), 'min': stats.get('min'), 'max': stats.get('max'), 'n': None})
    hot, warm = {}, {}
    for pid, readings in raw.items():
        rows = sorted((p, ts, bpm) for (p, ts), bpm in readings.items() if ts >= cutoff)
        if rows:
            hot[pid] = pa.table({'provider': pa.array([r[0] for r in rows]).dictionary_encode(),
                                 'ts': pa.array([r[1] for r in rows], pa.int64()),
                                 'bpm': pa.array([r[2] for r in rows], heart_rate_type([r[2] for r in rows]))})
    for pid, rows in minutes.items():
        rows.sort(key=lambda r: (r['ts'], r['source'], r['provider']))
        warm[pid] = pa.table({'provider': pa.array([r['provider'] for r in rows]).dictionary_encode(),
                              'ts': pa.array([r['ts'] for r in rows], pa.int64()),
                              'source': pa.array([r['source'] for r in rows]).dictionary_encode(),
                              **{k: pa.array([r[k] for r in rows], pa.float32()) for k in ('mean', 'min', 'max')},
                              'n': pa.array([r['n'] for r in rows], pa.uint16())})
    return hot, warm


def measurements_table(rows):
    pa = _pa()
    columns = {k: [] for k in ('participant', 'provider', 'dataset', 'record_key', 'metric', 'ts', 'end_ts', 'civil_date',
                               'value', 'unit', 'value_kind', 'availability', 'vendor_value')}
    for pid, provider, dataset, key, metric, value, unit, kind, availability, measured, start, end, civil, vendor in rows:
        for column, item in (('participant', pid), ('provider', provider), ('dataset', dataset), ('record_key', key),
                             ('metric', metric), ('ts', epoch(measured or start)), ('end_ts', epoch(end)),
                             ('civil_date', civil_text(civil)), ('value', number(value)), ('unit', unit),
                             ('value_kind', kind), ('availability', availability),
                             # Non-numeric vendor values (enums, text) stay available; numbers are not duplicated.
                             ('vendor_value', json.dumps(vendor, sort_keys=True) if value is None and vendor is not None else None)):
            columns[column].append(item)
    order = sorted(range(len(rows)), key=lambda i: (columns['participant'][i], columns['dataset'][i], columns['metric'][i],
                                                    columns['ts'][i] if columns['ts'][i] is not None else -1,
                                                    columns['civil_date'][i] or '', columns['record_key'][i]))
    def column(name, kind=None, dictionary=False):
        array = pa.array([columns[name][i] for i in order], kind)
        return array.dictionary_encode() if dictionary else array
    return pa.table({'participant': column('participant', dictionary=True), 'provider': column('provider', dictionary=True),
                     'dataset': column('dataset', dictionary=True), 'record_key': column('record_key', pa.string()),
                     'metric': column('metric', dictionary=True), 'ts': column('ts', pa.int64()), 'end_ts': column('end_ts', pa.int64()),
                     'civil_date': column('civil_date', pa.string()), 'value': column('value', pa.float64()),
                     'unit': column('unit', pa.string(), True), 'value_kind': column('value_kind', dictionary=True),
                     'availability': column('availability', dictionary=True), 'vendor_value': column('vendor_value', pa.string())})


def sessions_table(rows):
    pa = _pa()
    rows = sorted(rows, key=lambda r: (r[0], r[2], epoch(r[5]) or -1, r[3]))
    names = ('participant', 'provider', 'dataset', 'record_key', 'session_type', 'start_ts', 'end_ts', 'score_state', 'provisional')
    data = {n: [r[i] for r in rows] for i, n in enumerate(names)}
    return pa.table({'participant': pa.array(data['participant'], pa.string()).dictionary_encode(),
                     'provider': pa.array(data['provider'], pa.string()).dictionary_encode(),
                     'dataset': pa.array(data['dataset'], pa.string()).dictionary_encode(),
                     'record_key': pa.array(data['record_key'], pa.string()),
                     'session_type': pa.array(data['session_type'], pa.string()).dictionary_encode(),
                     'start_ts': pa.array([epoch(v) for v in data['start_ts']], pa.int64()),
                     'end_ts': pa.array([epoch(v) for v in data['end_ts']], pa.int64()),
                     'score_state': pa.array(data['score_state'], pa.string()),
                     'provisional': pa.array(data['provisional'], pa.bool_())})


def parquet_bytes(table):
    pa = _pa()
    buffer = io.BytesIO()
    pa.parquet.write_table(table, buffer, compression='zstd')
    return buffer.getvalue()


def person_days(table, *, participant='participant'):
    if table.num_rows == 0:
        return 0
    days = set()
    parts = table.column(participant).to_pylist() if participant else [None] * table.num_rows
    ts = table.column('ts').to_pylist()
    civil = table.column('civil_date').to_pylist() if 'civil_date' in table.column_names else [None] * table.num_rows
    for p, t, c in zip(parts, ts, civil):
        if t is not None or c:
            days.add((p, day_of(t) if t is not None else c))
    return len(days)


def size_report(objects, days, usage, *, employees=10, period_days=30):
    """Measured bytes per tier and a linear projection; hot raw HR is capped at HOT_DAYS."""
    tiers = {}
    for tier in ('hr_raw', 'hr_minute', 'measurements', 'sessions'):
        size = sum(len(body) for key, body in objects.items() if key.split('/', 1)[0].removesuffix('.parquet') == tier)
        per_day = size / days[tier] if days.get(tier) else None
        retained = min(period_days, HOT_DAYS) if tier == 'hr_raw' else period_days
        tiers[tier] = {'bytes': size, 'person_days': days.get(tier, 0), 'bytes_per_person_day': round(per_day) if per_day else None,
                       'projected_bytes': round(per_day * employees * retained) if per_day else None}
    audit_per_day = usage['audit_bytes'] / days['measurements'] if days.get('measurements') else None
    total = sum(t['projected_bytes'] or 0 for t in tiers.values())
    return {'tiers': tiers, 'total_bytes': sum(t['bytes'] for t in tiers.values()),
            'projection': {'employees': employees, 'days': period_days, 'tier_bytes': total,
                           'audit_database_bytes': round(audit_per_day * employees * period_days) if audit_per_day else None},
            'meaning': 'Linear projection from observed person-days; hr_raw keeps only the last 30 days. '
                       'Datasets missing for some days or participants make per-day rates optimistic. Decimal bytes.'}


def build(reader, limits, *, now=None, employees=10, period_days=30):
    """Read once, build every tier in memory and return {object_key: bytes} plus the size report."""
    now = now or datetime.now(timezone.utc)
    reader.usage()
    raw, vendor = reader.read('hr_raw'), reader.read('hr_minute')
    measurements, sessions = measurements_table(reader.read('measurements')), sessions_table(reader.read('sessions'))
    hot, warm = hr_tables(raw, vendor, now)
    objects = {f'hr_raw/{pid}.parquet': parquet_bytes(t) for pid, t in sorted(hot.items())}
    objects.update({f'hr_minute/{pid}.parquet': parquet_bytes(t) for pid, t in sorted(warm.items())})
    objects['measurements.parquet'] = parquet_bytes(measurements)
    objects['sessions.parquet'] = parquet_bytes(sessions)
    days = {'hr_raw': sum(person_days(t, participant=None) for t in hot.values()),
            'hr_minute': sum(person_days(t, participant=None) for t in warm.values()),
            'measurements': person_days(measurements)}
    days['sessions'] = days['measurements']
    usage = reader.usage()
    report = {'built_at': now.isoformat(), 'read_bytes': reader.read_bytes,
              'objects': {key: len(body) for key, body in sorted(objects.items())},
              **size_report(objects, days, usage, employees=employees, period_days=period_days)}
    return objects, report


def fetch(storage, folder, *, maximum=MAX_OBJECT_BYTES):
    """Download the latest published tiers listed in size_report.json; storage.reserve covers egress."""
    code, body = storage.request('GET', 'size_report.json', maximum=1_000_000)
    if code != 200:
        raise SentraError(f'Tier report unavailable (HTTP {code}); run tiers-build first.')
    report = json.loads(body)
    for key, size in report.get('objects', {}).items():
        path = (Path(folder) / key).resolve()
        if (not isinstance(size, int) or not 0 <= size <= maximum or '..' in key
                or '\\' in key or ':' in key or not path.is_relative_to(Path(folder).resolve())):
            raise SentraError('Tier report lists an invalid object; nothing processed.')
        code, data = storage.request('GET', key, maximum=size + 65_536)
        if code != 200 or len(data) != size:
            raise SentraError(f'Tier object {key} missing or changed since its report; rebuild tiers.')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return report


def publish(objects, report, storage, reader, limits, *, local_dir=None):
    """Upload after the capacity guard accepts the full size, or write to a private local folder."""
    body = json.dumps(report, indent=2).encode()
    if any(len(b) > MAX_OBJECT_BYTES for b in objects.values()):
        raise SentraError('A tier object exceeds the 50 MB bucket limit; split the tier before uploading.')
    if local_dir is not None:
        for key, data in {**objects, 'size_report.json': body}.items():
            path = Path(local_dir) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {'uploaded': 0, 'local': str(local_dir)}
    # Conservative: replaced objects are counted at full size, never netted against older versions.
    limits.check(reader.usage(), object_add=sum(len(b) for b in objects.values()) + len(body))
    for key, data in {**objects, 'size_report.json': body}.items():
        code, _ = storage.request('POST', key, data=data, maximum=65_536, upsert=True,
                                  content_type='application/json' if key.endswith('.json') else PARQUET)
        if code not in (200, 201):
            raise SentraError(f'Tier upload failed (HTTP {code}) at {key}; earlier tier objects may be newer than others. Repeat the build.')
    return {'uploaded': len(objects) + 1, 'bucket': TIER_BUCKET}
