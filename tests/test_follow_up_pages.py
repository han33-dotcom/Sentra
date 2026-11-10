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


def row(fid, org, pid, assignee='reviewer@a.test', status='open', ended=False):
    return {'follow_up_id': fid, 'org_id': org, 'participant_id': pid, 'opened_by': 'officer@a.test', 'opened_at': AT,
            'status': status, 'assignee': assignee, 'note': f'**note {fid}**', 'updated_at': AT, 'event_count': 1,
            'latest_event_id': fid, 'sharing_ended': ended}


# p92 shares group_only (CONSENTS), so the reader flags their follow-up as sharing ended.
ROWS = [row(1, 'org-a', 'p91'), row(2, 'org-a', 'p92', ended=True), row(3, 'org-b', None, 'officer@b.test'),
        row(4, 'org-a', None, 'officer@a.test')]
EVENTS = [{'event_id': r['follow_up_id'], 'follow_up_id': r['follow_up_id'], 'recorded_at': AT, 'actor': 'officer@a.test',
           'status': 'open', 'assignee': r['assignee'], 'note': r['note']} for r in ROWS]


def shown(r):
    return 'resolved' if r['sharing_ended'] else r['status']


class FollowUpReader(OrgReader):
    scopes = []
    rows = ROWS
    def follow_up_rows(self, org_id=None, participants=None, statuses=None):
        # Like the database: scope and status filters first, then the page limit of 50.
        FollowUpReader.scopes.append((org_id, participants, statuses))
        rows = [dict(r) for r in FollowUpReader.rows if (org_id is None or r['org_id'] == org_id)
                and (participants is None or r['participant_id'] is None or r['participant_id'] in participants)
                and (statuses is None or shown(r) in statuses)]
        rows = sorted(rows, key=lambda r: (shown(r) == 'resolved', -r['latest_event_id']))[:50]
        ids = {r['follow_up_id'] for r in rows}
        return rows, [dict(e) for e in EVENTS if e['follow_up_id'] in ids]


class FollowUpPageTests(unittest.TestCase):
    def open(self, email, writer='fake', rows=ROWS):
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
        FollowUpReader.scopes = []
        FollowUpReader.rows = rows
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
        self.assertEqual(self.titles(app), ['**Follow-up 4 · Group**', '**Follow-up 1 · Participant p91**'])
        self.assertEqual(FollowUpReader.scopes, [('org-a', ['p91'], ('open', 'ongoing'))])  # before the page limit
        self.assertIn('**note 1**', [t.value for t in app.text])  # plain text, not Markdown
        app.selectbox[0].set_value('p91')
        app.selectbox[1].set_value('reviewer@a.test')
        app.text_area[0].input('Agreed to  review sleep\n next week.')
        app.button[0].click().run()
        self.writer.open.assert_called_once_with('officer@a.test', 'org-a', 'p91', 'reviewer@a.test',
                                                 'Agreed to review sleep next week.')
        self.assertIn('Follow-up recorded.', [s.value for s in app.success])
        self.assertFalse(app.error)  # the list reloads after the write instead of stopping the page
        self.assertEqual(len(FollowUpReader.scopes), 2)
        self.assertIn('**Follow-up 1 · Participant p91**', self.titles(app))

    def test_officer_updates_status_and_assignee(self):
        app = self.open('officer@a.test')
        next(b for b in app.selectbox if b.label == 'Status').set_value('ongoing')
        app.text_input[0].input('Checked in today.')
        next(b for b in app.button if b.label == 'Save update').click().run()
        self.writer.update.assert_called_once_with('officer@a.test', 4, 'ongoing', 'officer@a.test', 'Checked in today.')
        self.assertFalse(app.error)
        self.assertEqual(len(FollowUpReader.scopes), 2)
        self.assertIn('Follow-up updated.', [s.value for s in app.success])

    def test_reviewer_and_team_read_without_recording(self):
        reviewer = self.open('reviewer@a.test')
        self.assertEqual(len(self.titles(reviewer)), 2)
        self.assertEqual(len(reviewer.get('form')), 1)  # only the follow-up assigned to them (1), no new-record form
        next(b for b in reviewer.selectbox if b.label == 'Status').set_value('resolved')
        reviewer.text_input[0].input('Back to usual.')
        next(b for b in reviewer.button if b.label == 'Save update').click().run()
        self.writer.update.assert_called_once_with('reviewer@a.test', 1, 'resolved', 'reviewer@a.test', 'Back to usual.')
        team = self.open('team@example.test')
        self.assertEqual(len(self.titles(team)), 3)  # open and ongoing; p92's follow-up is closed (sharing ended)
        self.assertEqual(len(team.get('form')), 0)
        team.radio(key='audit_follow_up_filter').set_value('Resolved').run()
        self.assertEqual(self.titles(team), ['**Follow-up 2 · Participant p92**'])
        self.assertIn('Sharing ended', ' '.join(c.value for c in team.caption))

    def test_resolved_view_reads_its_own_page_beyond_fifty_open_items(self):
        app = self.open('officer@a.test')
        FollowUpReader.rows = ([row(100 + i, 'org-a', None, 'officer@a.test') for i in range(50)]
                               + [row(5, 'org-a', None, 'officer@a.test', status='resolved')])
        app.radio(key='audit_follow_up_filter').set_value('Resolved').run()
        self.assertFalse(app.exception); self.assertFalse(app.error)
        self.assertEqual(FollowUpReader.scopes[-1], ('org-a', ['p91'], ('resolved',)))
        self.assertEqual(self.titles(app), ['**Follow-up 5 · Group**'])
        app.radio(key='audit_follow_up_filter').set_value('Open and ongoing').run()
        self.assertEqual(len(self.titles(app)), 50)
        self.assertEqual(FollowUpReader.scopes[-1][2], ('open', 'ongoing'))  # each filter is its own cached page

    def test_an_inactive_assignee_is_never_silently_replaced(self):
        app = self.open('officer@a.test', rows=[row(7, 'org-a', None, 'former@a.test')])
        app.text_input[0].input('Checked in.')
        next(b for b in app.button if b.label == 'Save update').click().run()
        self.writer.update.assert_not_called()
        self.assertIn('Choose who the follow-up is assigned to.', [e.value for e in app.error])
        self.assertIn('no longer active', ' '.join(c.value for c in app.caption))
        next(b for b in app.selectbox if b.label == 'Assign to' and b.placeholder).set_value('reviewer@a.test')
        app.text_input[0].input('Checked in.')
        next(b for b in app.button if b.label == 'Save update').click().run()
        self.writer.update.assert_called_once_with('officer@a.test', 7, 'open', 'reviewer@a.test', 'Checked in.')

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
