"""Check every reviewer field-map reference against Sentra's own contracts.

`field_map.json` lists each field the reviewer prototype shows with machine-checkable references:
provider datasets, vendor field paths, canonical metrics, board keys, rules and SQL columns. A
renamed dataset, path, key or rule makes `failures()` non-empty, so the prototype cannot drift
from the code it will be wired to (docs/reviewer-data-connections.md).
"""
from datetime import date
import json
from pathlib import Path

from ..datasets import ON_REQUEST, plan_jobs
from ..processing.board import FIELDS, FLAGS
from ..processing.canonical import METRICS
from ..processing.metric_map import GOOGLE_STAGE_CODES, MAPPING, UNMAPPED, WHOOP_ASLEEP_PARTS
from ..processing.pipeline import TH

# Repository root for sql/ and source checks; tests pass it explicitly when the package is installed.
ROOT = Path(__file__).resolve().parents[3]
FIELD_MAP = Path(__file__).with_name('field_map.json')
STATUSES = {'in_sentra', 'stored', 'derive', 'not_provided', 'no_source'}
# Values the prototype hard-codes; they must equal the processing thresholds.
PROTOTYPE_THRESHOLDS = {'short_sleep_minutes': 360, 'z_alert': 2.0, 'baseline_days': 28,
                        'baseline_min_days': 7, 'cohort_k_anonymity': 5}


def _datasets():
    found = {p: {j.dataset for j in plan_jobs(p, date(2026, 10, 1), date(2026, 10, 31))}
             for p in ('google_health', 'whoop')}
    found['google_health'] |= {j.dataset for j in plan_jobs('google_health', date(2026, 10, 1),
                                                             date(2026, 10, 2), on_request=ON_REQUEST)}
    return found


def check(rule, datasets, root=ROOT):
    """(ok, description) for one field-map reference."""
    kind, *args = rule
    if kind == 'mapping':
        provider, dataset, path, canonical = args
        target = MAPPING.get((provider, dataset, path))
        return target is not None and target[0] == canonical, f'MAPPING{(provider, dataset, path)} -> {target}'
    if kind == 'board':
        return args[0] in set(FIELDS) | {'d', 'lvl', 'f', 'a', 'm'}, f'board key {args[0]!r}'
    if kind == 'dataset':
        return args[1] in datasets[args[0]], f'{args[0]} dataset {args[1]!r} in plan_jobs'
    if kind == 'unmapped':
        return (args[0], args[1]) in UNMAPPED, f'UNMAPPED{tuple(args)}'
    if kind == 'whoop_part':
        return args[0] in WHOOP_ASLEEP_PARTS, f'WHOOP_ASLEEP_PARTS has {args[0]}'
    if kind == 'stage_codes':
        return all(code in GOOGLE_STAGE_CODES for code in args), f'GOOGLE_STAGE_CODES has {args}'
    if kind == 'canonical':
        return args[0] in METRICS, f'canonical metric {args[0]!r}'
    if kind == 'on_request':
        return args[0] in ON_REQUEST, f'ON_REQUEST has {args[0]!r}'
    if kind == 'flags':
        return set(args) == set(FLAGS.values()), f'board flags {sorted(FLAGS.values())}'
    if kind == 'k':
        return TH['cohort_k_anonymity'] == args[0], f'cohort_k_anonymity == {args[0]}'
    if kind == 'sql':
        table, column = args
        text = '\n'.join(p.read_text(encoding='utf-8') for p in sorted((root / 'sql').glob('*.sql')))
        return f'create table {table}' in text and column in text, f'{table}.{column} in sql/'
    if kind == 'source_text':
        path, needle = args
        return needle in (root / path).read_text(encoding='utf-8'), f'{path} contains {needle!r}'
    return False, f'unknown check {kind}'


def load(path=FIELD_MAP):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def failures(fields=None, root=ROOT):
    """Every reference or threshold that no longer matches the repository rooted at `root`."""
    root = Path(root)
    fields = load(root / 'src' / 'sentra' / 'reviewer' / 'field_map.json') if fields is None else fields
    datasets, out = _datasets(), []
    for field in fields:
        if field.get('status') not in STATUSES:
            out.append(f'{field.get("id")}: unknown status {field.get("status")!r}')
        for rule in field['checks']:
            ok, what = check(rule, datasets, root)
            if not ok:
                out.append(f'{field["id"]}: {what}')
    for key, value in PROTOTYPE_THRESHOLDS.items():
        if TH[key] != value:
            out.append(f'threshold {key}: repository {TH[key]} != prototype {value}')
    return out
