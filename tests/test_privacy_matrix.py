"""Privacy verification matrix for SEN-32: every viewer page, every kind of signed-in user.

The reader below deliberately returns every synthetic participant from every method, as if the
database scoping had failed. Each page must still show only what that user may see: the check
looks at everything rendered (text, tables, options, chart data and the embedded board), not
only at one widget. Synthetic identities and rows only.

Pages added by later tasks join `PAGES` when they merge, and the matrix is rerun with them: Trends
(#40) is included in both views; Follow-ups (#31) joins when it merges.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from sentra.processing.pipeline import ASSESSMENT_VERSION
from test_organization_pages import User
from test_viewer_app import FakeReader

TEAM = ['team@example.test']
# 'Page · View' also selects a view inside the page.
PAGES = ('Daily activity', 'Sleep', 'Workouts', 'Data availability', 'Wellness board',
         'Organization overview', 'Profiles', 'Trends · One person', 'Trends · Group')
USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True},
         {'org_id': 'org-a', 'email': 'reviewer@a.test', 'role': 'reviewer', 'active': True},
         {'org_id': 'org-a', 'email': 'removed@a.test', 'role': 'officer', 'active': False},
         {'org_id': 'org-b', 'email': 'officer@b.test', 'role': 'officer', 'active': True}]
# p91 individual (org-a); p92-p95 group-only (org-a); p96 individual (org-b); p97 withdrawn (org-a);
# p98 pilot data with no consent record. Everyone has data on the board and in the catalog.
CONSENT = {'p91': ('org-a', 'individual', False), 'p92': ('org-a', 'group_only', False),
           'p93': ('org-a', 'group_only', False), 'p94': ('org-a', 'group_only', False),
           'p95': ('org-a', 'group_only', False), 'p96': ('org-b', 'individual', False),
           'p97': ('org-a', 'individual', True)}
EVERYONE = [f'p9{i}' for i in range(1, 9)]
CAN_SEE = {'officer@a.test': {'p91'}, 'reviewer@a.test': {'p91'}, 'officer@b.test': {'p96'}}


def consents(overrides=None):
    rows = dict(CONSENT, **(overrides or {}))
    return [{'participant_id': pid, 'org_id': org, 'sharing': sharing, 'withdrawn': withdrawn, 'membership_open': True}
            for pid, (org, sharing, withdrawn) in rows.items()]


def today():
    return datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Beirut')).date()


def board():
    days = [(today() - timedelta(days=n)).isoformat() for n in (2, 1)]
    people = [{'id': pid, 'name': pid, 'device': 'Fitbit',
               'days': [{'d': d, 'lvl': 'green', 'sleep': 400 + i, 'rhr': 55 + i, 'steps': 5000 + i,
                         'sleep_b': 410, 'rhr_b': 54.0} for d in days]} for i, pid in enumerate(EVERYONE)]
    return {'people': people, 'data_through': days[-1], 'built_at': '2026-11-06T23:30:00Z',
            'assessment_version': ASSESSMENT_VERSION}


class EveryoneReader(FakeReader):
    """A reader whose scoping failed: it hands every participant to every page."""
    def catalog(self):
        return [{'participant_id': pid, 'provider': provider, 'dataset': dataset, 'authorization_status': 'authorized',
                 'latest_civil_day': today().isoformat(), 'latest_interval_end': datetime.now(timezone.utc)}
                for pid in EVERYONE for provider, dataset in (('google_health', 'daily_steps'), ('whoop', 'sleep'))]
    group_catalog = catalog
    def board(self): return board()
    group_board = board


def _decoded(message):
    """Text of a protobuf message with binary payloads decoded: Arrow tables (dataframes, chart data) become
    CSV, other bytes UTF-8. Stringifying the protobuf alone escapes cell bytes and can hide an ID."""
    import pyarrow as pa
    from google.protobuf.message import Message
    out = []
    for _, value in message.ListFields():
        single = isinstance(value, (Message, str, bytes, int, float, bool))
        for item in ([value] if single else value):  # repeated fields are containers
            if isinstance(item, Message):
                out.append(_decoded(item))
            elif isinstance(item, bytes):
                try:
                    out.append(pa.ipc.open_stream(item).read_all().to_pandas().to_csv())
                except Exception:
                    out.append(item.decode('utf-8', 'ignore'))
            else:
                out.append(str(item))
    return '\n'.join(out)


def rendered(app):
    """Everything the page sent to the browser, as text: elements, options, decoded table and chart data,
    iframes."""
    out = []
    def walk(node):
        if getattr(node, 'proto', None) is not None:
            out.append(_decoded(node.proto))
        for child in getattr(node, 'children', {}).values():
            walk(child)
    walk(app.main)
    walk(app.sidebar)
    return '\n'.join(out)


def shown_ids(text):
    return {pid for pid in EVERYONE if re.search(rf'(?<![0-9a-z]){pid}(?![0-9])', text)}


class PrivacyMatrixTests(unittest.TestCase):
    def open(self, email, rows):
        from sentra import viewer_app
        from streamlit.testing.v1 import AppTest
        @contextmanager
        def reader(): yield EveryoneReader()
        state = {'rows': rows}
        self.state = state
        for p in (patch.object(viewer_app.st, 'user', User(email)),
                  patch.object(viewer_app, 'open_reader', reader),
                  patch.object(viewer_app, 'load_organization_rows', Mock(side_effect=lambda e: (USERS, state['rows'])))):
            p.start()
            self.addCleanup(p.stop)
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'viewer' / 'app.py', default_timeout=15)
        app.secrets['viewer'] = {'allowed_emails': TEAM}
        app.run()
        return app

    def visit(self, app, page):
        name, _, view = page.partition(' · ')
        app.radio(key='explore').set_value(name).run()
        if view:
            app.radio(key='audit_trend_view').set_value(view).run()
        self.assertFalse(app.exception, page)
        return rendered(app)

    def test_organization_users_see_only_permitted_participants_on_every_page(self):
        for email, allowed in CAN_SEE.items():
            app = self.open(email, consents())
            for page in PAGES:
                with self.subTest(user=email, page=page):
                    text = self.visit(app, page)
                    self.assertFalse(app.error, page)
                    self.assertLessEqual(shown_ids(text), allowed)

    def test_unknown_and_removed_accounts_see_nothing(self):
        for email in ('stranger@example.test', 'removed@a.test'):
            with self.subTest(user=email):
                app = self.open(email, consents())
                self.assertFalse(app.exception)
                self.assertIn('Access restricted', ' '.join(e.value for e in app.error))
                self.assertEqual(shown_ids(rendered(app)), set())
                self.assertEqual(len(app.dataframe), 0)

    def test_team_operator_keeps_full_operator_access(self):
        app = self.open('team@example.test', consents())
        self.visit(app, 'Profiles')
        self.assertEqual(app.selectbox[0].options, EVERYONE)  # operators run, audit and recover the system

    def test_group_statistics_never_show_small_counts_to_organization_users(self):
        for overrides, expected in (({}, '5'),                                          # p91-p95; p97 withdrawn
                                    ({'p95': ('org-a', 'group_only', True)}, '<5')):    # one more withdrawal
            with self.subTest(overrides=overrides):
                app = self.open('officer@a.test', consents(overrides))
                self.visit(app, 'Organization overview')
                table = app.dataframe[0].value.to_dict('records')
                self.assertEqual({r['Contributors'] for r in table if r['Measure'] == 'Sleep'}, {expected})
                counts = {r['Contributors'] for r in table}
                self.assertFalse(counts & {'1', '2', '3', '4'})
                metrics = {m.label: m.value for m in app.metric}
                for label in ('Connected', 'Recently contributing', 'Assessable'):
                    self.assertNotIn(metrics[label], {'1', '2', '3', '4'}, label)

    def test_withdrawal_applies_on_the_next_render_on_every_page(self):
        app = self.open('officer@a.test', consents())
        self.assertIn('p91', shown_ids(self.visit(app, 'Profiles')))
        self.state['rows'] = consents({'p91': ('org-a', 'individual', True)})
        for page in PAGES:
            with self.subTest(page=page):
                text = self.visit(app, page)
                self.assertEqual(shown_ids(text), set())

    def test_sharing_reduced_to_group_only_hides_individual_details_next_render(self):
        app = self.open('officer@a.test', consents())
        self.assertIn('p91', shown_ids(self.visit(app, 'Wellness board')))
        self.state['rows'] = consents({'p91': ('org-a', 'group_only', False)})
        for page in PAGES:
            with self.subTest(page=page):
                self.assertEqual(shown_ids(self.visit(app, page)), set())


class RenderedScanTests(unittest.TestCase):
    """The scan itself must find an ID wherever a page can put it."""
    @staticmethod
    def page():
        import altair as alt
        import pandas as pd
        import streamlit as st
        where = st.query_params.get('where', 'table')
        frame = pd.DataFrame({'Participant': ['p96'], 'Value': [1]})
        if where == 'table':
            st.dataframe(frame)
        elif where == 'chart':
            st.altair_chart(alt.Chart(frame).mark_point().encode(x='Participant', y='Value'))
        elif where == 'option':
            st.selectbox('Pick', ['p96'])
        else:
            st.caption('nothing here')

    def test_ids_are_found_in_table_cells_chart_data_and_options(self):
        from streamlit.testing.v1 import AppTest
        for where, expected in (('table', {'p96'}), ('chart', {'p96'}), ('option', {'p96'}), ('none', set())):
            with self.subTest(where=where):
                app = AppTest.from_function(self.page)
                app.query_params['where'] = where
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(shown_ids(rendered(app)), expected)


class ExcludedFieldsTests(unittest.TestCase):
    def test_published_board_carries_no_names_contact_or_location(self):
        import pandas as pd
        from sentra.processing.board import payload
        daily = pd.DataFrame([{'subject_id': 'p91', 'date': pd.Timestamp('2026-11-05'), 'usable_day': True,
                               'wellness_level': 'green', 'assessment_state': 'complete', 'sleep_min': 420.0,
                               'email': 'person@example.test', 'display_name': 'Real Name', 'lat': 33.9, 'lon': 35.5,
                               'provider_user_id': 'whoop-123'}])
        published = payload(daily, {'p91': 'whoop'}, built_at='2026-11-06T00:00:00Z')
        person = published['people'][0]
        self.assertEqual(set(person), {'id', 'name', 'device', 'days'})
        self.assertEqual(person['name'], person['id'])  # pseudonym only
        keys = set()
        def collect(value):
            if isinstance(value, dict):
                keys.update(value); [collect(v) for v in value.values()]
            elif isinstance(value, list):
                [collect(v) for v in value]
        collect(published)
        self.assertFalse(keys & {'email', 'display_name', 'lat', 'lon', 'provider_user_id'})
        text = str(published)
        for value in ('person@example.test', 'Real Name', '33.9', '35.5', 'whoop-123'):
            self.assertNotIn(value, text)


if __name__ == '__main__':
    unittest.main()
