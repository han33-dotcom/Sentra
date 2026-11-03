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

    def test_organization_officer_signs_in_and_decision_is_cached(self):
        patches, load, _ = self.run_as('officer@a.test', (USERS, consents()))
        with patches[0], patches[1], patches[2]:
            app = self.app(); app.run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            app.radio[0].set_value('Sleep').run()
            self.assertFalse(app.error)
            self.assertEqual(load.call_count, 1)
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

    def test_withdrawal_takes_effect_once_the_cache_expires(self):
        from sentra import viewer_app
        patches, load, _ = self.run_as('officer@a.test', [(USERS, consents()), (USERS, consents(withdrawn=True))])
        with patches[0], patches[1], patches[2], patch.object(viewer_app, 'ACCESS_TTL_SECONDS', 0):
            app = self.app(); app.run()
            self.assertEqual(app.session_state['audit_access'][2].individuals, {'p99'})
            app.run()
            self.assertEqual(load.call_count, 2)
            self.assertEqual(app.session_state['audit_access'][2].individuals, frozenset())


if __name__ == '__main__':
    unittest.main()
