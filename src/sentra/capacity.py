"""Capacity and collection measurements for #50: aggregate snapshots, compared over time.

A snapshot holds only counts, sizes and run outcomes per participant pseudonym, provider and
dataset; no readings. Snapshots append to a private JSON-lines log beneath .private, and the
difference between two snapshots is the observed ongoing growth (initial imports are reported
separately by `shared-growth`).
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from .vault import atomic_write


def snapshot(backend, *, days=14):
    backend.reserve(131_072)
    db = backend.db
    usage = backend.usage()
    tables = {name: int(size) for name, size in db.execute('''select n.nspname||'.'||c.relname, pg_total_relation_size(c.oid)
        from pg_class c join pg_namespace n on n.oid=c.relnamespace
        where n.nspname in ('audit','org','enrollment_private') and c.relkind='r' order by 1''').fetchall()}
    rows = db.execute('''select participant_id, provider, dataset, count(*) from audit.measurements
        group by 1,2,3 order by 1,2,3''').fetchall()
    runs = db.execute('''select participant_id, provider, status, count(*) from audit.collection_runs
        where started_at >= now() - make_interval(days => %s) group by 1,2,3 order by 1,2,3''', (days,)).fetchall()
    return {'taken_at': datetime.now(timezone.utc).isoformat(), 'usage': usage, 'audit_table_bytes': tables,
            'measurement_rows': [{'participant_id': p, 'provider': v, 'dataset': d, 'rows': n} for p, v, d, n in rows],
            'runs_last_days': days,
            'runs': [{'participant_id': p, 'provider': v, 'status': s, 'count': n} for p, v, s, n in runs]}


def append(log, entry):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    previous = log.read_text(encoding='utf-8') if log.is_file() else ''
    atomic_write(log, (previous + json.dumps(entry, sort_keys=True) + '\n').encode())


def growth(log):
    """Per-day change between the first and last snapshot in the log."""
    entries = [json.loads(line) for line in Path(log).read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(entries) < 2:
        return {'snapshots': len(entries), 'meaning': 'at least two snapshots are needed'}
    first, last = entries[0], entries[-1]
    when = lambda entry: datetime.fromisoformat(entry['taken_at'])
    rate = lambda a, b, key: (round(((b['usage'].get(key) or 0) - (a['usage'].get(key) or 0))
                                    / ((when(b) - when(a)).total_seconds() / 86_400))
                              if when(b) > when(a) else None)
    # The egress ledger restarts each UTC month, so compare only snapshots from the latest month.
    month = lambda entry: when(entry).astimezone(timezone.utc).strftime('%Y-%m')
    same_month = next(e for e in entries if month(e) == month(last))
    return {'snapshots': len(entries), 'from': first['taken_at'], 'to': last['taken_at'],
            'days': round((when(last) - when(first)).total_seconds() / 86_400, 2),
            'database_bytes_per_day': rate(first, last, 'database_bytes'),
            'object_bytes_per_day': rate(first, last, 'object_bytes'),
            'egress_bytes_per_day': rate(same_month, last, 'egress_bytes'), 'egress_from': same_month['taken_at'],
            'meaning': 'Observed change between snapshots; includes corrections and bloat. Egress is compared only '
                       'within the latest UTC month (its ledger resets monthly); null until two snapshots share it.'}
