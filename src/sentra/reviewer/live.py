"""Real-data payload for the reviewer page, built on the server for one signed-in user; pure, no I/O.

The viewer (`sentra.viewer_app.reviewer_page`) reads the published board and catalog through
`ViewerReader` under the user's `sentra.access` decision and passes:
- `people`: board rows the user may see individually (individual sharing, or the team);
- `group_people` and `contributors`: rows and IDs allowed to count towards group statistics.

Only individually visible people leave the server as rows. Group figures leave as values computed
here by `sentra.organization.group_summary` and `sentra.trends.group_trend` (one median per person,
then the median, per device). A statistic below `cohort_k_anonymity` contributors leaves as an empty
value with no count, and an empty day is not told apart from a hidden one. The group window ends on
the latest day with a publishable statistic, so suppressed readings never move it.

Owner decisions applied for now (docs/reviewer-data-connections.md): codes only, no names; the
group median (Sentra's method); the refresh time as configured; no device issue date; no daytime
heart rate. Board values pass through unchanged: missing stays missing.
"""
import json
from pathlib import Path

from ..access import PSEUDONYM
from ..organization import KNOWN_DEVICES, group_summary, is_number, latest_group_day, valid_days
from ..processing.board import FIELDS
from ..trends import group_trend, publishable_end

PAGE = Path(__file__).with_name('prototype.html')
DATA_TAG = '<script id="reviewer-data" type="application/json">null</script>'
REFRESH = '01:30'  # .github/workflows/wellness.yml, Asia/Beirut
TREND_DAYS = 30
TREND_KEYS = ('rhr', 'sleep', 'steps')
TILE_KEYS = ('sleep', 'steps', 'rhr')
DAY_KEYS = set(FIELDS) | {'d', 'lvl', 'f', 'a', 'm'}
PROVIDERS = {'google_health': 'Fitbit', 'whoop': 'WHOOP'}


def _person(person, catalog):
    days = []
    for day in valid_days(person):
        row = {k: v for k, v in day.items() if k in DAY_KEYS and (k in ('d', 'lvl', 'a') or v is not None)}
        for key in FIELDS:
            if key in row and not is_number(row[key]):
                del row[key]  # only numeric readings; a malformed value is not shown
        if not isinstance(row.get('f'), list):
            row.pop('f', None)
        if not isinstance(row.get('m'), list):
            row.pop('m', None)
        days.append(row)
    days.sort(key=lambda d: d['d'])
    latest = {}
    for r in catalog:
        if r.get('participant_id') != person.get('id'):
            continue
        stamp = max((str(r[c]) for c in ('latest_point_time', 'latest_interval_end', 'latest_civil_day') if r.get(c)),
                    default=None)
        provider = PROVIDERS.get(r.get('provider'), r.get('provider'))
        if stamp and (provider not in latest or stamp > latest[provider]):
            latest[provider] = stamp
    device = person.get('device') if person.get('device') in KNOWN_DEVICES else 'Unknown'
    return {'id': person['id'], 'dev': device, 'days': days, 'latest': latest}


def _group(group_people, contributors):
    end = publishable_end(group_people, contributors)
    if end is None:
        return {'end': None, 'tiles': [], 'trends': {}}
    tiles = [{'key': r['key'], 'device': r['device'], 'value': r['value'],
              'contributors': r['contributors'] if r['status'] == 'available' else None}
             for r in group_summary(group_people, contributors, end=end, days=1)
             if r['key'] in TILE_KEYS and r['device']]
    trends = {}
    for key in TREND_KEYS:
        found = group_trend(group_people, contributors, key, end=end, days=TREND_DAYS)
        # Only the value leaves: an empty day and a suppressed day look the same.
        trends[key] = {device: [{'d': row['d'], 'value': row['value']} for row in rows]
                       for device, rows in found['devices'].items()}
    return {'end': end.isoformat(), 'tiles': tiles, 'trends': trends}


def payload(*, board, people, group_people, contributors, catalog, today, viewer):
    """JSON-ready reviewer data for one user. `viewer` is a short label of who is signed in (role, organization)."""
    shown = [_person(p, catalog) for p in sorted(people, key=lambda p: str(p.get('id')))
             if isinstance(p, dict) and isinstance(p.get('id'), str) and PSEUDONYM.fullmatch(p['id'])]
    end = latest_group_day(people)
    first = min((d['d'] for p in shown for d in p['days']), default=None)
    return {'mode': 'live', 'viewer': viewer, 'today': today.isoformat(),
            'built_at': board.get('built_at'), 'data_through': board.get('data_through'),
            'latest_individual_day': end.isoformat() if end else None,
            'first_day': first, 'refresh': REFRESH,
            'assessment_version': board.get('assessment_version'), 'board_version': board.get('board_version'),
            'thresholds_status': board.get('thresholds_status'), 'notice': board.get('notice'),
            'people': shown, 'group': _group(group_people, contributors)}


def render(data):
    """The reviewer page with `data` embedded; safe against `</script>` inside values."""
    page = PAGE.read_text(encoding='utf-8')
    if page.count(DATA_TAG) != 1:
        raise ValueError('reviewer page has no data slot')
    # Every '<' becomes a JSON escape, so no value can close the script element or open a comment.
    text = json.dumps(data, separators=(',', ':'), default=str).replace('<', '\\u003c')
    return page.replace(DATA_TAG, f'<script id="reviewer-data" type="application/json">{text}</script>')

