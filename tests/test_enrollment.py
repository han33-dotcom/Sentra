"""Synthetic enrollment protocol tests. No live provider requests or secrets."""
from contextlib import contextmanager, redirect_stdout
import base64
import hashlib
import importlib.util
from io import StringIO
import json
from pathlib import Path
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from pglast import parse_sql

from sentra.enrollment import EnrollmentError, EnrollmentSettings, ProviderLogin, scopes
from sentra.cloud_run import configured_connections, connection_targets

HAS_API = all(importlib.util.find_spec(m) for m in ('fastapi', 'httpx'))
if HAS_API:
    from fastapi.testclient import TestClient
    from sentra.enrollment_web import create_app


def settings(**kwargs):
    return EnrollmentSettings(origin=kwargs.pop('origin', 'https://join.sentra.example'),
        db=kwargs.pop('db', {}), token_key=Fernet.generate_key().decode(), identity_key='synthetic-identity-key-' * 3,
        clients={'google_health': {'client_id': 'synthetic-google', 'client_secret': 'fake-secret', 'publishing_status': 'testing'},
                 'whoop': {'client_id': 'synthetic-whoop', 'client_secret': 'fake-secret', 'publishing_status': 'production'}}, **kwargs)


class EnrollmentProtocolTests(unittest.TestCase):
    def test_summary_cli_reads_counts_without_creating_an_invitation(self):
        from sentra.enrollment import main
        store = MagicMock()
        store.summary.return_value = {'enrolled': 1, 'assessable': None, 'assessment_unknown': 1}
        output = StringIO()
        with patch('sentra.enrollment.EnrollmentSettings.from_env', return_value=settings()), \
                patch('sentra.enrollment_store.open_store') as opened, redirect_stdout(output):
            opened.return_value.__enter__.return_value = store
            self.assertEqual(main(['--organization', 'synthetic-pilot', '--summary']), 0)
        self.assertEqual(json.loads(output.getvalue())['assessment_unknown'], 1)
        store.summary.assert_called_once_with('synthetic-pilot')
        store.invite.assert_not_called()

    def test_summary_stops_before_reading_credentials_when_organization_exceeds_pilot_bound(self):
        from sentra.enrollment_store import EnrollmentStore
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [('p100',)] * 101
        store = EnrollmentStore(db, settings())
        with patch.object(store, '_participation') as detail, self.assertRaises(EnrollmentError):
            store.summary('synthetic-pilot')
        detail.assert_not_called()
        db.execute.assert_called_once()

    def test_origin_and_keys_fail_closed(self):
        for origin in ('http://example.com', 'https://example.com/path', 'https://user@example.com', 'https://example.com?next=x'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                settings(origin=origin)
        with self.assertRaises(EnrollmentError):
            with patch.dict('os.environ', {'SENTRA_ENROLLMENT_CONFIG': 'invalid'}):
                EnrollmentSettings.from_env()

    def test_pkce_verifier_matches_challenge_and_never_enters_authorization_url(self):
        config = settings()
        url, pending = ProviderLogin(config).begin('google_health')
        query = parse_qs(urlsplit(url).query)
        expected = base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(query['code_challenge'], [expected])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(query['redirect_uri'], [config.callback('google_health')])
        self.assertEqual(query['state'], [pending['state']])
        self.assertNotIn(pending['verifier'], url)
        self.assertIn('openid', query['scope'][0].split())
        self.assertNotIn('email', query['scope'][0].split())

    def test_identity_is_stable_provider_separated_and_not_plaintext(self):
        config = settings()
        self.assertEqual(config.identity('whoop', '123'), config.identity('whoop', '123'))
        self.assertNotEqual(config.identity('google_health', '123'), config.identity('whoop', '123'))
        self.assertEqual(len(config.identity('whoop', '123')), 64)

    def test_token_exchange_identity_and_scope_validation(self):
        config = settings()
        login = ProviderLogin(config)
        _, pending = login.begin('whoop')
        token = {'access_token': 'fake-access', 'refresh_token': 'fake-refresh',
                 'token_type': 'Bearer', 'scope': scopes('whoop'), 'expires_in': 3600}
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({'user_id': 456, 'email': 'discard@example.invalid', 'first_name': 'Discard'}).encode()]
        with patch('sentra.enrollment.PrivateOAuthSession') as session, patch('sentra.enrollment.requests.get', return_value=response) as profile:
            session.return_value.fetch_token.return_value = token
            identity, saved = login.finish(pending, 'synthetic-code')
            self.assertEqual(identity, config.identity('whoop', '456'))
            self.assertNotIn('discard', json.dumps(saved).lower())
            self.assertFalse(profile.call_args.kwargs['allow_redirects'])
            self.assertIn('read:profile', scopes('whoop'))
            session.return_value.fetch_token.return_value = {**token, 'scope': ['offline']}
            with self.assertRaises(EnrollmentError) as error:
                login.finish(pending, 'synthetic-code')
            self.assertNotIn('fake-access', str(error.exception))

    def test_google_verifier_sent_only_to_token_endpoint(self):
        config = settings(); login = ProviderLogin(config)
        _, pending = login.begin('google_health')
        response = MagicMock(); response.__enter__.return_value = response
        response.status_code = 200; response.iter_content.return_value = [b'{"sub":"synthetic-sub"}']
        with patch('sentra.enrollment.PrivateOAuthSession') as session, patch('sentra.enrollment.requests.get', return_value=response):
            session.return_value.fetch_token.return_value = {'access_token': 'fake-access', 'refresh_token': 'fake-refresh',
                'token_type': 'Bearer', 'expires_in': 3600, 'scope': scopes('google_health')}
            _, saved = login.finish(pending, 'synthetic-code')
            self.assertEqual(session.return_value.fetch_token.call_args.kwargs['code_verifier'], pending['verifier'])
            self.assertGreater(saved['refresh_expires_at'], time.time() + 6 * 86400)

    def test_migration_parses_and_role_cannot_read_wearable_values(self):
        sql = Path('sql/008_self_service_enrollment.sql').read_text(encoding='utf-8')
        self.assertTrue(parse_sql(sql))
        self.assertNotIn('grant select on audit.measurements', sql.lower())
        self.assertNotIn('grant select on audit.records', sql.lower())


