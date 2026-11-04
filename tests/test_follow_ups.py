"""Synthetic follow-up access and history rules for #31; no participant data."""
from datetime import datetime, timezone
import unittest

from sentra.access import resolve
from sentra.errors import SentraError
from sentra.follow_ups import assignees, can_record, clean_note, history, visible

USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True},
         {'org_id': 'org-a', 'email': 'reviewer@a.test', 'role': 'reviewer', 'active': True},
         {'org_id': 'org-a', 'email': 'former@a.test', 'role': 'officer', 'active': False},
         {'org_id': 'org-b', 'email': 'officer@b.test', 'role': 'officer', 'active': True}]
CONSENTS = [{'participant_id': 'p91', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': False, 'membership_open': True},
            {'participant_id': 'p92', 'org_id': 'org-a', 'sharing': 'group_only', 'withdrawn': False, 'membership_open': True}]


def at(hour):
    return datetime(2026, 11, 4, hour, tzinfo=timezone.utc)


FOLLOW_UPS = [{'follow_up_id': 1, 'org_id': 'org-a', 'participant_id': 'p91'},
              {'follow_up_id': 2, 'org_id': 'org-a', 'participant_id': None},
              {'follow_up_id': 3, 'org_id': 'org-a', 'participant_id': 'p92'},   # sharing since reduced
              {'follow_up_id': 4, 'org_id': 'org-b', 'participant_id': None},
              {'follow_up_id': 5, 'org_id': 'org-a', 'participant_id': None}]    # no events: incomplete
EVENTS = [{'event_id': 2, 'follow_up_id': 1, 'recorded_at': at(10), 'status': 'ongoing', 'assignee': 'officer@a.test', 'note': 'b'},
          {'event_id': 1, 'follow_up_id': 1, 'recorded_at': at(9), 'status': 'open', 'assignee': 'reviewer@a.test', 'note': 'a'},
          {'event_id': 3, 'follow_up_id': 2, 'recorded_at': at(9), 'status': 'resolved', 'assignee': 'reviewer@a.test', 'note': 'c'},
          {'event_id': 4, 'follow_up_id': 3, 'recorded_at': at(9), 'status': 'open', 'assignee': 'reviewer@a.test', 'note': 'd'},
          {'event_id': 5, 'follow_up_id': 4, 'recorded_at': at(9), 'status': 'open', 'assignee': 'officer@b.test', 'note': 'e'}]


class FollowUpTests(unittest.TestCase):
    def access(self, email):
        return resolve(email, team_emails=['team@example.test'], org_users=USERS, consents=CONSENTS)

    def test_history_uses_the_latest_event_and_keeps_every_step(self):
        items = {i['follow_up_id']: i for i in history(FOLLOW_UPS, EVENTS)}
        self.assertEqual((items[1]['status'], items[1]['assignee']), ('ongoing', 'officer@a.test'))
        self.assertEqual([e['status'] for e in items[1]['events']], ['open', 'ongoing'])
        self.assertNotIn(5, items)

    def test_notes_follow_organization_and_sharing_boundaries(self):
        items = history(FOLLOW_UPS, EVENTS)
        self.assertEqual(sorted(i['follow_up_id'] for i in visible(items, self.access('officer@a.test'))), [1, 2])
        self.assertEqual(sorted(i['follow_up_id'] for i in visible(items, self.access('reviewer@a.test'))), [1, 2])
        self.assertEqual([i['follow_up_id'] for i in visible(items, self.access('officer@b.test'))], [4])
        self.assertEqual(len(visible(items, self.access('team@example.test'))), 4)

    def test_only_officers_record_and_assignees_are_active_members(self):
        self.assertTrue(can_record(self.access('officer@a.test')))
        self.assertFalse(can_record(self.access('reviewer@a.test')))
        self.assertFalse(can_record(self.access('team@example.test')))
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
