"""Full backup -> offline verify -> restore, including consent/enrollment tables, on real PostgreSQL.

Opt-in: set SENTRA_TEST_DATABASE_URL to an admin connection on a throwaway PostgreSQL 15+ server
(never the shared Supabase project). Each run creates and drops its own databases. Rows are synthetic.
"""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cryptography.fernet import Fernet

from sentra import shared_backup as m

URL = os.environ.get('SENTRA_TEST_DATABASE_URL')
ROLES = ('anon', 'authenticated', 'sentra_collector', 'sentra_viewer')
# The two enrollment tables a backup carries, as defined in sql/008 (which also creates roles and grants).
ENROLLMENT = '''create schema enrollment_private;
create sequence enrollment_private.participant_number start 100 maxvalue 9999 no cycle;
create table enrollment_private.invites (invite_hash text primary key, org_id text not null references org.organizations,
  remaining integer not null, expires_at timestamptz not null);
create table enrollment_private.identities (provider text not null, identity_hash text not null,
  participant_id text not null references audit.participants, primary key(provider,identity_hash));'''


@unittest.skipUnless(URL, 'set SENTRA_TEST_DATABASE_URL to a throwaway PostgreSQL server to run')
class BackupRestoreDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import make_conninfo
        cls.psycopg, cls.names = psycopg, []
        with psycopg.connect(URL, autocommit=True) as server:
            for role in ROLES:
                if not server.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                    server.execute(f'create role {role} nologin nosuperuser nobypassrls')

        def database():
            name = 'sentra_test_' + uuid4().hex[:12]
            with psycopg.connect(URL, autocommit=True) as server:
                server.execute(f'create database {name}')
            cls.names.append(name)
            db = psycopg.connect(make_conninfo(URL, dbname=name), autocommit=True)
            db.execute('create schema auth; create table auth.users(id uuid primary key)')
            db.execute(Path('sql/001_foundation.sql').read_text(encoding='utf-8'))
            db.execute(Path('sql/007_organization_access.sql').read_text(encoding='utf-8'))
            db.execute(ENROLLMENT)
            return db, make_conninfo(URL, dbname=name)
        cls.source, info = database()
        cls.admin = psycopg.connect(info, autocommit=True)  # second session, as the admin role in production
        cls.target, _ = database()  # an empty, migrated replacement project
        cls.reader_info = info
        db = cls.source
        db.execute("insert into audit.participants values ('p01'),('p02'),('p150')")
        db.execute("insert into org.organizations(org_id,display_name) values ('org-a','A')")
        db.execute("insert into org.org_users(org_id,email,role) values ('org-a','officer@example.org','officer')")
        for pid in ('p01', 'p02'):
            mid = db.execute("insert into org.memberships(participant_id,org_id,joined_on) values (%s,'org-a','2026-11-01') "
                             "returning membership_id", (pid,)).fetchone()[0]
            db.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version,sharing,recorded_at) "
                       "values (%s,%s,'org-a','1.0','group_only','2026-11-01')", (mid, pid))
        db.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version,withdrawn,recorded_at) "
                   "select membership_id,participant_id,org_id,'1.0',true,'2026-11-02' from org.memberships where participant_id='p02'")
        db.execute("insert into enrollment_private.identities values ('whoop',%s,'p01')", ('a' * 64,))
        db.execute("insert into audit.connection_state values ('p01','whoop','sleep','authorized',null,'[]','{}',now())")

    @classmethod
    def tearDownClass(cls):
        for db in (cls.source, cls.admin, cls.target):
            db.close()
        with cls.psycopg.connect(URL, autocommit=True) as server:
            for name in cls.names:
                server.execute(f'drop database {name}')

    class Backend:
        def __init__(self, db):
            self.db, self.guards, self.credentials = db, [], {'url': 'https://example.supabase.co'}
        def lock(self): pass
        def unlock(self): pass
        def guard(self, **additions): self.guards.append(additions)
        def reserve(self, amount): pass
        def reserve_external(self, amount): pass

    def backup(self, folder, admin_db):
        cipher = Fernet(Fernet.generate_key())
        root = Path(folder) / 'backups'
        root.mkdir()
        return m.BackupReader(m.make_backup(self.Backend(self.source), root, cipher, admin_db=admin_db), cipher)

    def test_full_backup_covers_consent_history_and_restores_into_an_empty_project(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.backup(folder, self.admin)
            result = m.verify_backup(reader)
            self.assertEqual((result['tables']['org.consents'], result['tables']['org.memberships'],
                              result['tables']['enrollment_private.identities'], result['not_covered']), (3, 2, 1, []))
            self.assertEqual(result['restore_estimate_bytes'],
                             int(sum(reader.info['table_bytes'].values()) * m.RESTORE_FACTOR) + 16_000_000)
            backend = self.Backend(self.source)
            restored = m.restore_backup(reader, backend, self.target, empty_audit=True)
            self.assertEqual(restored['status'], 'restored_and_verified')
            self.assertEqual(backend.guards[0]['database_add'], result['restore_estimate_bytes'])
            # Withdrawal survives, and new consent rows continue after the restored identity values.
            self.assertEqual(self.target.execute("select withdrawn from org.current_consent where participant_id='p02'").fetchone()[0], True)
            new = self.target.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version) "
                                      "select membership_id,participant_id,org_id,'1.0' from org.memberships where participant_id='p01' "
                                      "returning consent_id").fetchone()[0]
            self.assertGreater(new, 3)
            # New enrollments continue after the restored participant numbers (p150 restored).
            self.assertEqual(self.target.execute("select nextval('enrollment_private.participant_number')").fetchone()[0], 151)
            with self.assertRaises(m.SentraError):  # never over existing rows
                m.restore_backup(reader, self.Backend(self.source), self.target, empty_audit=True)

    def test_isolated_rehearsal_restores_every_table_beside_the_source(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.backup(folder, self.admin)
            restored = m.restore_backup(reader, self.Backend(self.source), self.admin)
            schema = restored['schema']
            self.assertEqual(self.admin.execute(f'select count(*) from {schema}.org__consents').fetchone()[0], 3)
            self.admin.execute(f'drop schema {schema} cascade')

    def test_full_backup_fails_closed_when_row_security_would_filter_the_admin(self):
        from psycopg.conninfo import make_conninfo
        role, password = 'sentra_test_backup_reader', uuid4().hex
        with self.psycopg.connect(URL, autocommit=True) as server:
            if not server.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                server.execute(f"create role {role} login nobypassrls password '{password}'")
            else:
                server.execute(f"alter role {role} password '{password}'")
        self.source.execute(f'grant usage on schema org,enrollment_private to {role}; '
                            f'grant select on all tables in schema org,enrollment_private to {role}')
        with self.psycopg.connect(make_conninfo(self.reader_info, user=role, password=password), autocommit=True) as limited:
            self.assertEqual(limited.execute('select count(*) from org.consents').fetchone()[0], 0)  # silently filtered
            with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(m.SentraError, 'row-level security'):
                self.backup(folder, limited)

    def test_audit_only_backup_says_what_it_does_not_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            result = m.verify_backup(self.backup(folder, None))
            self.assertEqual(set(result['not_covered']), set(m.PRIVATE_TABLES))
            self.assertNotIn('org.consents', result['tables'])


if __name__ == '__main__':
    unittest.main()
