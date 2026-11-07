"""Synthetic follow-up access and history rules for #31; no participant data."""
from datetime import datetime, timezone
import unittest

from sentra.access import resolve
from sentra.errors import SentraError
from sentra.follow_ups import assignees, can_record, can_update, clean_note, history, shared_pairs, visible

USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True},
         {'org_id': 'org-a', 'email': 'reviewer@a.test', 'role': 'reviewer', 'active': True},
         {'org_id': 'org-a', 'email': 'former@a.test', 'role': 'officer', 'active': False},
         {'org_id': 'org-b', 'email': 'officer@b.test', 'role': 'officer', 'active': True}]
CONSENTS = [{'participant_id': 'p91', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': False, 'membership_open': True},
            {'participant_id': 'p92', 'org_id': 'org-a', 'sharing': 'group_only', 'withdrawn': False, 'membership_open': True}]


def at(hour):
    return datetime(2026, 11, 4, hour, tzinfo=timezone.utc)


def row(fid, org, pid, status, assignee='reviewer@a.test', count=1):
    return {'follow_up_id': fid, 'org_id': org, 'participant_id': pid, 'status': status, 'assignee': assignee,
            'note': f'note {fid}', 'updated_at': at(10), 'event_count': count}


ROWS = [row(1, 'org-a', 'p91', 'ongoing', 'officer@a.test', count=2),
        row(2, 'org-a', None, 'resolved'),
        row(3, 'org-a', 'p92', 'open'),        # sharing since reduced to group_only
        row(4, 'org-b', None, 'open', 'officer@b.test')]
EVENTS = [{'event_id': 2, 'follow_up_id': 1, 'recorded_at': at(10), 'status': 'ongoing', 'assignee': 'officer@a.test', 'note': 'b'},
          {'event_id': 1, 'follow_up_id': 1, 'recorded_at': at(9), 'status': 'open', 'assignee': 'reviewer@a.test', 'note': 'a'}]


class FollowUpTests(unittest.TestCase):
    def access(self, email):
        return resolve(email, team_emails=['team@example.test'], org_users=USERS, consents=CONSENTS)

    def test_current_state_comes_from_the_latest_event_not_the_history_page(self):
        items = {i['follow_up_id']: i for i in history(ROWS, EVENTS[1:])}  # history page lacks the latest event
        self.assertEqual((items[1]['status'], items[1]['assignee']), ('ongoing', 'officer@a.test'))
        self.assertEqual(([e['status'] for e in items[1]['events']], items[1]['history_complete']), (['open'], False))
        self.assertEqual([e['event_id'] for e in {i['follow_up_id']: i for i in history(ROWS, EVENTS)}[1]['events']], [1, 2])

    def test_follow_ups_about_people_who_stopped_sharing_are_closed(self):
        items = {i['follow_up_id']: i for i in history(ROWS, EVENTS, shared=shared_pairs(CONSENTS))}
        self.assertEqual((items[3]['status'], items[3]['closed_reason']),
                         ('resolved', 'Sharing ended; no further updates are possible.'))
        self.assertEqual((items[1]['status'], items[1]['closed_reason']), ('ongoing', None))
        self.assertIsNone(items[4]['closed_reason'])  # group follow-ups are unaffected

    def test_notes_follow_organization_and_sharing_boundaries(self):
        items = history(ROWS, EVENTS)
        self.assertEqual(sorted(i['follow_up_id'] for i in visible(items, self.access('officer@a.test'))), [1, 2])
        self.assertEqual(sorted(i['follow_up_id'] for i in visible(items, self.access('reviewer@a.test'))), [1, 2])
        self.assertEqual([i['follow_up_id'] for i in visible(items, self.access('officer@b.test'))], [4])
        self.assertEqual(len(visible(items, self.access('team@example.test'))), 4)

    def test_officers_open_and_assignees_update_their_own(self):
        officer, reviewer, team = (self.access(e) for e in ('officer@a.test', 'reviewer@a.test', 'team@example.test'))
        self.assertEqual((can_record(officer), can_record(reviewer), can_record(team)), (True, False, False))
        mine, theirs = row(5, 'org-a', None, 'open', 'reviewer@a.test'), row(6, 'org-a', None, 'open', 'officer@a.test')
        self.assertEqual((can_update(reviewer, mine), can_update(reviewer, theirs)), (True, False))
        self.assertEqual((can_update(officer, theirs), can_update(team, mine)), (True, False))
        self.assertFalse(can_update(officer, {**mine, 'closed_reason': 'Sharing ended'}))
        self.assertEqual(assignees(USERS, 'org-a'), ['officer@a.test', 'reviewer@a.test'])

    def test_notes_are_brief_and_never_empty(self):
        self.assertEqual(clean_note('  Agreed to\n check in  '), 'Agreed to check in')
        for bad in ('', '   ', 'x' * 501, None):
            with self.subTest(note=bad), self.assertRaises(SentraError):
                clean_note(bad)


class FollowUpStoreTests(unittest.TestCase):
    def test_write_role_is_separate_and_optional(self):
        from sentra.follow_up_store import follow_up_credentials
        viewer = {'db': {'user': 'sentra_viewer.ref', 'password': 'v', 'host': 'h', 'port': 6543, 'dbname': 'postgres'}}
        self.assertIsNone(follow_up_credentials({}, viewer))
        db = follow_up_credentials({'followups': {'user': 'sentra_followups.ref', 'password': 'f'}}, viewer)['db']
        self.assertEqual((db['user'], db['password'], db['host']), ('sentra_followups.ref', 'f', 'h'))
        self.assertEqual(viewer['db']['user'], 'sentra_viewer.ref')  # the viewer's settings are untouched
        for bad in ({'user': 'sentra_viewer.ref', 'password': 'f'}, {'user': 'sentra_followups.ref'}):
            with self.subTest(section=bad), self.assertRaises(SentraError):
                follow_up_credentials({'followups': bad}, viewer)

    def test_database_rule_messages_are_shown_and_others_are_generic(self):
        from unittest.mock import Mock
        import psycopg
        from sentra.follow_up_store import FollowUpWriter
        def failing(code, message):
            class Failure(psycopg.Error):
                sqlstate = code
                diag = Mock(message_primary=message)
            return Mock(execute=Mock(side_effect=Failure(message)))
        with self.assertRaisesRegex(SentraError, 'Only an active officer'):
            FollowUpWriter({}, db=failing('42501', 'Only an active officer of this organization can record follow-ups.')).open(
                'a@x.test', 'org-a', None, 'b@x.test', 'n')
        with self.assertRaisesRegex(SentraError, 'nothing was changed'):
            FollowUpWriter({}, db=failing('08006', 'connection to host 10.0.0.1 lost')).update('a@x.test', 1, 'open', 'b@x.test', 'n')


if __name__ == '__main__':
    unittest.main()
