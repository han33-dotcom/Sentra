"""Organization overview and profile pages with synthetic identities and board rows (#39)."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from test_viewer_app import FakeReader

TEAM = ['team@example.test']
USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True}]
# p91 individual; p92-p95 group-only; p96 belongs to another organization.
CONSENTS = ([{'participant_id': 'p91', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': False,
              'membership_open': True}]
            + [{'participant_id': f'p9{i}', 'org_id': 'org-a', 'sharing': 'group_only', 'withdrawn': False,
                'membership_open': True} for i in range(2, 6)]
            + [{'participant_id': 'p96', 'org_id': 'org-b', 'sharing': 'individual', 'withdrawn': False,
                'membership_open': True}])


def day(pid, i):
    values = {'d': '2026-10-07', 'sleep': 400 + i, 'steps': 5000 + 100 * i, 'sleep_b': 410}
    if pid != 'p95':
        values['rhr'] = 55 + i  # only four org-a people supply resting heart rate
    return values


BOARD = {'people': [{'id': f'p9{i}', 'name': f'p9{i}', 'device': 'Fitbit', 'days': [day(f'p9{i}', i)]}
                    for i in range(1, 7)],
         'data_through': '2026-10-07', 'built_at': '2026-10-08T01:30:00Z'}
CATALOG = [{'participant_id': f'p9{i}', 'provider': 'google_health', 'dataset': 'daily_steps',
            'authorization_status': 'authorized', 'latest_civil_day': '2026-10-07'} for i in range(1, 7)]


class OrgReader(FakeReader):
    def board(self): return {**BOARD, 'people': list(BOARD['people'])}
    def group_board(self): return {**BOARD, 'people': list(BOARD['people'])}
    def group_catalog(self): return list(CATALOG)


class User:
    def __init__(self, email):
        self.claims = dict(is_logged_in=True, email=email, email_verified=True,
                           iss='https://accounts.google.com', exp=time.time() + 3600)
    @property
    def is_logged_in(self): return True
    def to_dict(self): return self.claims.copy()


class OrganizationPageTests(unittest.TestCase):
    def open(self, email, page):
        from sentra import viewer_app
        from streamlit.testing.v1 import AppTest
        @contextmanager
        def reader(): yield OrgReader()
        self.patches = [patch.object(viewer_app.st, 'user', User(email)),
                        patch.object(viewer_app, 'open_reader', reader),
                        patch.object(viewer_app, 'load_organization_rows', Mock(return_value=(USERS, CONSENTS)))]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'viewer' / 'app.py', default_timeout=10)
        app.secrets['viewer'] = {'allowed_emails': TEAM}
        app.run()
        app.radio[0].set_value(page).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        return app

    def table(self, app):
        frame = app.dataframe[0].value
        return {row['Measure']: row for row in frame.to_dict('records')}

    def test_officer_overview_counts_own_organization_and_suppresses_small_statistics(self):
        app = self.open('officer@a.test', 'Organization overview')
        metrics = {m.label: m.value for m in app.metric}
        self.assertEqual(metrics['Enrolled'], '5')
        self.assertEqual(metrics['Connected'], '5')
        rows = self.table(app)
        self.assertEqual((rows['Sleep']['Contributors'], rows['Sleep']['Group median']), (5, '403 min'))
        self.assertEqual((rows['Resting heart rate']['Contributors'], rows['Resting heart rate']['Group median']),
                         (4, 'Not shown'))
        self.assertIn('Fewer than 5', rows['Resting heart rate']['Note'])
        self.assertEqual(rows['Heart rate variability']['Contributors'], 0)

    def test_group_only_and_other_organization_never_appear_on_profiles(self):
        app = self.open('officer@a.test', 'Profiles')
        self.assertEqual(app.selectbox[0].options, ['p91'])
        rows = self.table(app)
        self.assertEqual((rows['Sleep']['Latest'], rows['Sleep']['Usual (own baseline)'], rows['Sleep']['Difference']),
                         ('401 min', '410 min', '-9 min'))
        self.assertIn('Not enough history', rows['Resting heart rate']['Note'])

    def test_team_operator_sees_all_participants(self):
        app = self.open('team@example.test', 'Organization overview')
        self.assertEqual({m.label: m.value for m in app.metric}['Enrolled'], '6')
        self.assertEqual(self.table(app)['Resting heart rate']['Contributors'], 5)
        app.radio(key='explore').set_value('Profiles').run()
        self.assertEqual(app.selectbox[0].options, [f'p9{i}' for i in range(1, 7)])

    def test_period_switch_and_empty_board_are_explicit(self):
        app = self.open('officer@a.test', 'Organization overview')
        next(r for r in app.radio if r.label == 'Period').set_value('Last 7 days').run()
        self.assertFalse(app.exception)
        self.assertEqual(self.table(app)['Sleep']['Contributors'], 5)


if __name__ == '__main__':
    unittest.main()
