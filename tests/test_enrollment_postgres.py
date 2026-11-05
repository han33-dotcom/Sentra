"""Real PostgreSQL transactions + HTTP, using only a disposable local database.

Set SENTRA_TEST_ENROLLMENT_DSN to a loopback PostgreSQL admin DSN. This fixture
creates its own database and Supabase stand-ins; it never opens the project DB.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import os
from pathlib import Path
import re
import secrets
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from sentra.auth import token_state
from sentra.cloud_tokens import CloudTokenVault, TokenRepository
from sentra.daily_plan import day_jobs
from sentra.enrollment import EnrollmentError, ProviderLogin, digest
from sentra.enrollment_store import EnrollmentStore, open_store
from sentra.transport import ReadClient
from test_enrollment import settings, HAS_API

if HAS_API:
    from fastapi.testclient import TestClient
    from sentra.enrollment_web import create_app

DSN = os.environ.get('SENTRA_TEST_ENROLLMENT_DSN')


class SyntheticLogin(ProviderLogin):
    exchanges = 0

    def begin(self, provider):
        state = secrets.token_urlsafe(32)
        return 'https://synthetic.invalid/authorize?state=' + state, {'state': state, 'provider': provider, 'started': time.time()}

    def finish(self, pending, code):
        self.exchanges += 1
        if code == 'fail':
            raise EnrollmentError('Synthetic exchange failure')
        return self.settings.identity(pending['provider'], code), token_state({
            'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'expires_in': 3600})


@unittest.skipUnless(DSN and HAS_API, 'isolated PostgreSQL enrollment tests not opted in or API dependencies absent')
class EnrollmentPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = conninfo_to_dict(DSN)
        if config.get('host') not in ('127.0.0.1', 'localhost'):
            raise RuntimeError('Enrollment test DSN must point to a disposable loopback server.')
        cls.database = 'sentra_enrollment_test_' + uuid4().hex[:12]
        cls.admin = psycopg.connect(DSN, autocommit=True)
        cls.admin.execute(sql.SQL('create database {}').format(sql.Identifier(cls.database)))
        cls.admin_config = {**config, 'dbname': cls.database}
        with psycopg.connect(**cls.admin_config, autocommit=True) as db:
            for role in ('anon', 'authenticated'):
                if not db.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                    db.execute(sql.SQL('create role {}').format(sql.Identifier(role)))
            db.execute('''create schema auth; create table auth.users(id uuid primary key);
                create function auth.uid() returns uuid language sql as $$select null::uuid$$;
                create schema storage;
                create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
                create table storage.objects(bucket_id text,metadata jsonb);''')
            for filename in ('001_foundation.sql', '002_permissions.sql', '003_numeric_precision.sql',
                    '004_daily_collection.sql', '005_viewer_status.sql', '006_parquet_tiers.sql',
                    '007_organization_access.sql', '008_self_service_enrollment.sql'):
                migration = Path('sql', filename).read_text(encoding='utf-8')
                # Fixture roles are cluster-wide; grants remain scoped to this new database.
                migration = re.sub(r'create role (sentra_[a-z]+) login[^;]+;',
                    lambda m: f"do $role$ begin if not exists(select 1 from pg_roles where rolname='{m[1]}') then {m[0]} end if; end $role$;", migration)
                db.execute(migration)
            db.execute("insert into collector_private.egress_budget values(date_trunc('month',now())::date,0,0,now())")
        cls.config = settings(origin='http://127.0.0.1:8819', db={**cls.admin_config, 'user': 'sentra_enrollment'})
        cls.login = SyntheticLogin(cls.config)
        cls.app = create_app(cls.config, provider_login=cls.login)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'admin'):
            cls.admin.execute(sql.SQL('drop database {} with (force)').format(sql.Identifier(cls.database)))
            cls.admin.close()

    def setUp(self):
        self.org = 'pilot-' + uuid4().hex[:12]
        self.code = 'synthetic-' + uuid4().hex
        self.client = self.browser()
        self.headers = {'Origin': self.config.origin}
        with self.admin_db() as db:
            db.execute('delete from enrollment_private.rate_limits')
            db.execute('insert into org.organizations(org_id,display_name) values(%s,%s)', (self.org, 'Synthetic pilot'))
        self.invite = self.new_invite(self.org)

    def browser(self):
        return TestClient(self.app, base_url=self.config.origin, follow_redirects=False)

    @contextmanager
    def admin_db(self):
        with psycopg.connect(**self.admin_config, autocommit=True) as db:
            yield db

    def new_invite(self, org, seats=5):
        token = secrets.token_urlsafe(32)
        with open_store(self.config) as store:
            store.invite(digest(token), org, seats, 7)
        return token

    def start(self, client=None, invite=None):
        client = client or self.client
        response = client.post('/api/session', json={'invite': invite} if invite else {}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pending(self, client, state, provider='whoop'):
        response = client.post('/api/connect', json={'provider': provider, 'sharing': 'group_only',
            'demonstration': False, 'accepted': True}, headers={**self.headers, 'X-CSRF-Token': state['csrf']})
        self.assertEqual(response.status_code, 200, response.text)
        return parse_qs(urlsplit(response.json()['url']).query)['state'][0]

    def complete(self, client=None, invite=None, code=None, provider='whoop'):
        client = client or self.client
        state = self.start(client, invite)
        pending = self.pending(client, state, provider)
        response = client.get(f'/oauth/{provider}/callback', params={'state': pending, 'code': code or self.code})
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers['location'], '/account', response.text)
        return client.get('/api/status').json()

    def test_signup_is_atomic_cookie_rotated_credentials_encrypted_and_collection_paused(self):
        first = self.start(self.client, self.invite)
        old_cookie = self.client.cookies.get(self.config.cookie)
        with self.admin_db() as db:
            self.assertFalse(db.execute('select 1 from org.memberships where org_id=%s', (self.org,)).fetchone())
        pending = self.pending(self.client, first)
        response = self.client.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code})
        self.assertEqual(response.headers['location'], '/account')
        self.assertNotEqual(self.client.cookies.get(self.config.cookie), old_cookie)
        status = self.client.get('/api/status').json()
        self.assertTrue(status['enrolled']); self.assertTrue(status['connected'])
        self.assertFalse(status['recently_contributing']); self.assertIsNone(status['assessable'])
        self.assertTrue(status['collection_paused']); self.assertEqual(status['assessment'], 'not_available')
        self.assertNotIn('fake-access', json.dumps(status))
        with self.admin_db() as db:
            blob = bytes(db.execute('select encrypted_token_bundle from collector_private.provider_credentials where participant_id=%s', (status['participant_id'],)).fetchone()[0])
            self.assertNotIn(b'fake-access', blob)
            self.assertIn(b'fake-access', self.config.cipher.decrypt(blob))
            self.assertEqual(db.execute('select remaining from enrollment_private.invites where invite_hash=%s', (digest(self.invite),)).fetchone()[0], 4)
            self.assertFalse(db.execute('select 1 from enrollment_private.sessions where session_hash=%s', (digest(old_cookie),)).fetchone())

    def test_returning_provider_login_uses_same_participant_without_new_seat_or_consent(self):
        original = self.complete(invite=self.invite)
        with self.admin_db() as db:
            before = db.execute('select count(*) from org.consents where participant_id=%s', (original['participant_id'],)).fetchone()[0]
        returning = self.complete(self.browser())
        self.assertEqual(returning['participant_id'], original['participant_id'])
        with self.admin_db() as db:
            self.assertEqual(db.execute('select count(*) from org.consents where participant_id=%s', (original['participant_id'],)).fetchone()[0], before)

    def test_state_wrong_provider_expiry_and_replay_do_not_exchange(self):
        value = self.start(self.client, self.invite); pending = self.pending(self.client, value)
        before = self.login.exchanges
        for provider, state in (('whoop', 'wrong'), ('google_health', pending)):
            self.assertEqual(self.client.get(f'/oauth/{provider}/callback', params={'state': state, 'code': self.code}).status_code, 400)
        self.assertEqual(self.login.exchanges, before)
        self.assertEqual(self.client.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code}).headers['location'], '/account')
        self.assertEqual(self.client.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code}).status_code, 400)
        self.assertEqual(self.login.exchanges, before + 1)
        other = self.browser(); value = self.start(other, self.invite); pending = self.pending(other, value)
        with open_store(self.config) as store:
            sid = other.cookies.get(self.config.cookie); saved = store.session(sid)
            saved['pending']['started'] -= 601; store._save(sid, saved)
        self.assertEqual(other.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code}).status_code, 400)

    def test_cancel_and_failed_exchange_leave_no_membership_and_can_retry(self):
        state = self.start(self.client, self.invite); pending = self.pending(self.client, state)
        response = self.client.get('/oauth/whoop/callback', params={'state': pending, 'error': 'private-provider-error'})
        self.assertEqual(response.headers['location'], '/join?connection=cancelled')
        pending = self.pending(self.client, state)
        response = self.client.get('/oauth/whoop/callback', params={'state': pending, 'code': 'fail'})
        self.assertEqual(response.headers['location'], '/join?connection=failed')
        with self.admin_db() as db:
            self.assertEqual(db.execute('select count(*) from org.memberships where org_id=%s', (self.org,)).fetchone()[0], 0)
        self.complete(invite=self.invite)

    def test_cross_organization_and_unknown_account_login_do_not_create_memberships(self):
        initial = self.complete(invite=self.invite)
        with self.admin_db() as db:
            db.execute('insert into org.organizations(org_id,display_name) values(%s,%s)', (self.org + '-other', 'Other synthetic pilot'))
        invite = self.new_invite(self.org + '-other')
        client = self.browser(); state = self.start(client, invite); pending = self.pending(client, state)
        self.assertEqual(client.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code}).headers['location'], '/join?connection=failed')
        unknown = self.browser(); state = self.start(unknown); pending = self.pending(unknown, state)
        self.assertEqual(unknown.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code + 'unknown'}).headers['location'], '/join?connection=failed')
        self.assertEqual(self.client.get('/api/status').json()['participant_id'], initial['participant_id'])

    def test_invitation_seat_race_does_not_leave_partial_enrollment(self):
        invite = self.new_invite(self.org, 1)
        a, b = self.browser(), self.browser()
        sa, sb = self.start(a, invite), self.start(b, invite)
        pa, pb = self.pending(a, sa), self.pending(b, sb)
        a.get('/oauth/whoop/callback', params={'state': pa, 'code': self.code})
        self.assertEqual(b.get('/oauth/whoop/callback', params={'state': pb, 'code': self.code + '-other'}).headers['location'], '/join?connection=failed')
        with self.admin_db() as db:
            self.assertEqual(db.execute('select count(*) from org.memberships where org_id=%s', (self.org,)).fetchone()[0], 1)

    def test_duplicate_identity_callbacks_in_parallel_use_one_participant(self):
        a, b = self.browser(), self.browser()
        sa, sb = self.start(a, self.invite), self.start(b, self.invite)
        pa, pb = self.pending(a, sa), self.pending(b, sb)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda item: item[0].get('/oauth/whoop/callback', params={'state': item[1], 'code': self.code}), [(a, pa), (b, pb)]))
        self.assertTrue(all(r.headers.get('location') == '/account' for r in results))
        self.assertEqual(a.get('/api/status').json()['participant_id'], b.get('/api/status').json()['participant_id'])
        with self.admin_db() as db:
            self.assertEqual(db.execute('select count(*) from org.memberships where org_id=%s', (self.org,)).fetchone()[0], 1)
            self.assertEqual(db.execute('select remaining from enrollment_private.invites where invite_hash=%s', (digest(self.invite),)).fetchone()[0], 4)

    def test_changes_append_history_csrf_required_and_withdrawal_stops_retry(self):
        status = self.complete(invite=self.invite)
        headers = {**self.headers, 'X-CSRF-Token': status['csrf']}
        choice = {'sharing': 'individual', 'demonstration': True, 'accepted': True}
        self.assertEqual(self.client.post('/api/choices', json=choice, headers=self.headers).status_code, 403)
        self.assertEqual(self.client.post('/api/choices', json=choice, headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/status').json()['sharing'], 'individual')
        with psycopg.connect(**{**self.admin_config, 'user': 'sentra_collector'}, autocommit=True) as db:
            vault = CloudTokenVault(TokenRepository(db), status['participant_id'], 'whoop', self.config.cipher)
            response = MagicMock(); response.__enter__.return_value = response
            response.status_code = 500; response.headers = {}
            def withdraw(_):
                self.assertEqual(self.client.post('/api/withdraw', json={}, headers=headers).status_code, 200)
            read = ReadClient(lambda: 'fake-access', pace=0, pause=withdraw, guard=vault.ensure_active)
            with patch('sentra.transport.requests.request', return_value=response) as request, self.assertRaisesRegex(Exception, 'withdrawn'):
                read.fetch(day_jobs('whoop', date(2026, 10, 1))[0], '')
            self.assertEqual(request.call_count, 1)
            self.assertNotIn((status['participant_id'], 'whoop'), db.execute('select * from collector_private.enrolled_connections()').fetchall())
        withdrawn = self.client.get('/api/status').json()
        self.assertFalse(withdrawn['enrolled']); self.assertFalse(withdrawn['connected'])
        self.assertEqual(self.client.post('/api/withdraw', json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/api/choices', json=choice, headers=headers).status_code, 409)
        with self.admin_db() as db:
            self.assertEqual(db.execute('select count(*) from org.consents where participant_id=%s', (status['participant_id'],)).fetchone()[0], 3)

    def test_operator_summary_is_bounded_scoped_and_does_not_treat_unknown_as_assessable(self):
        person = self.complete(invite=self.invite)
        with open_store(self.config) as store:
            summary = store.summary(self.org)
            self.assertEqual(summary, dict(enrolled=1, connected=1, recently_contributing=0,
                assessable=None, assessment_unknown=1, withdrawn=0))
            self.assertNotIn(person['participant_id'], json.dumps(summary))
            self.assertEqual(store.summary('different-organization')['enrolled'], 0)
        headers = {**self.headers, 'X-CSRF-Token': person['csrf']}
        self.assertEqual(self.client.post('/api/withdraw', json={}, headers=headers).status_code, 200)
        with self.admin_db() as db:
            before = db.execute('select count(*) from org.consents').fetchone()[0]
        with open_store(self.config) as store:
            summary = store.summary(self.org)
            self.assertEqual(summary, dict(enrolled=0, connected=0, recently_contributing=0,
                assessable=0, assessment_unknown=0, withdrawn=1))
        with self.admin_db() as db:
            self.assertEqual(db.execute('select count(*) from org.consents').fetchone()[0], before)

    def test_add_second_provider_and_reject_someone_elses_existing_identity(self):
        status = self.complete(invite=self.invite)
        pending = self.pending(self.client, status, 'google_health')
        self.assertEqual(self.client.get('/oauth/google_health/callback', params={'state': pending, 'code': self.code}).headers['location'], '/account')
        self.assertEqual(set(self.client.get('/api/status').json()['providers']), {'google_health', 'whoop'})
        other = self.browser(); different = self.complete(other, self.invite, self.code + '-other')
        pending = self.pending(other, different)
        self.assertEqual(other.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code}).headers['location'], '/join?connection=failed')
        self.assertEqual(other.get('/api/status').json()['participant_id'], different['participant_id'])

    def test_logout_and_expiry_remove_management_access(self):
        status = self.complete(invite=self.invite)
        self.assertEqual(self.client.post('/api/logout', json={}, headers={**self.headers, 'X-CSRF-Token': status['csrf']}).status_code, 200)
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        other = self.browser(); self.start(other, self.invite)
        with self.admin_db() as db:
            db.execute("update enrollment_private.sessions set expires_at=now()-interval '1 second' where session_hash=%s", (digest(other.cookies.get(self.config.cookie)),))
        self.assertEqual(other.get('/api/status').status_code, 401)

    def test_runtime_roles_and_immutable_consent(self):
        self.complete(invite=self.invite)
        for query in ('select * from audit.measurements', 'select * from audit.records', 'delete from org.consents',
                      'update org.org_users set active=false', 'select * from collector_private.observation_control'):
            with psycopg.connect(**{**self.admin_config, 'user': 'sentra_enrollment'}, autocommit=True) as db:
                with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute(query)
        with self.admin_db() as db:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute('update org.consents set demonstration=false where org_id=%s', (self.org,))
        for role in ('anon', 'authenticated', 'sentra_viewer'):
            with self.admin_db() as db:
                db.execute(sql.SQL('set role {}').format(sql.Identifier(role)))
                with self.subTest(role=role), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute('select * from enrollment_private.sessions')

    def test_invitation_expiring_during_authorization_rolls_back_enrollment(self):
        first = self.start(self.client, self.invite); pending = self.pending(self.client, first)
        with self.admin_db() as db:
            db.execute("update enrollment_private.invites set expires_at=now()-interval '1 second' where invite_hash=%s", (digest(self.invite),))
        result = self.client.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code})
        self.assertEqual(result.headers['location'], '/join?connection=failed')
        with self.admin_db() as db:
            self.assertFalse(db.execute('select 1 from org.memberships where org_id=%s', (self.org,)).fetchone())

    def test_new_attempt_supersedes_a_callback_already_exchanging(self):
        state = self.start(self.client, self.invite)
        first = self.pending(self.client, state)
        sid = self.client.cookies.get(self.config.cookie)
        with open_store(self.config) as store:
            pending = store.consume(sid, 'whoop', first)
        second = self.pending(self.client, state)
        identity, token = self.login.finish(pending, self.code)
        with open_store(self.config) as store:
            with self.assertRaises(EnrollmentError):
                store.finish(sid, pending, identity, token, self.login)
        response = self.client.get('/oauth/whoop/callback', params={'state': second, 'code': self.code})
        self.assertEqual(response.headers['location'], '/account')

    def test_pending_old_invitation_and_returning_login_cannot_undo_withdrawal(self):
        enrolled = self.complete(invite=self.invite)
        stale = self.browser(); first = self.start(stale, self.invite); pending = self.pending(stale, first)
        result = self.client.post('/api/withdraw', json={}, headers={**self.headers, 'X-CSRF-Token': enrolled['csrf']})
        self.assertEqual(result.status_code, 200)
        result = stale.get('/oauth/whoop/callback', params={'state': pending, 'code': self.code})
        self.assertEqual(result.headers['location'], '/join?connection=failed')
        returning = self.complete(self.browser())
        self.assertFalse(returning['enrolled']); self.assertFalse(returning['connected'])
        # A new, explicit join after withdrawal can enroll again under a new episode.
        rejoined = self.complete(self.browser(), self.invite)
        self.assertTrue(rejoined['enrolled']); self.assertEqual(rejoined['participant_id'], enrolled['participant_id'])

    def test_recency_uses_usable_measurement_dates_not_fetch_dates_and_expiry_requires_reconnect(self):
        enrolled = self.complete(invite=self.invite); pid = enrolled['participant_id']
        with self.admin_db() as db:
            response_id = digest('response-' + pid)
            db.execute('''insert into audit.raw_response_manifest values(%s,%s,'whoop','sleep','synthetic','{}','synthetic',
                now(),'synthetic',%s,0,'{}')''', (response_id, pid, response_id))
            db.execute("insert into audit.records values(%s,'whoop','sleep','synthetic',%s,'{}',%s,now())", (pid, response_id, response_id))
            db.execute('''insert into audit.measurements values(%s,'whoop','sleep','synthetic','synthetic',null,'synthetic',
                'null','synthetic','measurement','missing',null,null,null,
                to_jsonb((now() at time zone 'Asia/Beirut')::date::text),'vendor_civil_date','{}',now(),null,'synthetic',%s,'/synthetic')''', (pid, response_id))
        self.assertFalse(self.client.get('/api/status').json()['recently_contributing'])
        with self.admin_db() as db:
            db.execute("update audit.measurements set value=1,availability='available' where participant_id=%s", (pid,))
        status = self.client.get('/api/status').json()
        self.assertTrue(status['recently_contributing']); self.assertIsNone(status['assessable'])
        with self.admin_db() as db:
            db.execute("update audit.measurements set civil_date='\"2020-01-01\"' where participant_id=%s", (pid,))
            row = db.execute('select encrypted_token_bundle from collector_private.provider_credentials where participant_id=%s', (pid,)).fetchone()
            body = json.loads(self.config.cipher.decrypt(bytes(row[0])))
            body['token']['refresh_expires_at'] = 1
            db.execute('update collector_private.provider_credentials set encrypted_token_bundle=%s where participant_id=%s',
                (self.config.cipher.encrypt(json.dumps(body).encode()), pid))
        status = self.client.get('/api/status').json()
        self.assertFalse(status['recently_contributing']); self.assertFalse(status['connected'])
        self.assertEqual(status['providers']['whoop'], 'reconnect_required')

    def test_same_browser_csrf_does_not_authorize_another_session_and_rate_is_bounded(self):
        first = self.complete(invite=self.invite)
        other = self.browser(); second = self.complete(other, self.invite, self.code + '-other')
        result = other.post('/api/withdraw', json={}, headers={**self.headers, 'X-CSRF-Token': first['csrf']})
        self.assertEqual(result.status_code, 403)
        self.assertTrue(other.get('/api/status').json()['enrolled'])
        with self.admin_db() as db:
            db.execute('delete from enrollment_private.rate_limits')
        for _ in range(20):
            self.assertEqual(other.post('/api/session', json={}, headers=self.headers).status_code, 200)
        self.assertEqual(other.post('/api/session', json={}, headers=self.headers).status_code, 429)
