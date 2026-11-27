"""Check every reviewer field-map reference against Sentra's own contracts.

`field_map.json` lists each field the reviewer prototype shows with machine-checkable references:
provider datasets, vendor field paths, canonical metrics, board keys, rules and SQL columns. A
renamed dataset, path, key or rule makes `failures()` non-empty, so the prototype cannot drift
from the code it will be wired to (docs/reviewer-data-connections.md).
"""
from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re

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


NAME = r'[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?'
CONSTRAINTS = {'constraint', 'primary', 'foreign', 'unique', 'check', 'exclude', 'like'}


def _split(text):
    """Split at top-level commas; strings and dollar-quoted bodies are blanked beforehand."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(text):
        depth += (c == '(') - (c == ')')
        if c == ',' and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    return [p.strip() for p in parts + [text[start:]] if p.strip()]


def _parens(text, start):
    """Body of the parenthesised group opening at text[start]."""
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == '(') - (text[i] == ')')
        if depth == 0:
            return text[start + 1:i]
    raise ValueError('unbalanced parentheses in sql/')


def _view_columns(select):
    """Output column names of a view's top-level select list."""
    body = re.sub(r'^select\s+(?:distinct\s+on\s*\([^)]*\)\s*|distinct\s+)?', '', select.strip())
    depth, end = 0, len(body)
    for m in re.finditer(r'[()]|\bfrom\b', body):
        if m.group() == '(':
            depth += 1
        elif m.group() == ')':
            depth -= 1
        elif depth == 0:
            end = m.start()
            break
    names = set()
    for item in _split(body[:end]):
        alias = re.search(r'\bas\s+([a-z_][a-z0-9_]*)$', item)
        names.add(alias.group(1) if alias else re.split(r'[.\s]', item)[-1])
    return names


def _apply_alter(tables, name, actions):
    columns = tables.get(name)
    if columns is None:
        return
    for action in _split(actions):
        if a := re.fullmatch(rf'rename to ({NAME})', action):
            new = a.group(1) if '.' in a.group(1) else name.rsplit('.', 1)[0] + '.' + a.group(1)
            tables[new] = tables.pop(name)
            name, columns = new, tables[new]
        elif a := re.match(r'rename (?:column )?(?!constraint\b|to\b)([a-z_][a-z0-9_]*) to ([a-z_][a-z0-9_]*)$', action):
            columns.discard(a.group(1))
            columns.add(a.group(2))
        elif a := re.match(r'add (?:column )?(?:if not exists )?(?!(?:constraint|primary|unique|foreign|check|exclude)\b)'
                           r'([a-z_][a-z0-9_]*) ', action):
            columns.add(a.group(1))
        elif a := re.match(r'drop (?:column )?(?:if exists )?(?!constraint\b)([a-z_][a-z0-9_]*)', action):
            columns.discard(a.group(1))


TOKENS = re.compile(r"--[^\n]*|/\*.*?\*/|'(?:[^']|'')*'|(\$[a-z_]*\$).*?\1|[^'$/-]+|.", re.S)


def _code(text):
    """SQL text with comments removed and string literals and dollar-quoted bodies blanked, in one pass."""
    out = []
    for m in TOKENS.finditer(text):
        token = m.group()
        if token.startswith('--') or token.startswith('/*') or m.group(1):
            out.append(' ')
        elif token.startswith("'"):
            out.append("''")
        else:
            out.append(token)
    return ''.join(out)


@lru_cache(maxsize=8)
def _schema(sql_dir, stamp):
    text = _code('\n'.join(p.read_text(encoding='utf-8') for p in sorted(Path(sql_dir).glob('*.sql'))).lower())
    tables = {}
    for statement in text.split(';'):
        st = ' '.join(statement.split())
        if m := re.match(rf'create (?:unlogged )?table (?:if not exists )?({NAME}) ?\(', st):
            first = (re.match(r'"?([a-z_][a-z0-9_]*)', item) for item in _split(_parens(st, m.end() - 1)))
            tables[m.group(1)] = {f.group(1) for f in first if f and f.group(1) not in CONSTRAINTS}
        elif m := re.match(rf'create (?:or replace )?view ({NAME})(?: with ?\([^)]*\))? as (select .*)', st):
            tables[m.group(1)] = _view_columns(m.group(2))
        elif m := re.match(rf'alter table (?:if exists )?(?:only )?({NAME}) (.*)', st):
            _apply_alter(tables, m.group(1), m.group(2))
        elif m := re.match(r'drop (?:table|view) (?:if exists )?(.*)', st):
            for name in re.findall(NAME, re.sub(r' (?:cascade|restrict)$', '', m.group(1))):
                tables.pop(name, None)
    return {name: frozenset(columns) for name, columns in tables.items()}


def schema(root=ROOT):
    """{schema.table or view: columns} after applying every migration in sql/ in order, including ALTERs."""
    sql_dir = Path(root) / 'sql'
    stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(sql_dir.glob('*.sql')))
    return _schema(str(sql_dir), stamp)


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
        return column in schema(root).get(table, ()), f'{table}.{column} in the schema built from sql/'
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
