"""Selected-period reports for authorized colleagues (#42); pure, no I/O.

A report only reuses the calculators behind the viewer pages, so it follows the same rules:
- participation counts as on the overview (#39); organization users see small activity counts as '<k';
- group summary and group trends per device, each statistic needing at least `cohort_k_anonymity`
  contributors of its own (#39, #40); for organization users the period ends on the latest publishable
  day, so a suppressed reading never moves it, and devices that never reach k are left out;
- individual sections only for people this user may see individually and chose to include: their trend
  against their own baseline (#40) and the explained observations for their latest day (#41);
- follow-ups as counts by status only (#31). Note text never enters a report.

Inputs are re-checked here against the access decision, so a caller passing too much cannot widen a
report. Missing values stay missing. Wellness wording only; nothing here is a medical conclusion.
"""
from .access import K_ANONYMITY
from .follow_ups import STATUSES
from .observations import observations
from .organization import METRICS, latest_group_day, participation, shown_count, group_summary
from .processing.pipeline import TH
from .trends import PERIODS, group_trend, personal_trend, publishable_end

LIMITATIONS = (
    "Wellness information compared with each person's own pattern; not a medical assessment or diagnosis.",
    f"Rules are provisional ({TH['_status']}).",
    'Days without a reading are gaps; nothing is filled in or estimated.',
    f'Each group statistic needs at least {K_ANONYMITY} eligible contributors of its own; smaller groups are '
    'not shown. Fitbit and WHOOP measure differently and are never combined.',
    'This report reflects the permissions in force when it was generated. Later sharing changes or '
    'withdrawals apply to new reports only; a copy already shared cannot be recalled.',
    'Share it only with authorized colleagues of the organization named in the consent. Recipients delete '
    'downloaded copies within 30 days (retention policy).',
)
TEAM_LABEL = 'All organizations (team operator)'


def _available(series):
    return [r['value'] for r in series if r['status'] == 'available']


def _group_trends(people, scope, *, end, days, team):
    result = []
    for key, label, unit, _ in METRICS:
        trend = group_trend(people, scope, key, end=end, days=days) if end else {'devices': {}}
        for device, series in trend['devices'].items():
            values = _available(series)
            if not team and not values:
                continue  # a device below k on every day would reveal a small group's wear pattern
            row = {'key': key, 'label': label, 'unit': unit, 'device': device, 'days': len(series),
                   'days_shown': len(values), 'low': min(values, default=None), 'high': max(values, default=None),
                   'most_contributors': max((r['contributors'] for r in series if r['status'] == 'available'),
                                            default=None)}
            if team:
                row['days_hidden'] = sum(r['status'] == 'suppressed' for r in series)
            result.append(row)
    return result


def _individual(person, *, days, today, assessment_version):
    end = latest_group_day([person])
    measures = []
    if end:
        for key, *_ in METRICS:
            measures.append({'key': key, **personal_trend(person, key, end=end, days=days,
                                                          assessment_version=assessment_version)['summary']})
    return {'id': person['id'], 'device': person.get('device'), 'end': end, 'measures': measures,
            'observations': observations(person, today=today, assessment_version=assessment_version)}


def build(decision, *, board, group_people, scope, enrolled, catalog, include, days, today, generated_at,
          follow_ups=()):
    """The report for `decision` over the last `days` published days.

    `group_people`, `scope`, `enrolled` and `catalog` are the overview's group inputs (`organization_data`);
    `board` is the individually scoped board; `include` the participant IDs the user chose for individual
    sections; `follow_ups` the items the user may read (`follow_ups.visible`)."""
    if days not in PERIODS:
        raise ValueError(f'Period must be one of {PERIODS} days.')
    team = decision.is_team
    group_people = [p for p in group_people if isinstance(p, dict) and decision.group_contributors([p.get('id')])]
    scope = decision.group_contributors(scope)
    version = board.get('assessment_version')
    counts = participation(scope, catalog, group_people, today=today, assessment_version=version)
    counts['enrolled'] = len(enrolled & scope) if not team else len(enrolled)
    shown = {k: (str(v) if team or k == 'enrolled' else shown_count(v))
             for k, v in counts.items() if k != 'recent_days'}
    end = latest_group_day(group_people) if team else publishable_end(group_people, scope)
    people = [p for p in board.get('people', ()) if isinstance(p, dict) and p.get('id') in include
              and decision.can_view_individual(p.get('id'))]
    items = [i for i in follow_ups if team or (i.get('org_id') == decision.org_id and (
        i.get('participant_id') is None or decision.can_view_individual(i['participant_id'])))]
    return {
        'organization': TEAM_LABEL if team else decision.org_id, 'role': decision.role,
        'generated_at': generated_at, 'days': days, 'today': today,
        # The board's own date covers every organization; organization users get only their scoped dates.
        'data_through': board.get('data_through') if team else None, 'board_built_at': board.get('built_at'),
        'participation': shown, 'recent_days': counts['recent_days'],
        'group_end': end, 'group_summary': group_summary(group_people, scope, end=end, days=days) if end else [],
        'group_trends': _group_trends(group_people, scope, end=end, days=days, team=team),
        'individuals': [_individual(p, days=days, today=today, assessment_version=version)
                        for p in sorted(people, key=lambda p: p['id'])],
        'follow_ups': {s: sum(i.get('status') == s for i in items) for s in STATUSES},
        'limitations': list(LIMITATIONS),
    }


