"""Organization overview and individual profile summaries (#39); pure, no I/O.

Inputs are rows the viewer already reads: published wellness-board people (pseudonymous daily rows,
missing values omitted), the dataset catalog and the participants in scope from `sentra.access`.
Callers pass only participants the signed-in user may count (group statistics) or see (profiles).

- Group statistics: one value per contributing person for the period (their median), then the group
  median, separately per device (Fitbit and WHOOP readings are not comparable; docs/medical-evidence.md).
  Each statistic is published only with at least `cohort_k_anonymity` contributors of its own;
  otherwise it is suppressed and its exact count is not reported. Missing values are never filled.
- Participation counts states separately; one state does not imply the next.
- Assessment availability consumes the versioned board contract (#45): only a recent complete
  day counts as assessable. Profiles show values and baselines.
"""
from datetime import date, timedelta
from statistics import median

from .access import K_ANONYMITY, SHARING, publishable
from .processing.board import DEVICES
from .processing.pipeline import ASSESSMENT_VERSION
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
KNOWN_DEVICES = frozenset(DEVICES.values())  # board device labels with a known measurement meaning
RECENT_DAYS = 3  # proposed "recently contributing" window; latest measurement day within 3 days


# Shared board parsing rules for every board consumer (overview, observations, trends).
def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def board_day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def valid_days(person):
    """Day rows with a valid ISO date; one malformed row must not hide the valid ones."""
    return [d for d in person.get('days', ()) if isinstance(d, dict) and board_day(d.get('d'))]


def latest_group_day(people):
    """Latest valid published day among the already authorized group contributors."""
    return max((board_day(d['d']) for person in people for d in valid_days(person)), default=None)


def shown_count(count, k=K_ANONYMITY):
    """A contributor count safe to display: exact from k upwards, otherwise only '<k'."""
    return str(count) if count == 0 or publishable(count, k) else f'<{k}'


def team_scope(participants, consents):
    """Team view: (enrolled, included). Enrolled have current consent; included adds pilot participants
    with data but no consent record. Anyone whose recorded consent is withdrawn or closed is excluded."""
    enrolled = {c['participant_id'] for c in consents if isinstance(c.get('participant_id'), str)
                and c.get('withdrawn') is False and c.get('membership_open') is True and c.get('sharing') in SHARING}
    recorded = {c.get('participant_id') for c in consents}
    return enrolled, enrolled | {p for p in participants if isinstance(p, str) and p not in recorded}


def _window(end, days):
    return {(end - timedelta(days=offset)).isoformat() for offset in range(max(days, 1))}


def group_summary(people, contributors, *, end, days=1, k=K_ANONYMITY):
    """Per-metric, per-device group medians for the `days` ending on `end`, each suppressed below k."""
    window = _window(end, days)
    scoped = [p for p in people if isinstance(p, dict) and p.get('id') in contributors]
    result = []
    for key, label, unit, decimals in METRICS:
        by_device = {}
        for person in scoped:
            values = [d[key] for d in valid_days(person) if d['d'] in window and is_number(d.get(key))]
            if values:
                device = person.get('device')
                if device in KNOWN_DEVICES:  # unknown devices may differ from each other; never pooled
                    by_device.setdefault(device, []).append(median(values))
        for device in sorted(by_device) or [None]:
            per_person = by_device.get(device, [])
            count = len(per_person)
            row = {'key': key, 'label': label, 'unit': unit, 'device': device, 'contributors': count, 'value': None}
            if count == 0:
                row.update(status='no_data', reason='No eligible contributor has this measurement in the period.')
            elif not publishable(count, k):
                row.update(status='suppressed', reason=f'Fewer than {k} eligible contributors; not shown.')
            else:
                row.update(status='available', reason=None, value=round(median(per_person), decimals))
            result.append(row)
    return result


def participation(scope, catalog, people, *, today, recent_days=RECENT_DAYS, assessment_version=None):
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
    assessable = set()
    # Legacy boards can contain misleading green days. Require the current producer contract,
    # then consume its completeness state rather than deriving assessment from baselines.
    if assessment_version == ASSESSMENT_VERSION:
        for person in people:
            if not isinstance(person, dict) or person.get('id') not in scope:
                continue
            latest = max(valid_days(person), key=lambda d: d['d'], default=None)
            if (latest and today - timedelta(days=recent_days) <= board_day(latest['d']) <= today
                    and latest.get('a') is None and latest.get('lvl') in ('green', 'amber', 'red')):
                assessable.add(person['id'])
    return {'enrolled': len(scope), 'connected': len(connected), 'recently_contributing': len(recent),
            'assessable': len(assessable), 'recent_days': recent_days}


def profile(person, *, today):
    """Latest values for one permitted person, compared with their own baseline; missing stays missing."""
    days = valid_days(person)
    latest = days[-1] if days else {}
    through = board_day(latest['d']) if latest else None
    metrics = []
    for key, label, unit, decimals in METRICS:
        value = latest.get(key) if is_number(latest.get(key)) else None
        baseline_key = BASELINES.get(key)
        baseline = latest.get(baseline_key) if baseline_key and is_number(latest.get(baseline_key)) else None
        difference = round(value - baseline, decimals) if value is not None and baseline is not None else None
        if value is None:
            note = 'Not supplied for the latest day.'
        elif baseline_key and baseline is None:
            note = 'Not enough history for a personal baseline yet.'
        else:
            note = None
        metrics.append({'key': key, 'label': label, 'unit': unit, 'value': value, 'baseline': baseline,
                        'difference': difference, 'note': note})
    recent = sum(1 for d in days if today - timedelta(days=6) <= board_day(d['d']) <= today)
    return {'id': person.get('id'), 'device': person.get('device'), 'data_through': through,
            'days_old': (today - through).days if through else None, 'days_with_data_last_7': recent,
            'metrics': metrics}
