"""Organization overview and profile pages with synthetic identities and board rows (#39)."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from test_viewer_app import FakeReader
from sentra.processing.pipeline import ASSESSMENT_VERSION

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
    catalog_calls = 0
    def catalog(self):
        OrgReader.catalog_calls += 1
        return list(CATALOG)
    def board(self): return {**BOARD, 'people': list(BOARD['people'])}
    def group_board(self): return {**BOARD, 'people': list(BOARD['people'])}
    def group_catalog(self):
        OrgReader.catalog_calls += 1
        return list(CATALOG)


class User:
    def __init__(self, email):
        self.claims = dict(is_logged_in=True, email=email, email_verified=True,
                           iss='https://accounts.google.com', exp=time.time() + 3600)
    @property
    def is_logged_in(self): return True
    def to_dict(self): return self.claims.copy()


class OrganizationPageTests(unittest.TestCase):
    def open(self, email, page, consents=CONSENTS):
        from sentra import viewer_app
        from streamlit.testing.v1 import AppTest
        @contextmanager
        def reader(): yield OrgReader()
        for p in (patch.object(viewer_app.st, 'user', User(email)),
                  patch.object(viewer_app, 'open_reader', reader),
                  patch.object(viewer_app, 'load_organization_rows', Mock(return_value=(USERS, consents)))):
            p.start()
            self.addCleanup(p.stop)  # per patch, so a second open() in one test cannot leak the first
        OrgReader.catalog_calls = 0
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
        self.assertEqual((rows['Sleep']['Contributors'], rows['Sleep']['Group median']), ('5', '403 min'))
        self.assertEqual(rows['Sleep']['Device'], 'Fitbit')
        # Four contributors: suppressed, and the exact count is not disclosed.
        self.assertEqual((rows['Resting heart rate']['Contributors'], rows['Resting heart rate']['Group median']),
                         ('<5', 'Not shown'))
        self.assertIn('Fewer than 5', rows['Resting heart rate']['Note'])
        self.assertEqual(rows['Heart rate variability']['Contributors'], '0')

    def test_group_only_and_other_organization_never_appear_on_profiles(self):
        app = self.open('officer@a.test', 'Profiles')
        self.assertEqual(app.selectbox[0].options, ['p91'])
        rows = self.table(app)
        self.assertEqual((rows['Sleep']['Latest'], rows['Sleep']['Usual (own baseline)'], rows['Sleep']['Difference']),
                         ('401 min', '410 min', '-9 min'))
        self.assertIn('Not enough history', rows['Resting heart rate']['Note'])

    def test_latest_group_day_excludes_other_organizations(self):
        people = [{**p, 'days': [dict(p['days'][0])]} for p in BOARD['people']]
        people[-1]['days'][0]['d'] = '2026-11-03'  # org-b updated after org-a
        with patch.dict(BOARD, people=people, data_through='2026-11-03'):
            app = self.open('officer@a.test', 'Organization overview')
            self.assertEqual(self.table(app)['Sleep']['Group median'], '403 min')
            self.assertTrue(any('Published days through 2026-10-07.' in c.value for c in app.caption))

    def test_assessable_counts_consume_the_versioned_board_state(self):
        from sentra import viewer_app
        people = [{**p, 'days': [{**p['days'][0], 'lvl': 'green'}]} for p in BOARD['people']]
        with patch.dict(BOARD, people=people, assessment_version=ASSESSMENT_VERSION), \
                patch.object(viewer_app, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 8, tzinfo=timezone.utc)
            app = self.open('officer@a.test', 'Organization overview')
            self.assertEqual({m.label: m.value for m in app.metric}['Assessable'], '5')
            people[4]['days'][0].update(lvl='amber', a='partial')
            next(b for b in app.button if b.label == 'Reload overview').click().run()
            self.assertFalse(app.exception)
            self.assertEqual({m.label: m.value for m in app.metric}['Assessable'], '<5')

    def test_team_operator_sees_all_participants(self):
        app = self.open('team@example.test', 'Organization overview')
        self.assertEqual({m.label: m.value for m in app.metric}['Enrolled'], '6')
        self.assertEqual(self.table(app)['Resting heart rate']['Contributors'], '5')
        app.radio(key='explore').set_value('Profiles').run()
        self.assertEqual(app.selectbox[0].options, [f'p9{i}' for i in range(1, 7)])

    def test_team_view_excludes_withdrawn_participants(self):
        withdrawn = [{**c, 'withdrawn': True} if c['participant_id'] == 'p96' else c for c in CONSENTS]
        app = self.open('team@example.test', 'Organization overview', consents=withdrawn)
        self.assertEqual({m.label: m.value for m in app.metric}['Enrolled'], '5')
        self.assertEqual(self.table(app)['Sleep']['Contributors'], '5')
        self.assertEqual(self.table(app)['Resting heart rate']['Contributors'], '<5')

    def test_team_overview_reuses_the_explore_catalog(self):
        app = self.open('team@example.test', 'Daily activity')
        app.radio(key='explore').set_value('Organization overview').run()
        self.assertFalse(app.exception)
        self.assertEqual(OrgReader.catalog_calls, 1)  # one catalog query for both pages

    def test_team_withdrawal_is_applied_on_the_next_render(self):
        from sentra import viewer_app
        app = self.open('team@example.test', 'Organization overview')
        self.assertEqual({m.label: m.value for m in app.metric}['Enrolled'], '6')
        withdrawn = [{**c, 'withdrawn': True} if c['participant_id'] == 'p96' else c for c in CONSENTS]
        viewer_app.load_organization_rows.return_value = (USERS, withdrawn)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual({m.label: m.value for m in app.metric}['Enrolled'], '5')
        self.assertEqual(self.table(app)['Sleep']['Contributors'], '5')

    def test_period_switch_and_empty_board_are_explicit(self):
        app = self.open('officer@a.test', 'Organization overview')
        next(r for r in app.radio if r.label == 'Period').set_value('Last 7 days').run()
        self.assertFalse(app.exception)
        self.assertEqual(self.table(app)['Sleep']['Contributors'], '5')

    def test_personal_trends_list_only_individually_permitted_people(self):
        app = self.open('officer@a.test', 'Trends')
        self.assertEqual(app.selectbox(key='audit_trend_person').options, ['p91'])
        metrics = {m.label: m.value for m in app.metric}
        self.assertEqual(metrics['Days with data'], '1 of 7')
        self.assertEqual(metrics['Usual (own baseline)'], '410 min')
        self.assertEqual(len(app.get('vega_lite_chart')), 1)

    def test_group_trends_show_only_days_with_enough_contributors(self):
        app = self.open('officer@a.test', 'Trends')
        app.radio(key='audit_trend_view').set_value('Group').run()
        rows = {r['Device']: r for r in app.dataframe[0].value.to_dict('records')}
        self.assertEqual((rows['Fitbit']['Days shown'], rows['Fitbit']['Most contributors on a day']), (1, '5'))
        self.assertNotIn('Days hidden (fewer than 5)', rows['Fitbit'])  # organization users get no hidden counts
        app.selectbox(key='audit_trend_metric').set_value('Resting heart rate').run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 0)  # a device below 5 on every day is not listed at all
        self.assertIn('nothing is shown', ' '.join(i.value for i in app.info))

    def test_suppressed_readings_never_move_the_window_or_the_empty_state(self):
        def group_view(extra, metric):
            consents = CONSENTS + [{'participant_id': 'p97', 'org_id': 'org-a', 'sharing': 'group_only',
                                    'withdrawn': False, 'membership_open': True}]
            board = {**BOARD, 'people': list(BOARD['people']) + extra}
            with patch.object(OrgReader, 'group_board', lambda self: board):
                app = self.open('officer@a.test', 'Trends', consents=consents)
                app.radio(key='audit_trend_view').set_value('Group').run()
                app.selectbox(key='audit_trend_metric').set_value(metric).run()
            self.assertFalse(app.exception)
            return ([i.value for i in app.info], [c.value for c in app.caption][-1:], len(app.dataframe))
        lone = [{'id': 'p97', 'name': 'p97', 'device': 'WHOOP', 'days': [{'d': '2026-10-08', 'sleep': 300, 'rec': 40}]}]
        for metric in ('Sleep', 'WHOOP recovery'):
            with self.subTest(metric=metric):
                # One group-only WHOOP reading a day later changes nothing an officer can see.
                self.assertEqual(group_view(lone, metric), group_view([], metric))
        sleep = group_view(lone, 'Sleep')
        self.assertIn('Days through 2026-10-07', sleep[1][0])

    def test_team_group_trends_keep_device_detail(self):
        app = self.open('team@example.test', 'Trends')
        app.radio(key='audit_trend_view').set_value('Group').run()
        app.selectbox(key='audit_trend_metric').set_value('Heart rate variability').run()
        self.assertFalse(app.exception)
        self.assertIn('No eligible contributor', ' '.join(i.value for i in app.info))

    def test_switching_between_permitted_people_keeps_working(self):
        both = [{**c, 'sharing': 'individual'} if c['participant_id'] == 'p92' else c for c in CONSENTS]
        app = self.open('officer@a.test', 'Trends', consents=both)
        app.selectbox(key='audit_trend_person').set_value('p92').run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual({m.label: m.value for m in app.metric}['Days with data'], '1 of 7')
        self.assertIn('older rules', ' '.join(c.value for c in app.caption))  # BOARD has no assessment_version

    def test_profile_explains_observations_for_permitted_people_only(self):
        today = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Beirut')).date().isoformat()
        people = [{**p, 'days': [{'d': today, 'lvl': 'amber', 'f': ['rhr_up'], 'rhr': 64, 'rhr_b': 55.0, 'rhr_z': 2.4,
                                  'a': 'partial', 'm': ['hrv:baseline_building']}]} for p in BOARD['people']]
        board = {**BOARD, 'people': people, 'data_through': today, 'assessment_version': ASSESSMENT_VERSION}
        with patch.object(OrgReader, 'board', lambda self: board):
            app = self.open('officer@a.test', 'Profiles')
        text = ' '.join(m.value for m in app.markdown) + ' '.join(c.value for c in app.caption)
        self.assertIn('Resting heart rate above your normal', text)
        self.assertIn('Partial assessment', text)
        self.assertIn('Heart-rate variability: personal normal still building', text)
        self.assertIn('not a medical conclusion', text)
        self.assertEqual(app.selectbox[0].options, ['p91'])  # group-only people get no observations

    def test_profile_observations_wait_for_the_current_rules(self):
        today = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Beirut')).date().isoformat()
        legacy = {**BOARD, 'people': [{**p, 'days': [{**p['days'][0], 'd': today, 'lvl': 'green'}]}
                                      for p in BOARD['people']]}  # no assessment_version
        with patch.object(OrgReader, 'board', lambda self: legacy):
            app = self.open('officer@a.test', 'Profiles')
        self.assertIn('Published under older rules', ' '.join(m.value for m in app.markdown))

    def test_profile_with_stale_data_draws_no_wellness_conclusion(self):
        app = self.open('officer@a.test', 'Profiles')  # BOARD's latest day is weeks old
        text = ' '.join(m.value for m in app.markdown)
        self.assertIn('No recent data', text)
        self.assertNotIn('No change from usual pattern', text)


if __name__ == '__main__':
    unittest.main()
