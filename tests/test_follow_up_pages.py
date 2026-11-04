"""Follow-ups page with synthetic identities, rows and a fake write path (#31)."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from sentra.errors import SentraError
from test_organization_pages import CONSENTS, OrgReader, User

TEAM = ['team@example.test']
USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True},
         {'org_id': 'org-a', 'email': 'reviewer@a.test', 'role': 'reviewer', 'active': True},
         {'org_id': 'org-b', 'email': 'officer@b.test', 'role': 'officer', 'active': True}]
AT = datetime(2026, 11, 4, 9, tzinfo=timezone.utc)
ROWS = ([{'follow_up_id': 1, 'org_id': 'org-a', 'participant_id': 'p91', 'opened_by': 'officer@a.test', 'opened_at': AT},
         {'follow_up_id': 2, 'org_id': 'org-a', 'participant_id': 'p92', 'opened_by': 'officer@a.test', 'opened_at': AT},
         {'follow_up_id': 3, 'org_id': 'org-b', 'participant_id': None, 'opened_by': 'officer@b.test', 'opened_at': AT}],
        [{'event_id': i, 'follow_up_id': i, 'recorded_at': AT, 'actor': 'officer@a.test', 'status': 'open',
          'assignee': 'reviewer@a.test', 'note': f'**note {i}**'} for i in (1, 2, 3)])


class FollowUpReader(OrgReader):
    def follow_up_rows(self): return [dict(r) for r in ROWS[0]], [dict(e) for e in ROWS[1]]


class FollowUpPageTests(unittest.TestCase):
    def open(self, email, writer='fake'):
        from sentra import viewer_app
        from streamlit.testing.v1 import AppTest
        self.writer = Mock() if writer == 'fake' else writer
        @contextmanager
        def reader(): yield FollowUpReader()
        @contextmanager
        def write(): yield self.writer
        for p in (patch.object(viewer_app.st, 'user', User(email)),
                  patch.object(viewer_app, 'open_reader', reader),
                  patch.object(viewer_app, 'open_follow_up_writer', write),
                  patch.object(viewer_app, 'load_organization_rows', Mock(return_value=(USERS, CONSENTS)))):
            p.start()
            self.addCleanup(p.stop)
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'viewer' / 'app.py', default_timeout=10)
        app.secrets['viewer'] = {'allowed_emails': TEAM}
        app.run()
        app.radio(key='explore').set_value('Follow-ups').run()
        self.assertFalse(app.exception)
        return app

    def titles(self, app):
        return [m.value for m in app.markdown if m.value.startswith('**Follow-up')]

    def test_officer_sees_only_permitted_notes_and_records_one(self):
        app = self.open('officer@a.test')
        self.assertEqual(self.titles(app), ['**Follow-up 1 · Participant p91**'])  # p92 is group-only; 3 is org-b
        self.assertIn('**note 1**', [t.value for t in app.text])  # plain text, not Markdown
        app.selectbox[0].set_value('p91')
        app.selectbox[1].set_value('reviewer@a.test')
        app.text_area[0].input('Agreed to  review sleep\n next week.')
        app.button[0].click().run()
        self.writer.open.assert_called_once_with('officer@a.test', 'org-a', 'p91', 'reviewer@a.test',
                                                 'Agreed to review sleep next week.')
        self.assertIn('Follow-up recorded.', [s.value for s in app.success])

    def test_officer_updates_status_and_assignee(self):
        app = self.open('officer@a.test')
        next(b for b in app.selectbox if b.label == 'Status').set_value('ongoing')
        app.text_input[0].input('Checked in today.')
        next(b for b in app.button if b.label == 'Save update').click().run()
        self.writer.update.assert_called_once_with('officer@a.test', 1, 'ongoing', 'reviewer@a.test', 'Checked in today.')

    def test_reviewer_and_team_read_without_recording(self):
        reviewer = self.open('reviewer@a.test')
        self.assertEqual(self.titles(reviewer), ['**Follow-up 1 · Participant p91**'])
        self.assertEqual(len(reviewer.get('form')), 0)
        team = self.open('team@example.test')
        self.assertEqual(len(self.titles(team)), 3)
        self.assertEqual(len(team.get('form')), 0)

    def test_write_failures_are_explained_and_nothing_is_claimed(self):
        writer = Mock()
        writer.open.side_effect = SentraError('This participant does not currently share individual details with this organization.')
        app = self.open('officer@a.test', writer=writer)
        app.text_area[0].input('Short note.')
        app.button[0].click().run()
        self.assertIn('does not currently share', ' '.join(e.value for e in app.error))
        self.assertEqual(len(app.success), 0)
        unconfigured = self.open('officer@a.test', writer=None)
        unconfigured.text_area[0].input('Short note.')
        unconfigured.button[0].click().run()
        self.assertIn('not configured yet', ' '.join(e.value for e in unconfigured.error))


if __name__ == '__main__':
    unittest.main()
