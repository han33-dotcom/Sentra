"""Counts-only live check of the data the reviewer prototype needs (docs/reviewer-data-connections.md).

    python scripts/reviewer_live_check.py [--secrets .streamlit/secrets.toml]

Operator use only, with the read-only viewer configuration. It reads the published board, the
dataset catalog, consent rows, coverage and recent run failures through `ViewerReader`, which
reserves transfer budget before every read. Output is aggregate counts per device and dataset;
it never prints participant IDs, names or readings. Nothing is written to Sentra.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys
import tempfile
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from sentra.processing.board import FIELDS  # noqa: E402

DETAIL_DATASETS = ('sleep', 'minute_heart-rate', 'minute_steps', 'original_heart-rate', 'exercise', 'workout',
                   'daily_steps', 'cycle', 'recovery')


def summarize(board, catalog, consents, detail_rows, coverage_rows, failure_rows):
    """Aggregate-only summary. Inputs are reader results; nothing per person is returned."""
    people = [p for p in board.get('people', []) if isinstance(p, dict)]
    devices = Counter(p.get('device') for p in people)
    keys = list(FIELDS) + ['lvl', 'f', 'a']
    fields = defaultdict(dict)
    day_counts = defaultdict(list)
    months = Counter()
    for device in devices:
        group = [p for p in people if p.get('device') == device]
        days = [d for p in group for d in p.get('days', []) if isinstance(d, dict)]
        for p in group:
            day_counts[device].append(len(p.get('days', [])))
        for d in days:
            months[(device, str(d.get('d', ''))[:7])] += 1
        for key in keys:
            with_key = [p for p in group if any(key in d for d in p.get('days', []) if isinstance(d, dict))]
            share = sum(key in d for d in days) / len(days) if days else 0
            fields[key][device] = {'people': len(with_key), 'share_of_days': round(share, 3)}
    datasets = defaultdict(lambda: {'people_with_rows': 0, 'rows': 0, 'latest_day': None, 'authorization': Counter()})
    for row in catalog:
        item = datasets[(row.get('provider'), row.get('dataset'))]
        item['authorization'][row.get('authorization_status')] += 1
        if (row.get('measurement_rows') or 0) > 0:
            item['people_with_rows'] += 1
            item['rows'] += row['measurement_rows']
        latest = row.get('latest_civil_day') or row.get('latest_point_time') or row.get('latest_interval_end')
        if latest and (item['latest_day'] is None or str(latest)[:10] > item['latest_day']):
            item['latest_day'] = str(latest)[:10]
    current = [c for c in consents if c.get('withdrawn') is False and c.get('membership_open') is True]
    return {
        'board': {'built_at': board.get('built_at'), 'data_through': board.get('data_through'),
                  'assessment_version': board.get('assessment_version'), 'board_version': board.get('board_version'),
                  'people_by_device': dict(devices),
                  'days_per_person': {d: {'min': min(v), 'median': statistics.median(v), 'max': max(v)}
                                      for d, v in day_counts.items() if v},
                  'person_days_by_month': {f'{d} {m}': n for (d, m), n in sorted(months.items(), key=str)},
                  'fields': dict(fields)},
        'datasets': {f'{p} {d}': {**v, 'authorization': dict(v['authorization'])} for (p, d), v in sorted(datasets.items(), key=str)},
        'detail': [dict(r) for r in detail_rows],
        'coverage': [dict(r) for r in coverage_rows],
        'failures_last_30_days': [dict(r) for r in failure_rows],
        'consent': {'current': len(current), 'sharing': dict(Counter(c.get('sharing') for c in current)),
                    'demonstration': sum(c.get('demonstration') is True for c in current),
                    'withdrawn_or_closed': len(consents) - len(current)},
    }


def main(argv=None):
    from sentra.viewer_config import runtime_settings
    from sentra.viewer_reader import ViewerReader
    parser = argparse.ArgumentParser(description='Counts-only reviewer data check (read-only viewer role)')
    parser.add_argument('--secrets', type=Path, default=Path('.streamlit/secrets.toml'))
    args = parser.parse_args(argv)
    secrets = tomllib.loads(args.secrets.read_text(encoding='utf-8'))
    reserved = [0]
    with tempfile.TemporaryDirectory() as folder:
        credentials, limits, _ = runtime_settings(secrets, folder)
        reader = ViewerReader(credentials, limits, lambda: None)
        original = reader.reserve
        def counted(amount):
            reserved[0] += amount
            original(amount)
        reader.reserve = counted
        try:
            board = reader.board()
            catalog = reader.catalog()
            _, consents = reader.organization_rows()
            source = reader._measurement_source()
            day = "(coalesce(m.measured_at,m.interval_start) at time zone 'Asia/Beirut')::date"
            detail = reader._rows(f'''select m.provider,m.dataset,count(distinct m.participant_id) people,
                count(distinct (m.participant_id,{day})) person_days,min({day}) first_day,max({day}) last_day,
                count(*) filter (where m.metric like '/sleep/stages/%%/type') stage_rows
                from {source} m where m.dataset=any(%s) group by 1,2 order by 1,2''',
                (list(DETAIL_DATASETS),), allowance=65_536)
            coverage = reader._rows('''select s.provider,s.dataset,count(*) connections,
                count(*) filter (where jsonb_array_length(s.covered_intervals)>0) with_coverage,
                min(c.first_requested) first_requested
                from audit.connection_state s left join lateral (select min(x->>'requested_civil_start') first_requested
                  from jsonb_array_elements(s.covered_intervals) x) c on true
                group by 1,2 order by 1,2''', allowance=65_536)
            failures = reader._rows('''select r.provider,f->>'dataset' dataset,f->>'outcome' outcome,count(*) failures
                from audit.collection_runs r cross join lateral jsonb_array_elements(coalesce(r.details->'failures','[]')) f
                where r.started_at > now()-interval '30 days' group by 1,2,3 order by 1,2,3''', allowance=65_536)
        finally:
            reader.close()
    summary = summarize(board, catalog, consents, detail, coverage, failures)
    summary['transfer_reserved_bytes'] = reserved[0]
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
