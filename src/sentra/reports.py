"""Selected-period reports for authorized colleagues (#42); pure, no I/O.

A report only reuses the calculators behind the viewer pages, so it follows the same rules:
- participation counts as on the overview (#39); organization users see small activity counts as '<k';
- group summary and group trends per device, each statistic needing at least `cohort_k_anonymity`
  contributors of its own (#39, #40); for organization users the period ends on the latest publishable
  day, and summaries and trends omit device labels for suppressed statistics;
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


def _group_summary(people, scope, *, end, days, team):
    rows = group_summary(people, scope, end=end, days=days)
    if team:
        return rows
    by_measure = {}
    for row in rows:
        by_measure.setdefault(row['key'], []).append(row)
    result = []
    for measure_rows in by_measure.values():
        available = [row for row in measure_rows if row['status'] == 'available']
        result.extend(available or [dict(
            measure_rows[0], device=None, contributors=None, value=None, status='unavailable',
            reason=f'No device has a publishable statistic (minimum {K_ANONYMITY} eligible contributors).',
        )])
    return result


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
          follow_ups=(), demonstration=None):
    """The report for `decision` over the last `days` published days.

    `group_people`, `scope`, `enrolled` and `catalog` are the overview's group inputs (`organization_data`);
    for the team, `scope` excludes withdrawn participants and closed memberships, including when a
    cached board still contains their rows.
    `board` is the individually scoped board; `include` the participant IDs the user chose for individual
    sections; `follow_ups` the items the user may read (`follow_ups.visible`).

    `demonstration`: None for a normal report, or the participants who agreed to internal demonstrations
    for a demonstration copy (`Access.demonstrators`; the team passes `access.demonstration_ids`). A
    demonstration copy uses nobody else, in group figures as well as individual sections."""
    if days not in PERIODS:
        raise ValueError(f'Period must be one of {PERIODS} days.')
    team = decision.is_team
    if demonstration is not None and not team:
        demonstration = set(demonstration) & decision.demonstrators  # never wider than the user's own decision

    scope = decision.group_contributors(scope)
    if demonstration is not None:
        scope &= demonstration
    group_people = [p for p in group_people if isinstance(p, dict) and p.get('id') in scope]
    version = board.get('assessment_version')
    counts = participation(scope, catalog, group_people, today=today, assessment_version=version)
    counts['enrolled'] = len(scope.intersection(enrolled))
    shown = {k: (str(v) if team or k == 'enrolled' else shown_count(v))
             for k, v in counts.items() if k != 'recent_days'}
    end = latest_group_day(group_people) if team else publishable_end(group_people, scope)
    selected = scope.intersection(include)
    people = [p for p in board.get('people', ()) if isinstance(p, dict) and p.get('id') in selected
              and decision.can_view_individual(p.get('id'))]
    items = [i for i in follow_ups if (team or (i.get('org_id') == decision.org_id and (
        i.get('participant_id') is None or decision.can_view_individual(i['participant_id']))))
        and (i.get('participant_id') is None or i['participant_id'] in scope)]
    return {
        'organization': TEAM_LABEL if team else decision.org_id, 'role': decision.role,
        'demonstration': demonstration is not None,
        'generated_at': generated_at, 'days': days, 'today': today,
        # The source board can include dates from withdrawn participants and people who declined demonstrations.
        'data_through': end.isoformat() if team and end else None, 'board_built_at': board.get('built_at'),
        'participation': shown, 'recent_days': counts['recent_days'],
        'group_end': end, 'group_summary': _group_summary(group_people, scope, end=end, days=days, team=team)
        if end else [],
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


def blocks(report):
    """The report's content as a list of blocks, rendered by `markdown` and `pdf`, so both formats always
    carry the same content. Blocks: ('title'|'h2'|'h3', text), ('p', text, bold lead or None),
    ('table', header, rows), ('bullets', [(bold lead or None, text, [sub-items])])."""
    k = K_ANONYMITY
    meta = [f"Organization: {report['organization']}", f"Prepared by role: {report['role']}",
            f"Period: last {report['days']} published days", f"Generated: {report['generated_at']}"]
    if report['data_through']:
        meta.append(f"Published data through: {report['data_through']}")
    if report['board_built_at']:
        meta.append(f"Daily board built: {report['board_built_at']}")
    out = [('title', 'Sentra wellness report'), ('bullets', [(None, line, []) for line in meta])]
    if report['demonstration']:
        out.append(('p', 'Includes only participants who agreed to internal project demonstrations, in group '
                    'figures as well as individual sections. Not for public material.', 'Demonstration copy.'))
    p = report['participation']
    out += [('p', "Wellness information compared with each person's own pattern; not a medical assessment or "
             'diagnosis.', None),
            ('h2', 'Participation'),
            ('table', ('Enrolled', 'Connected', f"Recently contributing ({report['recent_days']} days)", 'Assessable'),
             [(p['enrolled'], p['connected'], p['recently_contributing'], p['assessable'])]),
            ('p', 'Each state is counted separately; being connected does not mean recent data arrived.', None),
            ('h2', 'Group summary')]
    if not report['group_end']:
        out.append(('p', f'No group statistic can be shown: no day has {k} or more eligible contributors.', None))
    else:
        out += [('p', f"Median of each person's period median, days through {report['group_end'].isoformat()}.", None),
                ('table', ('Measure', 'Device', 'Group median', 'Contributors', 'Note'),
                 [(r['label'], r['device'] or '', _value(r['value'], r['unit']) if r['status'] == 'available'
                   else 'Not shown', '—' if r['contributors'] is None else shown_count(r['contributors']),
                   r['reason'] or '')
                  for r in report['group_summary']])]
    out.append(('h2', 'Group trends'))
    if report['group_trends']:
        team = 'days_hidden' in report['group_trends'][0]
        header = ['Measure', 'Device', 'Days shown', 'Lowest daily median', 'Highest daily median',
                  'Most contributors on a day'] + (['Days hidden'] if team else [])
        out += [('table', header, [[r['label'], r['device'], f"{r['days_shown']} of {r['days']}",
                                    _value(r['low'], r['unit']), _value(r['high'], r['unit']),
                                    r['most_contributors'] if r['most_contributors'] is not None else f'<{k}']
                                   + ([r['days_hidden']] if team else []) for r in report['group_trends']]),
                ('p', f'A day is shown only with at least {k} contributors; devices that never reach that are left out.',
                 None)]
    else:
        out.append(('p', f'No day in this period has {k} or more eligible contributors, so no group trend is shown.',
                    None))
    out.append(('h2', 'Individuals'))
    if not report['individuals']:
        out.append(('p', 'No individual section: nobody was selected, or nobody selected shares individual details.',
                    None))
    for person in report['individuals']:
        out += [('h3', person['id']),
                ('p', f"Device: {person['device'] or 'not supplied'} · Latest published day: "
                 + (person['end'].isoformat() if person['end'] else 'none'), None)]
        if person['measures']:
            out += [('table', ('Measure', 'Days with data', 'Period median', 'Usual (own baseline)',
                               'Typical difference', 'Rule checked / met'),
                     [(m['label'], f"{m['days_with_data']} of {m['days']}", _value(m['median'], m['unit']),
                       _value(m['median_baseline'], m['unit']), _value(m['median_difference'], m['unit'], True),
                       '—' if m['assessed_days'] is None else f"{m['assessed_days']} / {m['signal_days']}")
                      for m in person['measures']]),
                    ('p', 'Unchecked days are not counted as calm.', None)]
        out.append(('p', 'Observations for the latest published day:', None))
        if person['observations']:
            out.append(('bullets', [(item['title'], f"({item['kind']}): {item['detail']}",
                                     [f'{label}: {value}' for label, value in item['readings']] + item['limitations'])
                                    for item in person['observations']]))
    f = report['follow_ups']
    out += [('h2', 'Follow-ups'),
            ('table', ('Open', 'Ongoing', 'Resolved'), [(f['open'], f['ongoing'], f['resolved'])]),
            ('p', 'Counts of the follow-ups you may read (the latest 50, open and ongoing first); note text is not '
             'included in reports.', None),
            ('h2', 'Limitations'),
            ('bullets', [(None, line, []) for line in report['limitations']])]
    return out


def markdown(report):
    """The report as Markdown text, for preview and download."""
    parts = []
    for block in blocks(report):
        kind = block[0]
        if kind in ('title', 'h2', 'h3'):
            parts.append({'title': '# ', 'h2': '## ', 'h3': '### '}[kind] + block[1])
        elif kind == 'p':
            parts.append((f'**{block[2]}** ' if block[2] else '') + block[1])
        elif kind == 'table':
            parts.append('\n'.join(_table(block[1], block[2])))
        else:
            lines = []
            for bold, text, subs in block[1]:
                lines.append('- ' + (f'**{bold}** ' if bold else '') + text)
                lines += [f'  - {sub}' for sub in subs]
            parts.append('\n'.join(lines))
    return '\n\n'.join(parts) + '\n'


def pdf(report):
    """The same report as a PDF (A4, standard fonts). Pages are left uncompressed and the output is
    reproducible, so the privacy matrix can check the downloaded file's text like the Markdown's."""
    from io import BytesIO
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    body = styles['BodyText']
    cell = ParagraphStyle('ReportCell', parent=body, fontSize=8, leading=10)
    head = ParagraphStyle('ReportHead', parent=cell, fontName='Helvetica-Bold')
    margin = 15 * mm
    width = A4[0] - 2 * margin

    def para(text, bold=None, style=body):
        return Paragraph((f'<b>{escape(bold)}</b> ' if bold else '') + escape(str(text)), style)

    story = []
    for block in blocks(report):
        kind = block[0]
        if kind in ('title', 'h2', 'h3'):
            story.append(para(block[1], style=styles[{'title': 'Title', 'h2': 'Heading2', 'h3': 'Heading3'}[kind]]))
        elif kind == 'p':
            story.append(para(block[1], block[2]))
        elif kind == 'table':
            header, rows = block[1], block[2]
            table = Table([[para(h, style=head) for h in header]] + [[para(c, style=cell) for c in row] for row in rows],
                          colWidths=[width / len(header)] * len(header), repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#a59fb0')),
                                       ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#efedf2')),
                                       ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
            story.append(table)
        else:
            story.append(ListFlowable(
                [ListItem([para(text, bold)] + ([ListFlowable([ListItem(para(sub)) for sub in subs], bulletType='bullet')]
                                                if subs else [])) for bold, text, subs in block[1]],
                bulletType='bullet'))
        story.append(Spacer(1, 4))
    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin,
                      bottomMargin=margin, title='Sentra wellness report', author='Sentra', creator='Sentra',
                      invariant=1, pageCompression=0).build(story)
    return buffer.getvalue()
