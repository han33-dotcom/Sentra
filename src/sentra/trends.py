"""Trends over selectable periods: one person against their own baseline, or a permitted group (#40).

Pure, no I/O. Inputs are published wellness-board people already limited by `sentra.access`:
individually permitted people for personal trends, group contributors for group trends.

- Every day of the period is returned; a day without a reading stays a gap (value None), never
  filled or interpolated.
- The personal comparison is the contract's baseline (docs/indicator-contract.md): the median of
  the previous 28 days, needing 7 days with a reading. It is published on the board; nothing here
  recomputes it. Signal days are the board's own flags for that measure.
- Group trends: one value per contributing person per day, then the median, separately per device.
  Each day's statistic needs at least `cohort_k_anonymity` contributors of its own; otherwise it is
  suppressed and its exact count is not reported.
"""
from datetime import timedelta
from statistics import median

from .access import K_ANONYMITY, publishable
from .organization import BASELINES, METRICS, _days, _number

PERIODS = (7, 14, 28)  # days ending on the latest published day
SIGNAL_FLAGS = {'sleep': 'short_sleep', 'rhr': 'rhr_up', 'hrv': 'hrv_down'}


def period_days(end, days):
    """The `days` ISO dates ending on `end`, oldest first."""
    return [(end - timedelta(days=offset)).isoformat() for offset in reversed(range(max(days, 1)))]


def metric(key):
    return next(m for m in METRICS if m[0] == key)


def personal_trend(person, key, *, end, days):
    """Daily values against the person's own baseline for the period, with gaps kept and a summary."""
    _, label, unit, decimals = metric(key)
    by_day = {d['d']: d for d in _days(person)}
    baseline_key = BASELINES.get(key)
    points = []
    for iso in period_days(end, days):
        day = by_day.get(iso, {})
        value = day.get(key) if _number(day.get(key)) else None
        baseline = day.get(baseline_key) if baseline_key and _number(day.get(baseline_key)) else None
        points.append({'d': iso, 'value': value, 'baseline': baseline,
                       'difference': round(value - baseline, decimals) if None not in (value, baseline) else None,
                       'signal': SIGNAL_FLAGS.get(key) in (day.get('f') or ())})
    values = [p['value'] for p in points if p['value'] is not None]
    differences = [p['difference'] for p in points if p['difference'] is not None]
    baselines = [p['baseline'] for p in points if p['baseline'] is not None]
    summary = {'label': label, 'unit': unit, 'days': len(points), 'days_with_data': len(values),
               'median': round(median(values), decimals) if values else None,
               'median_baseline': round(median(baselines), decimals) if baselines else None,
               'median_difference': round(median(differences), decimals) if differences else None,
               'days_compared': len(differences),
               'signal_days': sum(p['signal'] for p in points) if key in SIGNAL_FLAGS else None}
    return {'points': points, 'summary': summary}


def group_trend(people, contributors, key, *, end, days, k=K_ANONYMITY):
    """Per-device daily group medians for the period; each day suppressed below k contributors."""
    _, label, unit, decimals = metric(key)
    dates = period_days(end, days)
    by_device = {}
    for person in people:
        if not isinstance(person, dict) or person.get('id') not in contributors:
            continue
        device = person.get('device') if isinstance(person.get('device'), str) else 'Not supplied'
        series = by_device.setdefault(device, {iso: [] for iso in dates})
        for day in _days(person):
            if day['d'] in series and _number(day.get(key)):
                series[day['d']].append(day[key])
    result = {}
    for device in sorted(by_device):
        rows = []
        for iso in dates:
            values = by_device[device][iso]
            count = len(values)
            if count == 0:
                rows.append({'d': iso, 'value': None, 'contributors': 0, 'status': 'no_data'})
            elif not publishable(count, k):
                rows.append({'d': iso, 'value': None, 'contributors': count, 'status': 'suppressed'})
            else:
                rows.append({'d': iso, 'value': round(median(values), decimals), 'contributors': count,
                             'status': 'available'})
        result[device] = rows
    return {'label': label, 'unit': unit, 'devices': result}
