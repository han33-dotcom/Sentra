"""Follow-up tracking (#31): who may see and record follow-ups; pure, no I/O.

Rows come from `org.follow_ups` and `org.follow_up_events` (sql/010_follow_ups.sql). Notes follow the
same boundaries as the information they are about:
- team operators see every follow-up but record none (they are not organization users);
- an organization user sees only their own organization's follow-ups, and a follow-up about one
  participant only while that participant shares individual details with them;
- only an active officer opens a follow-up; officers and the current assignee (any active officer or
  reviewer) update it. A follow-up about someone who stopped sharing individual details is closed.
The database re-checks every write rule; these checks decide what the page offers and shows.
"""
from .errors import SentraError

STATUSES = ('open', 'ongoing', 'resolved')
NOTE_LIMIT = 500
GUIDANCE = ('Wellness wording only: what was observed and what was agreed. No diagnoses, medical details, '
            'names or contact information.')


def history(rows, events, *, shared=None):
    """Follow-ups with their authoritative current state and their latest events, oldest first.

    `rows` already carry the latest event's status, assignee, note and time (fetched separately from the
    history page). `shared`, when given, is the set of (participant, organization) pairs with current
    individual sharing: a follow-up about anyone else can take no further updates, so it is shown as
    closed rather than open forever."""
    trails = {}
    for event in sorted(events, key=lambda e: (e['recorded_at'], e['event_id'])):
        trails.setdefault(event['follow_up_id'], []).append(event)
    items = []
    for row in rows:
        trail = trails.get(row['follow_up_id'], [])
        item = {**row, 'events': trail, 'history_complete': len(trail) >= row.get('event_count', len(trail)),
                'closed_reason': None}
        if (shared is not None and row.get('participant_id') and row['status'] != 'resolved'
                and (row['participant_id'], row.get('org_id')) not in shared):
            item.update(status='resolved', closed_reason='Sharing ended; no further updates are possible.')
        items.append(item)
    return sorted(items, key=lambda i: (STATUSES.index(i['status']), -i['follow_up_id']))


def visible(items, access):
    """Follow-ups this user may read; others are dropped, never masked."""
    if access.is_team:
        return list(items)
    return [i for i in items if i.get('org_id') == access.org_id
            and (i.get('participant_id') is None or access.can_view_individual(i['participant_id']))]


def can_record(access):
    """Opening follow-ups: active officers of an organization."""
    return access.role == 'officer' and access.org_id is not None


def can_update(access, item):
    """Officers update any visible follow-up; the current assignee updates their own."""
    return (access.org_id is not None and item.get('org_id') == access.org_id and item.get('closed_reason') is None
            and (access.role == 'officer' or item.get('assignee') == access.email))


def shared_pairs(consents):
    """(participant, organization) pairs with current individual sharing, from `org.current_consent` rows."""
    return {(c.get('participant_id'), c.get('org_id')) for c in consents if c.get('sharing') == 'individual'
            and c.get('withdrawn') is False and c.get('membership_open') is True}


def assignees(org_users, org_id):
    """Active officers and reviewers of the organization, by e-mail."""
    return sorted({u['email'] for u in org_users if u.get('org_id') == org_id and u.get('active') is True
                   and u.get('role') in ('officer', 'reviewer')})


def clean_note(note):
    text = ' '.join(str(note or '').split())
    if not 1 <= len(text) <= NOTE_LIMIT:
        raise SentraError(f'Write a note of 1 to {NOTE_LIMIT} characters.')
    return text
