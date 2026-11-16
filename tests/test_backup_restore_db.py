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

# The follow-up tables a backup carries, shaped as in sql/010 (#72), which also creates a role and functions.
FOLLOW_UPS = '''create table org.follow_ups (follow_up_id bigint generated always as identity primary key,
  org_id text not null references org.organizations, participant_id text references audit.participants,
  opened_by text not null, opened_at timestamptz not null default now());
create table org.follow_up_events (event_id bigint generated always as identity primary key,
  follow_up_id bigint not null references org.follow_ups, recorded_at timestamptz not null default now(),
  actor text not null, status text not null, assignee text not null, note text not null);'''


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
            db.execute(FOLLOW_UPS)
            return db, make_conninfo(URL, dbname=name)
        cls.source, info = database()
        cls.admin = psycopg.connect(info, autocommit=True)  # second session, as the admin role in production
        cls.target, _ = database()  # an empty, migrated replacement project
        cls.reader_info = info
        cls.database = staticmethod(database)
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
        fid = db.execute("insert into org.follow_ups(org_id,participant_id,opened_by) values ('org-a','p01','officer@example.org') "
                         "returning follow_up_id").fetchone()[0]
        for status in ('open', 'resolved'):
            db.execute("insert into org.follow_up_events(follow_up_id,actor,status,assignee,note) "
                       "values (%s,'officer@example.org',%s,'officer@example.org','Synthetic note')", (fid, status))
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
            self.assertEqual((result['tables']['org.follow_ups'], result['tables']['org.follow_up_events'],
                              result['not_installed']), (1, 2, []))
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
            # Follow-up history keeps its ids, and new events continue after them.
            event = self.target.execute("insert into org.follow_up_events(follow_up_id,actor,status,assignee,note) "
                                        "select follow_up_id,'officer@example.org','ongoing','officer@example.org','Synthetic' "
                                        "from org.follow_ups returning event_id").fetchone()[0]
            self.assertGreater(event, 2)
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


    def test_restore_keeps_an_exhausted_participant_sequence_recoverable(self):
        # sql/008 allows p9999 with MAXVALUE 9999: advancing past it must not roll the restore back.
        self.source.execute("insert into audit.participants values ('p9999')")
        try:
            target, _ = self.database()
            try:
                with tempfile.TemporaryDirectory() as folder:
                    reader = self.backup(folder, self.admin)
                    restored = m.restore_backup(reader, self.Backend(self.source), target, empty_audit=True)
                self.assertEqual(restored['status'], 'restored_and_verified')
                self.assertEqual(target.execute("select count(*) from audit.participants").fetchone()[0], 4)
                self.assertEqual(target.execute('select last_value,is_called from enrollment_private.participant_number').fetchone(),
                                 (9999, True))
                with self.assertRaises(self.psycopg.errors.SequenceGeneratorLimitExceeded):
                    target.execute("select nextval('enrollment_private.participant_number')")  # capacity, not recovery
            finally:
                target.close()
        finally:
            self.source.execute("delete from audit.participants where participant_id='p9999'")

    def allocators(self, db):
        """(last_value, is_called) of every sequence a restore moves: participant numbers and identities."""
        names = ['enrollment_private.participant_number'] + [
            db.execute('select pg_get_serial_sequence(%s,%s)', (table, column)).fetchone()[0]
            for table, column in sorted(m.IDENTITY_TABLES.items())]
        return {name: db.execute(f'select last_value,is_called from {name}').fetchone() for name in names}

    def test_failed_restore_leaves_every_allocator_where_it_was(self):
        # The allocators move as their tables land, before later tables are written and verified. If a
        # later step fails, they must roll back with the rows: both when they advance normally (p150)
        # and when they stop at the bound (p9999).
        for extra in (None, 'p9999'):
            with self.subTest(highest=extra or 'p150'):
                if extra:
                    self.source.execute('insert into audit.participants values (%s)', (extra,))
                try:
                    target, _ = self.database()
                    try:
                        # enrollment_private.identities is restored last, after every allocator has moved.
                        target.execute("""create function public.stop_restore() returns trigger language plpgsql
                            as $$ begin raise exception 'synthetic failure after the allocators moved'; end $$;
                            create trigger stop_restore before insert on enrollment_private.identities
                            for each row execute function public.stop_restore()""")
                        before = self.allocators(target)
                        with tempfile.TemporaryDirectory() as folder:
                            reader = self.backup(folder, self.admin)
                            with self.assertRaises(self.psycopg.errors.RaiseException):
                                m.restore_backup(reader, self.Backend(self.source), target, empty_audit=True)
                        self.assertEqual(target.execute('select count(*) from audit.participants').fetchone()[0], 0)
                        self.assertEqual(self.allocators(target), before)
                        # The next enrollment gets the target's own first number, not one past the failed archive.
                        self.assertEqual(target.execute("select nextval('enrollment_private.participant_number')").fetchone()[0], 100)
                    finally:
                        target.close()
                finally:
                    if extra:
                        self.source.execute('delete from audit.participants where participant_id=%s', (extra,))


if __name__ == '__main__':
    unittest.main()
