"""Organization sign-in through the shared access check; synthetic identities and rows only."""
from contextlib import contextmanager
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from test_viewer_app import FakeReader

TEAM = ['team@example.test']
USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True}]


def consents(withdrawn=False):
    return [{'participant_id': 'p99', 'org_id': 'org-a', 'sharing': 'individual',
             'withdrawn': withdrawn, 'membership_open': True}]


class User:
    def __init__(self, email):
        self.claims = dict(is_logged_in=True, email=email, email_verified=True,
                           iss='https://accounts.google.com', exp=time.time() + 3600)
    @property
    def is_logged_in(self): return True
    def to_dict(self): return self.claims.copy()


class ViewerAccessTests(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'viewer' / 'app.py', default_timeout=10)
        app.secrets['viewer'] = {'allowed_emails': TEAM}
        return app

    def run_as(self, email, rows, reads=None):
        from sentra import viewer_app
        reads = reads or Mock(wraps=FakeReader())
        @contextmanager
        def reader(): yield reads
        load = Mock(side_effect=rows) if isinstance(rows, list) else Mock(return_value=rows)
        patches = (patch.object(viewer_app.st, 'user', User(email)), patch.object(viewer_app, 'open_reader', reader),
                   patch.object(viewer_app, 'load_organization_rows', load))
        return patches, load, reads

    def test_team_operator_needs_no_organization_read(self):
        patches, load, _ = self.run_as('team@example.test', ([], []))
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            load.assert_not_called()

    def test_organization_access_is_cached_within_render_but_rechecked_next_render(self):
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()))
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            self.assertEqual(load.call_count, 1)
            app.radio[0].set_value('Sleep').run()
            self.assertFalse(app.error)
            self.assertEqual(load.call_count, 2)
            self.assertEqual(app.session_state['audit_access'][2].individuals, {'p99'})

    def test_unknown_account_is_denied_before_any_protected_read(self):
        reads = Mock(wraps=FakeReader())
        patches, load, _ = self.run_as('stranger@x.test', ([], []), reads)
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Access restricted' in e.value for e in app.error))
            reads.catalog.assert_not_called(); reads.board.assert_not_called()
            self.assertNotIn('audit_access', app.session_state)

    def test_withdrawal_hides_the_participant_on_the_next_render(self):
        from sentra import viewer_app
        state = {'withdrawn': False}
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()))
        load.side_effect = lambda email: (USERS, consents(withdrawn=state['withdrawn']))
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.error)
            self.assertEqual(app.selectbox[0].options, ['p99'])
            state['withdrawn'] = True
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('No participant has shared' in i.value for i in app.info))
            self.assertEqual(len(app.selectbox), 0)

    def test_group_only_change_clears_cached_individual_data_on_next_render(self):
        state = {'sharing': 'individual'}
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()))
        def rows(email):
            return USERS, [{**consents()[0], 'sharing': state['sharing']}]
        load.side_effect = rows
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertEqual(app.selectbox[0].options, ['p99'])
            app.session_state['audit_readable_csv'] = b'synthetic previously prepared export'
            state['sharing'] = 'group_only'
            app.run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            self.assertTrue(any('No participant has shared' in item.value for item in app.info))
            self.assertEqual(len(app.selectbox), 0)
            self.assertNotIn('audit_readable_csv', app.session_state)

    def test_removed_officer_is_denied_on_next_render_without_waiting(self):
        state = {'active': True}
        reads = Mock(wraps=FakeReader())
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()), reads)
        load.side_effect = lambda email: ([{**USERS[0], 'active': state['active']}], consents())
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.error)
            state['active'] = False
            reads.reset_mock()
            app.run()
            self.assertTrue(any('Access restricted' in item.value for item in app.error))
            reads.catalog.assert_not_called(); reads.board.assert_not_called()

    def test_officer_sees_only_permitted_people_and_no_operator_tools(self):
        class TwoPeople(FakeReader):
            def catalog(self):
                return super().catalog() + [{'participant_id': 'p98', 'provider': 'whoop', 'dataset': 'sleep'}]
        from sentra import viewer_app
        from sentra.viewer_reader import ViewerReader
        reads = Mock(wraps=TwoPeople())
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()), reads)
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            self.assertEqual(app.selectbox[0].options, ['p99'])
            labels = [b.label for b in app.button]
            self.assertNotIn('Load audit details', labels)
            self.assertNotIn('Prepare readable CSV', labels)
        # The reader itself refuses a participant outside the decision, even if asked directly.
        from sentra.shared import Limits
        denied = ViewerReader({}, Limits(), lambda: 'officer@a.test', db=Mock(), budget_db=Mock(),
                              can_view=lambda p: p == 'p99')
        from datetime import date
        from sentra.viewer_data import Selection
        from sentra.errors import SentraError
        with self.assertRaisesRegex(SentraError, 'outside your permitted access'):
            denied.measurements(Selection('p98', 'whoop', 'sleep', date(2026, 10, 7), date(2026, 10, 8)))

    def test_officer_board_contains_only_permitted_people(self):
        class Board(FakeReader):
            def board(self):
                return {'people': [{'id': 'p98', 'name': 'p98', 'device': 'WHOOP', 'days': []},
                                   {'id': 'p99', 'name': 'p99', 'device': 'WHOOP', 'days': []}],
                        'data_through': '2026-10-07', 'built_at': '2026-11-01T23:30:00Z'}
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()), Mock(wraps=Board()))
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            app.radio[0].set_value('Wellness board').run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            html = ''.join(str(e.proto) for e in app.get('iframe'))
            self.assertIn('p99', html)
            self.assertNotIn('p98', html)

    def test_open_reader_rechecks_the_current_decision_at_every_read(self):
        """Hassan's P1: revocation while a reader stays open must deny the next read."""
        from datetime import date
        from sentra import viewer_app
        from sentra.access import resolve
        from sentra.errors import SentraError
        from sentra.shared import Limits
        from sentra.viewer_data import Selection
        from sentra.viewer_reader import ViewerReader
        allowed = resolve('officer@a.test', team_emails=TEAM, org_users=USERS, consents=consents())
        revoked = resolve('officer@a.test', team_emails=TEAM, org_users=USERS, consents=consents(withdrawn=True))
        decisions = iter([allowed, allowed, revoked, revoked, revoked])
        captured = {}
        def build(credentials, limits, principal, can_view, can_count=None):
            captured['reader'] = ViewerReader(credentials, Limits(), lambda: 'officer@a.test', db=Mock(),
                                              budget_db=Mock(), can_view=can_view)
            return captured['reader']
        with patch.object(viewer_app, 'current_access', side_effect=lambda: next(decisions)), \
                patch.object(viewer_app, 'runtime_settings', return_value=({}, Limits(), None)), \
                patch.object(viewer_app, 'ViewerReader', side_effect=build), \
                patch.object(ViewerReader, 'close', lambda self: None):
            with viewer_app.open_reader() as reader:
                self.assertTrue(reader.can_view('p99'))  # still permitted
                with self.assertRaisesRegex(SentraError, 'outside your permitted access'):
                    reader.measurements(Selection('p99', 'whoop', 'sleep', date(2026, 10, 7), date(2026, 10, 8)))

    def test_newly_shared_participant_appears_without_signing_out(self):
        """Hassan's P2: an empty scoped catalog must refetch when the permitted set grows."""
        from sentra import viewer_app
        state = {'shared': False}
        rows = lambda: [] if not state['shared'] else consents()
        class Scoped(FakeReader):
            def catalog(self):
                return [r for r in super().catalog() if viewer_app.current_access().can_view_individual(r['participant_id'])]
        patches, load, _ = self.run_as('officer@a.test', (USERS, []), Mock(wraps=Scoped()))
        load.side_effect = lambda email: (USERS, rows())
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertTrue(any('No participant has shared' in i.value for i in app.info))
            self.assertIn('Check again', [b.label for b in app.button])
            state['shared'] = True
            app.run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            self.assertEqual(app.selectbox[0].options, ['p99'])

if __name__ == '__main__':
    unittest.main()