@unittest.skipUnless(HAS_API, 'install requirements-api.txt and httpx for enrollment HTTP tests')
class EnrollmentHttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.config = settings()
        self.repo = MagicMock()
        self.repo.start.return_value = ('synthetic-session', {})
        self.repo.status.return_value = {'csrf': 'synthetic-csrf', 'joining': True, 'signed_in': False, 'organization': 'Synthetic pilot'}
        @contextmanager
        def factory(config):
            yield self.repo
        self.client = TestClient(create_app(self.config, factory), base_url=self.config.origin)

    def test_cookie_csp_and_no_validation_echo(self):
        result = self.client.post('/api/session', json={'invite': 'x' * 43}, headers={'Origin': self.config.origin})
        self.assertEqual(result.status_code, 200)
        cookie = result.headers['set-cookie']
        for expected in ('__Host-sentra-participant=', 'HttpOnly', 'Secure', 'SameSite=lax', 'Path=/'):
            self.assertIn(expected, cookie)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", result.headers['content-security-policy'])
        bad = self.client.post('/api/session', json={'invite': 'private-invitation-' * 20}, headers={'Origin': self.config.origin})
        self.assertEqual(bad.status_code, 422)
        self.assertNotIn('private-invitation', bad.text)

    def test_cross_origin_wrong_host_and_large_body_rejected(self):
        self.assertEqual(self.client.post('/api/session', json={}, headers={'Origin': 'https://attacker.invalid'}).status_code, 403)
        self.assertEqual(self.client.get('/join', headers={'Host': 'attacker.invalid'}).status_code, 400)
        self.assertEqual(self.client.post('/api/session', content='x' * 9000, headers={'Origin': self.config.origin}).status_code, 413)
        self.repo.start.assert_not_called()

    def test_callback_query_pollution_rejected_before_exchange(self):
        for query in ('state=one&state=two&code=secret', 'code=secret'):
            result = self.client.get('/oauth/whoop/callback?' + query)
            self.assertEqual(result.status_code, 400)
            self.assertNotIn('secret', result.text)
        self.repo.consume.assert_not_called()

    def test_invalid_configuration_is_sanitized(self):
        with patch.dict('os.environ', {'SENTRA_ENROLLMENT_CONFIG': '{}'}):
            result = TestClient(create_app(), base_url=self.config.origin).get('/join')
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('Traceback', result.text)

    def test_static_page_does_not_read_database(self):
        page = self.client.get('/join')
        self.assertEqual(page.status_code, 200)
        self.assertIn('No new Sentra password', page.text)
        self.assertEqual(self.client.get('/assets/join.js').status_code, 200)
        self.repo.start.assert_not_called()
        self.repo.status.assert_not_called()


class MultiParticipantDirectoryTests(unittest.TestCase):
    def test_legacy_and_multiple_accounts_per_provider(self):
        self.assertEqual(configured_connections({'whoop': 'p02'}), [('p02', 'whoop')])
        self.assertEqual(configured_connections({'whoop': ['p02', 'p03'], 'google_health': ['p01']}),
            [('p02', 'whoop'), ('p03', 'whoop'), ('p01', 'google_health')])
        for value in ({}, {'whoop': ['p02', 'p02']}, {'whoop': ['alice']}, {'unknown': 'p01'}, {'whoop': []}):
            with self.subTest(value=value), self.assertRaises(Exception):
                configured_connections(value)

    def test_discovery_is_explicitly_opted_in_and_deduplicated(self):
        with patch.dict('os.environ', {'SENTRA_COLLECTOR_CONFIG': '{}'}), patch('sentra.cloud_run.SharedBackend') as backend:
            self.assertEqual(connection_targets({}, None, {'whoop': 'p02'}), [('p02', 'whoop')])
            backend.assert_not_called()
        with patch.dict('os.environ', {'SENTRA_COLLECTOR_CONFIG': '{"include_enrolled":true}'}), patch('sentra.cloud_run.SharedBackend') as backend:
            backend.return_value.db.execute.return_value.fetchall.return_value = [('p02', 'whoop'), ('p03', 'whoop')]
            self.assertEqual(connection_targets({}, None, {'whoop': 'p02'}), [('p02', 'whoop'), ('p03', 'whoop')])
            backend.return_value.guard.assert_called_once()
            backend.return_value.close.assert_called_once()
