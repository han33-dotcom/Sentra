"""Organization overview and individual profile summaries (#39); pure, no I/O.

Inputs are rows the viewer already reads: published wellness-board people (pseudonymous daily rows,
missing values omitted), the dataset catalog and the participants in scope from `sentra.access`.
Callers pass only participants the signed-in user may count (group statistics) or see (profiles).

- Group statistics: one value per contributing person for the period (their median), then the group
  median. Each statistic is published only with at least `cohort_k_anonymity` contributors of its
  own; otherwise it is suppressed with the reason. Missing values are never filled.
- Participation counts states separately; one state does not imply the next.
- Assessment levels are not interpreted here: the board's day level is not reliable for missing data
  until the incomplete-assessment contract (#45) lands, so profiles show values and baselines only.
"""
from datetime import date, timedelta
from statistics import median

from .access import K_ANONYMITY, publishable
from .viewer_data import latest_available_day

# board key, label, unit, decimals
METRICS = (
    ('sleep', 'Sleep', 'min', 0),
    ('rhr', 'Resting heart rate', 'bpm', 0),
    ('hrv', 'Heart rate variability', 'ms', 1),
    ('steps', 'Steps', 'steps', 0),
    ('rec', 'WHOOP recovery', '%', 0),
)
BASELINES = {'sleep': 'sleep_b', 'rhr': 'rhr_b', 'hrv': 'hrv_b', 'steps': 'steps_b'}
RECENT_DAYS = 3  # proposed "recently contributing" window; latest measurement day within 3 days


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _window(end, days):
    return {(end - timedelta(days=offset)).isoformat() for offset in range(max(days, 1))}


def group_summary(people, contributors, *, end, days=1, k=K_ANONYMITY):
    """Per-metric group medians for the `days` ending on `end`, each suppressed below k contributors."""
    window = _window(end, days)
    scoped = [p for p in people if isinstance(p, dict) and p.get('id') in contributors]
    result = []
    for key, label, unit, decimals in METRICS:
        per_person = []
        for person in scoped:
            values = [d[key] for d in person.get('days', ()) if d.get('d') in window and _number(d.get(key))]
            if values:
                per_person.append(median(values))
        count = len(per_person)
        row = {'key': key, 'label': label, 'unit': unit, 'contributors': count, 'value': None}
        if count == 0:
            row.update(status='no_data', reason='No eligible contributor has this measurement in the period.')
        elif not publishable(count, k):
            row.update(status='suppressed', reason=f'Fewer than {k} eligible contributors ({count}); not shown.')
        else:
            row.update(status='available', reason=None, value=round(median(per_person), decimals))
        result.append(row)
    return result


def participation(scope, catalog, people, *, today, recent_days=RECENT_DAYS):
    """Counts for the participants in scope: enrolled, connected, recently contributing, assessable."""
    scope = {p for p in scope if isinstance(p, str)}
    rows = [r for r in catalog if r.get('participant_id') in scope]
    connected = {r['participant_id'] for r in rows if r.get('authorization_status') == 'authorized'}
    recent = set()
    for pid in scope:
        latest = max((day for provider in {r['provider'] for r in rows if r['participant_id'] == pid}
                      if (day := latest_available_day(rows, pid, provider))), default=None)
        if latest and today - timedelta(days=recent_days) <= latest <= today:
            recent.add(pid)
    assessable = {p['id'] for p in people if isinstance(p, dict) and p.get('id') in scope and p.get('days')
                  and any(_number(p['days'][-1].get(b)) for b in BASELINES.values())}
    return {'enrolled': len(scope), 'connected': len(connected), 'recently_contributing': len(recent),
            'assessable': len(assessable), 'recent_days': recent_days}


def profile(person, *, today):
    """Latest values for one permitted person, compared with their own baseline; missing stays missing."""
    days = [d for d in person.get('days', ()) if isinstance(d, dict) and isinstance(d.get('d'), str)]
    latest = days[-1] if days else {}
    through = date.fromisoformat(latest['d']) if latest else None
    metrics = []
    for key, label, unit, decimals in METRICS:
        value = latest.get(key) if _number(latest.get(key)) else None
        baseline_key = BASELINES.get(key)
        baseline = latest.get(baseline_key) if baseline_key and _number(latest.get(baseline_key)) else None
        difference = round(value - baseline, decimals) if value is not None and baseline is not None else None
        if value is None:
            note = 'Not supplied for the latest day.'
        elif baseline_key and baseline is None:
            note = 'Not enough history for a personal baseline yet.'
        else:
            note = None
        metrics.append({'key': key, 'label': label, 'unit': unit, 'value': value, 'baseline': baseline,
                        'difference': difference, 'note': note})
    recent = sum(1 for d in days if today - timedelta(days=6) <= date.fromisoformat(d['d']) <= today)
    return {'id': person.get('id'), 'device': person.get('device'), 'data_through': through,
            'days_old': (today - through).days if through else None, 'days_with_data_last_7': recent,
            'metrics': metrics}
