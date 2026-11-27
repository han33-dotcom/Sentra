"""Counts-only live check of the data the reviewer prototype needs (docs/reviewer-data-connections.md).

    python scripts/reviewer_live_check.py --org ORG_ID [--secrets .private/reviewer-live-check.toml]

Operator use only. Authorization and scope:
- The operator holds a viewer-only secrets file with a `[viewer]` section and nothing else. The hosted
  app's `[auth]` section is refused, so the hosted-viewer November allowance is never used. Every read
  reserves the ordinary viewer allowance first, and the run stops before `--max-transfer-bytes`.
- Scope is one organization: participants with a current, non-withdrawn consent in an open
  membership of `--org` (the officer's group-statistics population, `sentra.access`). Database
  queries are filtered to that population; the published board is one file, filtered after download.
- Output is aggregates only. A count below `cohort_k_anonymity` (5) prints as "fewer than 5",
  and every figure derived from such a group is withheld. Dates are the day reached by at least
  five people, never one person's date. No participant IDs, names or readings are printed.

Share the output only in the team's private channel or with the task owner, never in the public
repository, its pull requests or issues; record only conclusions in the docs. Nothing is written
to Sentra.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import json
from pathlib import Path
import re
import statistics
import sys
import tempfile
import tomllib
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from sentra.access import K_ANONYMITY, ORG_ID, current  # noqa: E402
from sentra.processing.board import FIELDS  # noqa: E402
from sentra.processing.metric_map import MAPPING  # noqa: E402
from sentra.viewer_reader import CIVIL  # noqa: E402

LOCAL = ZoneInfo('Asia/Beirut')
DETAIL_DATASETS = ('sleep', 'minute_heart-rate', 'minute_steps', 'original_heart-rate', 'exercise', 'workout',
                   'daily_steps', 'cycle', 'recovery')
BOARD_KEYS = tuple(FIELDS) + ('lvl', 'f', 'a')
DESTINATION = 'Private team channel or task owner only; never the public repository, pull requests or issues.'
NAME = re.compile(r'[a-z0-9_-]+')


def dataset_basis():
    """(provider, dataset) -> documented day basis from processing's metric map (one basis per dataset)."""
    found = defaultdict(set)
    for (provider, dataset, _), (_, _, _, basis) in MAPPING.items():
        found[(provider, dataset)].add(basis)
    mixed = sorted(k for k, v in found.items() if len(v) != 1)
    if mixed:
        raise ValueError(f'datasets with more than one day basis: {mixed}')
    return {k: next(iter(v)) for k, v in found.items()}


def _local(column):
    return f"to_char({column} at time zone 'Asia/Beirut','YYYY-MM-DD')"


def day_sql():
    """SQL for the Asia/Beirut day a reading belongs to (docs/processing.md), or NULL when it cannot be placed.

    Mapped datasets use processing's basis: sleep by its wake day (interval end), WHOOP cycles and
    recoveries by cycle start, vendor daily values by their civil date (kept civil, never converted),
    intraday points and minute rollups by their own time. Other datasets use their civil date, then
    point time, then interval start. Unknown days stay NULL and are excluded by the caller.
    """
    # A record's rows share its day: a sleep stage row carries the stage's own interval, but the
    # session it belongs to ends on the wake day (latest interval end within the record).
    record = 'over (partition by m.participant_id,m.provider,m.dataset,m.record_key)'
    expr = {'end': _local(f'max(m.interval_end) {record}'), 'start': _local(f'min(m.interval_start) {record}'),
            'civil': f'({CIVIL})', None: _local('coalesce(m.measured_at,m.interval_start)')}
    cases = []
    for (provider, dataset), basis in sorted(dataset_basis().items()):
        if not (NAME.fullmatch(provider) and NAME.fullmatch(dataset)):
            raise ValueError(f'unexpected dataset name {(provider, dataset)!r}')
        cases.append(f"when m.provider='{provider}' and m.dataset='{dataset}' then {expr[basis]}")
    fallback = f"coalesce(({CIVIL}),{_local('m.measured_at')},{_local('m.interval_start')})"
    return 'case ' + ' '.join(cases) + f' else {fallback} end'


