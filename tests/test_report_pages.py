"""The Reports page (#42) with synthetic identities: preview, Markdown download and access boundaries."""
import base64
from contextlib import contextmanager
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch

from test_organization_pages import BOARD, CONSENTS, OrgReader, USERS, User
from test_privacy_matrix import pdf_text

TEAM = ['team@example.test']


class ReportReader(OrgReader):
    def follow_up_rows(self, org_id=None, participants=None, statuses=None):
        return [], []


def files(app):
    """{file name: bytes} for every download link the page rendered."""
    html = ''.join(str(e.proto) for e in app.get('iframe'))
    found = re.findall(r'download=\\?"([^"\\]+)\\?" href=\\?"data:[^;]+;base64,([A-Za-z0-9+/=]+)', html)
    return {name: base64.b64decode(data) for name, data in found}


def downloads(app):
    """The Markdown download(s), as text."""
    return [data.decode('utf-8') for name, data in files(app).items() if name.endswith('.md')]


def pdf_download(app):
    [data] = [data for name, data in files(app).items() if name.endswith('.pdf')]
    return data


def filename(app):
    [name] = [name for name in files(app) if name.endswith('.md')]
    return name


class ReportPageTests(unittest.TestCase):
    def open(self, email, consents=CONSENTS):
        from sentra import viewer_app
        from streamlit.testing.v1 import AppTest
        self.state = {'consents': consents}
        @contextmanager
        def reader(): yield ReportReader()
        for p in (patch.object(viewer_app.st, 'user', User(email)),
                  patch.object(viewer_app, 'open_reader', reader),
                  patch.object(viewer_app, 'load_organization_rows',
                               Mock(side_effect=lambda e: (USERS, self.state['consents'])))):
            p.start()
            self.addCleanup(p.stop)
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'viewer' / 'app.py', default_timeout=10)
        app.secrets['viewer'] = {'allowed_emails': TEAM}
        app.run()
        app.radio(key='explore').set_value('Reports').run()
        self.check(app)
        return app

    def check(self, app):
        self.assertFalse(app.exception)
        self.assertFalse(app.error)

    def preview(self, app):
        return '\n'.join(m.value for m in app.markdown)

    def test_officer_report_lists_only_individually_shared_people(self):
        app = self.open('officer@a.test')
        self.assertEqual(app.multiselect(key='audit_report_people').options, ['p91'])
        self.assertNotIn('p91', self.preview(app))  # nobody selected yet
        app.multiselect(key='audit_report_people').set_value(['p91']).run()
        self.check(app)
        [text] = downloads(app)
        for shown in (self.preview(app), text):
            self.assertIn('### p91', shown)
            for pid in ('p92', 'p93', 'p94', 'p95', 'p96'):
                self.assertNotIn(pid, shown)
        self.assertIn('Organization: org-a', text)
        self.assertIn('| Sleep | Fitbit | 403 min | 5 |', text)
        data = pdf_download(app)  # the same content as a PDF
        self.assertEqual({pid for pid in ('p91', 'p92', 'p93', 'p94', 'p95', 'p96') if pid in pdf_text(data)}, {'p91'})

    def test_the_download_is_the_previewed_markdown(self):
        app = self.open('officer@a.test')
        [text] = downloads(app)
        self.assertIn('# Sentra wellness report', text)
        self.assertIn('## Limitations', text)
        self.assertRegex(filename(app), r'^sentra-report-org-a-\d{4}-\d{2}-\d{2}-7d\.md$')
        self.assertEqual(sorted(files(app)), sorted([filename(app), filename(app)[:-3] + '.pdf']))
        self.assertTrue(pdf_download(app).startswith(b'%PDF-'))

    def test_withdrawal_removes_the_person_on_the_next_render(self):
        app = self.open('officer@a.test')
        app.multiselect(key='audit_report_people').set_value(['p91']).run()
        self.assertIn('### p91', downloads(app)[0])
        for change in ({'withdrawn': True}, {'sharing': 'group_only'}):
            with self.subTest(change=change):
                self.state['consents'] = [dict(c, **change) if c['participant_id'] == 'p91' else c for c in CONSENTS]
                app.run()
                self.check(app)
                self.assertEqual(app.multiselect(key='audit_report_people').value, [])
                self.assertNotIn('p91', downloads(app)[0])
                self.assertNotIn('p91', pdf_text(pdf_download(app)))
                self.assertNotIn('p91', self.preview(app))
                self.state['consents'] = CONSENTS
                app.run()
                app.multiselect(key='audit_report_people').set_value(['p91']).run()

    def test_demonstration_copy_uses_only_people_who_agreed(self):
        rows = [dict(c, demonstration=c['participant_id'] in ('p92', 'p93')) for c in CONSENTS]
        app = self.open('officer@a.test', rows)
        app.toggle(key='audit_report_demo').set_value(True).run()
        self.check(app)
        self.assertEqual(app.multiselect(key='audit_report_people').options, [])  # p91 did not agree
        [text] = downloads(app)
        self.assertIn('Demonstration copy', text)
        self.assertIn('| 2 |', text)  # enrolled: the two who agreed
        self.assertIn('No group statistic can be shown', text)  # fewer than 5 agreed
        self.assertRegex(filename(app), r'-7d-demo\.md$')
        self.assertIn('Demonstration copy', pdf_text(pdf_download(app)))

    def test_saving_a_follow_up_refreshes_the_report_counts(self):
        from sentra import viewer_app
        @contextmanager
        def writer(): yield Mock()
        state = {'audit_follow_ups': 1, 'audit_follow_ups_scope': 1, 'audit_report_follow_ups': 1,
                 'audit_report_follow_ups_scope': 1}
        with patch.object(viewer_app, 'open_follow_up_writer', writer), \
                patch.object(viewer_app, 'st', Mock(session_state=state)):
            viewer_app.save_follow_up(lambda w: None, 'Follow-up recorded.')
        self.assertNotIn('audit_report_follow_ups_scope', state)  # the next report render reads again
        self.assertNotIn('audit_follow_ups_scope', state)

    def test_team_operator_report_covers_all_organizations(self):
        app = self.open('team@example.test')
        self.assertEqual(app.multiselect(key='audit_report_people').options, [p['id'] for p in BOARD['people']])
        self.assertIn('Organization: All organizations (team operator)', downloads(app)[0])


if __name__ == '__main__':
    unittest.main()
