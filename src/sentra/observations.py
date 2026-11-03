"""Plain-language observations for one permitted participant (#41); pure, no I/O.

Consumes the published wellness-board day and the shared indicator contract
(docs/indicator-contract.md). Nothing here re-derives a rule: signals come from the board's flags
(`f`), assessment limits from its states (`a`, `m`), and the wording below mirrors the contract's
plain wording. Three kinds are kept apart so they are never confused:

- `wellness`: a rule signalled (or all core rules were checked and none signalled), relative to the
  person's own pattern. Rules are provisional until the medical expert signs them off.
- `assessment`: what could not be checked on that day, and why.
- `collection`: data problems (no published days, stale data, a board built under older rules).

None of these is a medical conclusion or diagnosis.
"""

from .organization import RECENT_DAYS, _day, _days, _number
from .processing.pipeline import ASSESSMENT_VERSION, CORE_RULES, TH

RULE_LABELS = {'sleep': 'Sleep', 'rhr': 'Resting heart rate', 'sleep_hr': 'Sleeping heart rate',
               'hrv': 'Heart-rate variability'}
# board flag -> (rule, contract wording, value key, baseline key, z key, unit)
SIGNALS = {
    'short_sleep': ('sleep', 'Slept less than 6 hours', 'sleep', None, None, 'min'),
    'rhr_up': ('rhr', 'Resting heart rate above your normal', 'rhr', 'rhr_b', 'rhr_z', 'bpm'),
    'sleep_hr_up': ('sleep_hr', 'Sleeping heart rate above your normal', 'sleep_hr', 'sleep_hr_b', None, 'bpm'),
    'hrv_down': ('hrv', 'Heart-rate variability below your normal', 'hrv', 'hrv_b', 'hrv_z', 'ms'),
}
REASONS = {'no_reading': 'no reading for this day',
           'baseline_building': f"personal normal still building (needs {TH['baseline_min_days']} of the previous "
                                f"{TH['baseline_days']} days)"}
PROVISIONAL = f"Provisional rule ({TH['_status']})."
NOT_MEDICAL = 'A wellness observation relative to this person\'s own pattern, not a medical conclusion.'


def _fmt(value, unit):
    return f'{value:g} {unit}'


def _readings(day, value_key, baseline_key, z_key, unit):
    readings = []
    if _number(day.get(value_key)):
        readings.append(('This day', _fmt(day[value_key], unit)))
    if baseline_key and _number(day.get(baseline_key)):
        readings.append(('Usual (own baseline)', _fmt(day[baseline_key], unit)))
    if z_key and _number(day.get(z_key)):
        readings.append(('Difference from usual variation', f'{day[z_key]:+g} × usual variation'))
    if value_key == 'sleep':
        readings.append(('Rule', f"less than {TH['short_sleep_minutes']} min asleep"))
    return readings


def _reasons(day):
    out = []
    for item in day.get('m') or ():
        rule, _, state = str(item).partition(':')
        out.append(f'{RULE_LABELS.get(rule, rule)}: {REASONS.get(state, state or "not assessed")}')
    return out


def observations(person, *, today, assessment_version, recent_days=RECENT_DAYS):
    """Observations for the person's latest published day, most important kind first."""
    days = _days(person)
    if not days:
        return [{'kind': 'collection', 'day': None, 'title': 'No published days yet',
                 'detail': 'Nothing can be observed until processed days are published.', 'readings': [],
                 'limitations': []}]
    day = days[-1]
    through = _day(day['d'])
    result = []
    if (today - through).days > recent_days:
        result.append({'kind': 'collection', 'day': through, 'title': 'No recent data',
                       'detail': f'The latest published day is {(today - through).days} days old, so this is not '
                                 'a current picture. Check the wearable connection and syncing.',
                       'readings': [], 'limitations': []})
    if assessment_version != ASSESSMENT_VERSION:
        # Levels from older rules can look falsely complete; show nothing until the next refresh.
        result.append({'kind': 'collection', 'day': through, 'title': 'Published under older rules',
                       'detail': 'Observations appear after the next daily refresh rebuilds the board.',
                       'readings': [], 'limitations': []})
        return result
    reasons = _reasons(day)
    limitations = [PROVISIONAL, NOT_MEDICAL] + ([f'Not checked: {"; ".join(reasons)}.'] if reasons else [])
    for flag in day.get('f') or ():
        if flag not in SIGNALS:
            continue
        rule, wording, value_key, baseline_key, z_key, unit = SIGNALS[flag]
        result.append({'kind': 'wellness', 'day': through, 'title': wording,
                       'detail': f'{RULE_LABELS[rule]} met its rule on this day.',
                       'readings': _readings(day, value_key, baseline_key, z_key, unit),
                       'limitations': limitations})
    if day.get('lvl') in ('amber', 'red') and not any(r['kind'] == 'wellness' for r in result):
        # Never leave a level unexplained; this means the board and this page disagree on rule codes.
        result.append({'kind': 'collection', 'day': through, 'title': 'Level without a recognised rule',
                       'detail': 'Processing reported a change this page cannot explain. Ask the team to check '
                                 'the published board.', 'readings': [], 'limitations': []})
    if day.get('a') in ('partial', 'insufficient'):
        title = 'Partial assessment' if day['a'] == 'partial' else 'Not enough information'
        result.append({'kind': 'assessment', 'day': through, 'title': title,
                       'detail': 'Some rules could not be checked, so a calm result cannot be concluded.'
                                 if day['a'] == 'partial' else 'No rule could be checked on this day.',
                       'readings': [], 'limitations': reasons or ['Reason not supplied by processing.']})
    elif day.get('lvl') == 'green' and not day.get('f'):
        checked = ', '.join(RULE_LABELS[r].lower() for r in CORE_RULES)
        result.append({'kind': 'wellness', 'day': through, 'title': 'No change from usual pattern',
                       'detail': f'All core rules ({checked}) were checked and none signalled.',
                       'readings': [], 'limitations': [PROVISIONAL, NOT_MEDICAL]})
    return result