def detail_sql(source):
    """Per person and dataset: placed days, first/last day, rows with no placeable day, sleep-stage rows.

    Parameters: datasets, participant IDs, row limit. Rows whose day is unknown never count as a day.
    """
    return f'''select provider,dataset,participant_id,count(distinct day) person_days,
        min(day) first_day,max(day) last_day,count(*) filter (where day is null) unplaced_rows,
        count(*) filter (where day is not null and metric like '/sleep/stages/%%/type') stage_rows
        from (select m.provider,m.dataset,m.participant_id,m.metric,{day_sql()} as day from {source} m
              where m.dataset=any(%s) and m.participant_id=any(%s)) x
        group by 1,2,3 order by 1,2,3 limit %s'''


def count(n, k=K_ANONYMITY):
    return n if n >= k else f'fewer than {k}'


def kth(values, k=K_ANONYMITY, latest=False):
    """Day reached by at least k people: k-th earliest (or latest) per-person day; None below k."""
    days = sorted((v for v in values if v), reverse=latest)
    return days[k - 1] if len(days) >= k else None


def _day(value):
    if isinstance(value, datetime):
        return value.astimezone(LOCAL).date().isoformat() if value.tzinfo else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10] if value else None


def scope(consents, org_id):
    """Current contributors, the individually shared subset, all of the organization's rows, and current rows."""
    rows = [c for c in consents if c.get('org_id') == org_id]
    live = [c for c in rows if current(c)]
    return ({c['participant_id'] for c in live}, {c['participant_id'] for c in live if c['sharing'] == 'individual'},
            rows, live)


def _board(board, contributors, k):
    people = [p for p in board.get('people', []) if isinstance(p, dict) and p.get('id') in contributors]
    out = {}
    for device in sorted({p.get('device') for p in people}, key=str):
        group = [p for p in people if p.get('device') == device]
        if len(group) < k:
            out[str(device)] = {'people': count(len(group), k)}
            continue
        rows = {id(p): [d for d in p.get('days', []) if isinstance(d, dict)] for p in group}
        days = [d for p in group for d in rows[id(p)]]
        months = defaultdict(lambda: [0, set()])
        for p in group:
            for d in rows[id(p)]:
                if d.get('d'):
                    months[str(d['d'])[:7]][0] += 1
                    months[str(d['d'])[:7]][1].add(p.get('id'))
        fields = {}
        for key in BOARD_KEYS:
            # A key holding null is not data (the board writes lvl: null for unassessed days); zero is data.
            with_value = [p for p in group if any(d.get(key) is not None for d in rows[id(p)])]
            entry = {'people': count(len(with_value), k)}
            if len(with_value) >= k and days:
                entry['share_of_days'] = round(sum(d.get(key) is not None for d in days) / len(days), 3)
            fields[key] = entry
        out[str(device)] = {
            'people': len(group),
            'median_days_per_person': statistics.median(len(rows[id(p)]) for p in group),
            'person_days_by_month': {m: (n if len(ids) >= k else f'fewer than {k} people')
                                     for m, (n, ids) in sorted(months.items())},
            'fields': fields}
    return out


