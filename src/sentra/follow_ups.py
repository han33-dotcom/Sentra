"""Follow-up tracking (#31): who may see and record follow-ups; pure, no I/O.

Rows come from `org.follow_ups` and `org.follow_up_events` (sql/010_follow_ups.sql). Notes follow the
same boundaries as the information they are about:
- team operators see every follow-up but record none (they are not organization users);
- an organization user sees only their own organization's follow-ups, and a follow-up about one
  participant only while that participant shares individual details with them;
- only an active officer records or updates; the assignee is any active officer or reviewer.
The database re-checks every write rule; these checks decide what the page offers and shows.
"""
from .errors import SentraError

STATUSES = ('open', 'ongoing', 'resolved')
NOTE_LIMIT = 500
GUIDANCE = ('Wellness wording only: what was observed and what was agreed. No diagnoses, medical details, '
            'names or contact information.')


def history(follow_ups, events):
    """Follow-ups with their events oldest first and the latest event as the current state."""
    by_id = {}
    for event in sorted(events, key=lambda e: (e['recorded_at'], e['event_id'])):
        by_id.setdefault(event['follow_up_id'], []).append(event)
    items = []
    for row in follow_ups:
        trail = by_id.get(row['follow_up_id'])
        if not trail:
            continue  # an item without events is incomplete; never shown as open
        latest = trail[-1]
        items.append({**row, 'status': latest['status'], 'assignee': latest['assignee'], 'note': latest['note'],
                      'updated_at': latest['recorded_at'], 'events': trail})
    return sorted(items, key=lambda i: (STATUSES.index(i['status']), -i['follow_up_id']))


def visible(items, access):
    """Follow-ups this user may read; others are dropped, never masked."""
    if access.is_team:
        return list(items)
    return [i for i in items if i.get('org_id') == access.org_id
            and (i.get('participant_id') is None or access.can_view_individual(i['participant_id']))]


def can_record(access):
    return access.role == 'officer' and access.org_id is not None


def assignees(org_users, org_id):
    """Active officers and reviewers of the organization, by e-mail."""
    return sorted({u['email'] for u in org_users if u.get('org_id') == org_id and u.get('active') is True
                   and u.get('role') in ('officer', 'reviewer')})


def clean_note(note):
    text = ' '.join(str(note or '').split())
    if not 1 <= len(text) <= NOTE_LIMIT:
        raise SentraError(f'Write a note of 1 to {NOTE_LIMIT} characters.')
    return text