def _value(value, unit, sign=False):
    return '—' if value is None else (f'{value:+g} {unit}' if sign else f'{value:g} {unit}')


def _cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def _table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |', '|' + ' --- |' * len(header)]
    lines += ['| ' + ' | '.join(_cell(c) for c in row) + ' |' for row in rows]
    return lines


def markdown(report):
    """The report as Markdown text, for preview and download."""
    k = K_ANONYMITY
    out = ['# Sentra wellness report', '',
           f"- Organization: {report['organization']}",
           f"- Prepared by role: {report['role']}",
           f"- Period: last {report['days']} published days",
           f"- Generated: {report['generated_at']}"]
    if report['data_through']:
        out.append(f"- Published data through: {report['data_through']}")
    if report['board_built_at']:
        out.append(f"- Daily board built: {report['board_built_at']}")
    out += ['', "Wellness information compared with each person's own pattern; not a medical assessment or diagnosis.",
           '', '## Participation', '']
    p = report['participation']
    out += _table(('Enrolled', 'Connected', f"Recently contributing ({report['recent_days']} days)", 'Assessable'),
                  [(p['enrolled'], p['connected'], p['recently_contributing'], p['assessable'])])
    out += ['', 'Each state is counted separately; being connected does not mean recent data arrived.', '',
            '## Group summary', '']
    if not report['group_end']:
        out.append(f'No group statistic can be shown: no day has {k} or more eligible contributors.')
    else:
        out.append(f"Median of each person's period median, days through {report['group_end'].isoformat()}.")
        out.append('')
        out += _table(('Measure', 'Device', 'Group median', 'Contributors', 'Note'),
                      [(r['label'], r['device'] or '', _value(r['value'], r['unit']) if r['status'] == 'available'
                        else 'Not shown', shown_count(r['contributors']), r['reason'] or '')
                       for r in report['group_summary']])
    out += ['', '## Group trends', '']
    if report['group_trends']:
        team = 'days_hidden' in report['group_trends'][0]
        header = ['Measure', 'Device', 'Days shown', 'Lowest daily median', 'Highest daily median',
                  'Most contributors on a day'] + (['Days hidden'] if team else [])
        out += _table(header, [[r['label'], r['device'], f"{r['days_shown']} of {r['days']}",
                                _value(r['low'], r['unit']), _value(r['high'], r['unit']),
                                r['most_contributors'] if r['most_contributors'] is not None else f'<{k}']
                               + ([r['days_hidden']] if team else []) for r in report['group_trends']])
        out += ['', f'A day is shown only with at least {k} contributors; devices that never reach that are left out.']
    else:
        out.append(f'No day in this period has {k} or more eligible contributors, so no group trend is shown.')
    out += ['', '## Individuals', '']
    if not report['individuals']:
        out.append('No individual section: nobody was selected, or nobody selected shares individual details.')
    for person in report['individuals']:
        out += [f"### {person['id']}", '',
                f"Device: {person['device'] or 'not supplied'} · Latest published day: "
                + (person['end'].isoformat() if person['end'] else 'none'), '']
        if person['measures']:
            out += _table(('Measure', 'Days with data', 'Period median', 'Usual (own baseline)', 'Typical difference',
                           'Rule checked / met'),
                          [(m['label'], f"{m['days_with_data']} of {m['days']}", _value(m['median'], m['unit']),
                            _value(m['median_baseline'], m['unit']), _value(m['median_difference'], m['unit'], True),
                            '—' if m['assessed_days'] is None else f"{m['assessed_days']} / {m['signal_days']}")
                           for m in person['measures']])
            out += ['', 'Unchecked days are not counted as calm.', '']
        out.append('Observations for the latest published day:')
        out.append('')
        for item in person['observations']:
            out.append(f"- **{item['title']}** ({item['kind']}): {item['detail']}")
            out += [f'  - {label}: {value}' for label, value in item['readings']]
            out += [f'  - {note}' for note in item['limitations']]
        out.append('')
    f = report['follow_ups']
    out += ['## Follow-ups', '']
    out += _table(('Open', 'Ongoing', 'Resolved'), [(f['open'], f['ongoing'], f['resolved'])])
    out += ['', 'Counts of follow-ups you may read; note text is not included in reports.', '',
            '## Limitations', '']
    out += [f'- {line}' for line in report['limitations']]
    return '\n'.join(out) + '\n'