def summarize(board, catalog, consents, detail_rows, coverage_rows, failure_rows, org_id, k=K_ANONYMITY):
    """Aggregate-only, small-group-suppressed summary for one organization.

    Inputs may hold participant IDs (reader rows); only counts, shares, medians and k-person days leave.
    """
    contributors, individuals, org_rows, live = scope(consents, org_id)
    datasets = defaultdict(lambda: {'with_rows': set(), 'rows': 0, 'latest': [], 'authorization': Counter()})
    for row in catalog:
        if row.get('participant_id') not in contributors:
            continue
        item = datasets[(row.get('provider'), row.get('dataset'))]
        item['authorization'][row.get('authorization_status')] += 1
        if (row.get('measurement_rows') or 0) > 0:
            item['with_rows'].add(row['participant_id'])
            item['rows'] += row['measurement_rows']
            latest = [_day(row.get(c)) for c in ('latest_civil_day', 'latest_point_time', 'latest_interval_end')]
            item['latest'].append(max((d for d in latest if d), default=None))
    datasets_out = {}
    for (provider, dataset), v in sorted(datasets.items(), key=str):
        n = len(v['with_rows'])
        out = {'people_with_rows': count(n, k),
               'authorization': {str(s): count(c, k) for s, c in sorted(v['authorization'].items(), key=str)}}
        if n >= k:
            out['rows'] = v['rows']
            out['latest_day_reached_by_5'] = kth(v['latest'], k, latest=True)
        datasets_out[f'{provider} {dataset}'] = out
    detail = defaultdict(lambda: {'people': set(), 'person_days': 0, 'first': [], 'last': [], 'stages': set(), 'unplaced': 0})
    for row in detail_rows:
        if row.get('participant_id') not in contributors:
            continue
        item = detail[(row.get('provider'), row.get('dataset'))]
        item['unplaced'] += row.get('unplaced_rows') or 0
        if (row.get('person_days') or 0) > 0:
            item['people'].add(row['participant_id'])
            item['person_days'] += row['person_days']
            item['first'].append(_day(row.get('first_day')))
            item['last'].append(_day(row.get('last_day')))
        if (row.get('stage_rows') or 0) > 0:
            item['stages'].add(row['participant_id'])
    detail_out = {}
    for (provider, dataset), v in sorted(detail.items(), key=str):
        n = len(v['people'])
        out = {'people_with_days': count(n, k), 'rows_without_a_day': 'present' if v['unplaced'] else 'none'}
        if n >= k:
            out.update(person_days=v['person_days'], first_day_reached_by_5=kth(v['first'], k),
                       latest_day_reached_by_5=kth(v['last'], k, latest=True))
        if dataset == 'sleep':
            out['people_with_stage_timeline'] = count(len(v['stages']), k)
        detail_out[f'{provider} {dataset}'] = out
    coverage = defaultdict(lambda: {'connections': 0, 'covered': 0, 'first': []})
    for row in coverage_rows:
        if row.get('participant_id') not in contributors:
            continue
        item = coverage[(row.get('provider'), row.get('dataset'))]
        item['connections'] += 1
        if row.get('covered'):
            item['covered'] += 1
            item['first'].append(_day(row.get('first_requested')))
    coverage_out = {}
    for (provider, dataset), v in sorted(coverage.items(), key=str):
        out = {'connections': count(v['connections'], k), 'with_coverage': count(v['covered'], k)}
        if v['covered'] >= k:
            out['first_requested_reached_by_5'] = kth(v['first'], k)
        coverage_out[f'{provider} {dataset}'] = out
    failures = defaultdict(lambda: {'people': set(), 'failures': 0})
    for row in failure_rows:
        if row.get('participant_id') not in contributors:
            continue
        item = failures[(row.get('provider'), row.get('dataset') or '(run level)', row.get('outcome') or 'failed')]
        item['people'].add(row['participant_id'])
        item['failures'] += row.get('failures') or 0
    failures_out = {}
    for (provider, dataset, outcome), v in sorted(failures.items(), key=str):
        n = len(v['people'])
        failures_out[f'{provider} {dataset} {outcome}'] = ({'people': n, 'failures': v['failures']} if n >= k
                                                          else {'people': count(n, k)})
    return {
        'scope': {'organization': org_id, 'population': 'current contributors (individual or group-only consent)',
                  'contributors': count(len(contributors), k), 'minimum_group': k, 'share_with': DESTINATION},
        'board': {'built_at': board.get('built_at'), 'data_through': board.get('data_through'),
                  'assessment_version': board.get('assessment_version'), 'board_version': board.get('board_version'),
                  'by_device': _board(board, contributors, k)},
        'datasets': datasets_out,
        'detail': detail_out,
        'coverage': coverage_out,
        'failures_last_30_days': failures_out,
        'consent': {'current': count(len(live), k), 'individual': count(len(individuals), k),
                    'group_only': count(len(contributors - individuals), k),
                    'demonstration': count(sum(c.get('demonstration') is True for c in live), k),
                    'not_current': count(len(org_rows) - len(live), k)},
    }


def load_operator_settings(path, folder):
    """Viewer-only operator settings; the hosted app's sign-in section is refused."""
    from sentra.errors import SentraError
    from sentra.viewer_config import viewer_settings
    secrets = tomllib.loads(Path(path).read_text(encoding='utf-8'))
    if set(secrets) != {'viewer'}:
        raise SentraError('Use an operator file with only a [viewer] section; hosted app configuration is not accepted.')
    credentials, limits, _ = viewer_settings(secrets, folder)
    if 'november_hosted_proof' in credentials:
        raise SentraError('Hosted-viewer allowance credentials are not accepted by this check.')
    return credentials, limits


def budgeted(reader, maximum):
    """Wrap the reader's reservation so the run stops before reserving more than `maximum` bytes."""
    from sentra.shared import CapacityStop
    spent, original = [0], reader.reserve

    def reserve(amount):
        if spent[0] + amount > maximum:
            raise CapacityStop(f'Stopped before exceeding --max-transfer-bytes {maximum}; {spent[0]} bytes reserved so far.')
        original(amount)
        spent[0] += amount
    reader.reserve = reserve
    return spent


def read(reader, org_id):
    """Scoped reads: consent first, then only the organization's current contributors."""
    from sentra.errors import SentraError
    _, consents = reader.organization_rows()
    contributors = sorted(scope(consents, org_id)[0])
    if len(contributors) < K_ANONYMITY:
        raise SentraError(f'Fewer than {K_ANONYMITY} current contributors in this organization; nothing shareable to report.')
    allowed = set(contributors)
    reader.can_count = lambda participant: participant in allowed
    board = reader.group_board()
    source = reader._measurement_source()
    bound = len(contributors) * 64
    catalog = reader._rows(f'''select s.participant_id,s.provider,s.dataset,s.authorization_status,
        count(m.metric) measurement_rows,max(m.measured_at) latest_point_time,max(m.interval_end) latest_interval_end,
        max(({CIVIL})) latest_civil_day
        from audit.connection_state s left join {source} m using(participant_id,provider,dataset)
        where s.participant_id=any(%s) group by 1,2,3,4 order by 1,2,3 limit %s''',
        (contributors, bound + 1), allowance=bound * 512 + 16_384)
    detail = reader._rows(detail_sql(source), (list(DETAIL_DATASETS), contributors, bound + 1),
                          allowance=bound * 256 + 16_384)
    coverage = reader._rows('''select s.provider,s.dataset,s.participant_id,
        jsonb_typeof(s.covered_intervals)='array' and jsonb_array_length(s.covered_intervals)>0 covered,
        (select min(x->>'requested_civil_start') from jsonb_array_elements(
           case when jsonb_typeof(s.covered_intervals)='array' then s.covered_intervals else '[]'::jsonb end) x) first_requested
        from audit.connection_state s where s.participant_id=any(%s) order by 1,2,3 limit %s''',
        (contributors, bound + 1), allowance=bound * 256 + 16_384)
    failures = reader._rows('''select r.provider,f->>'dataset' dataset,f->>'outcome' outcome,r.participant_id,
        count(*) failures from audit.collection_runs r cross join lateral jsonb_array_elements(
          case when jsonb_typeof(r.details->'failures')='array' then r.details->'failures' else '[]'::jsonb end) f
        where r.started_at > now()-interval '30 days' and r.participant_id=any(%s)
        group by 1,2,3,4 order by 1,2,3,4 limit %s''',
        (contributors, bound + 1), allowance=bound * 256 + 16_384)
    if max(len(catalog), len(detail), len(coverage), len(failures)) > bound:
        raise SentraError('Live check result exceeded its row bound; nothing reported.')
    return board, catalog, consents, detail, coverage, failures


def main(argv=None):
    from sentra.viewer_reader import ViewerReader
    parser = argparse.ArgumentParser(description='Counts-only reviewer data check for one organization (read-only viewer role)')
    parser.add_argument('--org', required=True, help='organization ID whose current contributors are in scope')
    parser.add_argument('--secrets', type=Path, default=Path('.private/reviewer-live-check.toml'),
                        help='operator file holding only the [viewer] section')
    parser.add_argument('--max-transfer-bytes', type=int, default=8_000_000)
    args = parser.parse_args(argv)
    if not ORG_ID.fullmatch(args.org):
        parser.error('--org must be an organization ID')
    with tempfile.TemporaryDirectory() as folder:
        credentials, limits = load_operator_settings(args.secrets, folder)
        # Nobody is individually visible; group use is limited to the organization once consent is read.
        reader = ViewerReader(credentials, limits, lambda: None, can_view=lambda p: False, can_count=lambda p: False)
        spent = budgeted(reader, args.max_transfer_bytes)
        try:
            rows = read(reader, args.org)
        finally:
            reader.close()
    summary = summarize(*rows, args.org)
    summary['transfer_reserved_bytes'] = spent[0]
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
