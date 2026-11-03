"""Behaviour of sql/007_organization_access.sql on a real PostgreSQL server.

Opt-in like the live tests: set SENTRA_TEST_DATABASE_URL to an admin connection on a throwaway
PostgreSQL 15+ server (never the shared Supabase project). Each run creates and drops its own
database; the stand-in roles below are created on that server if missing.
"""
import os
from pathlib import Path
import unittest
from uuid import uuid4

URL = os.environ.get('SENTRA_TEST_DATABASE_URL')
ROLES = ('anon', 'authenticated', 'sentra_collector', 'sentra_viewer')


@unittest.skipUnless(URL, 'set SENTRA_TEST_DATABASE_URL to a throwaway PostgreSQL server to run')
class OrganizationAccessDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        import psycopg.rows
        from psycopg.conninfo import make_conninfo
        cls.psycopg = psycopg
        cls.name = 'sentra_test_' + uuid4().hex[:12]
        with psycopg.connect(URL, autocommit=True) as server:
            for role in ROLES:
                if not server.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                    server.execute(f'create role {role} nologin nosuperuser nobypassrls')
            server.execute(f'create database {cls.name}')
        cls.db = psycopg.connect(make_conninfo(URL, dbname=cls.name), autocommit=True)
        cls.db.execute("create schema audit; create table audit.participants(participant_id text primary key)")
        cls.db.execute("insert into audit.participants values ('p901'),('p902')")
        cls.db.execute(Path('sql/007_organization_access.sql').read_text(encoding='utf-8'))
        cls.db.execute("insert into org.organizations values ('org-a','A'),('org-b','B')")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with cls.psycopg.connect(URL, autocommit=True) as server:
            server.execute(f'drop database {cls.name}')

    def join(self, participant, org):
        return self.db.execute("insert into org.memberships(participant_id,org_id,joined_on) values (%s,%s,'2026-11-01') "
                               "returning membership_id", (participant, org)).fetchone()[0]

    def consent(self, membership, participant, org, sharing='group_only', withdrawn=False, at='2026-11-01'):
        return self.db.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version,sharing,"
                               "withdrawn,recorded_at) values (%s,%s,%s,'1.0',%s,%s,%s) returning consent_id",
                               (membership, participant, org, sharing, withdrawn, at)).fetchone()[0]

    def current(self, participant):
        with self.db.transaction():
            self.db.execute('set local role sentra_viewer')
            return self.db.execute('select org_id,sharing,withdrawn,membership_open from org.current_consent '
                                   'where participant_id=%s', (participant,)).fetchone()

    def rejected(self, sql, params=()):
        try:
            with self.db.transaction():
                self.db.execute(sql, params)
        except self.psycopg.Error:
            return True
        return False

    def test_withdrawal_cannot_be_deleted_or_rewritten_by_the_admin_path(self):
        a = self.join('p902', 'org-a')
        self.consent(a, 'p902', 'org-a', 'individual', at='2026-11-01')
        withdrawal = self.consent(a, 'p902', 'org-a', withdrawn=True, at='2026-11-02')
        self.assertTrue(self.rejected('delete from org.consents where consent_id=%s', (withdrawal,)))
        self.assertTrue(self.rejected("update org.consents set withdrawn=false where consent_id=%s", (withdrawal,)))
        self.assertTrue(self.rejected('truncate org.consents'))
        self.assertEqual(self.current('p902'), ('org-a', 'group_only', True, True))

    def test_move_to_another_organization_keeps_history_and_ends_old_access(self):
        a = self.join('p901', 'org-a')
        self.consent(a, 'p901', 'org-a', 'individual', at='2026-11-01')
        self.consent(a, 'p901', 'org-a', withdrawn=True, at='2026-11-02')
        self.assertTrue(self.rejected("insert into org.memberships(participant_id,org_id,joined_on) "
                                      "values ('p901','org-b','2026-11-03')"))  # one open episode at a time
        self.db.execute("update org.memberships set left_on='2026-11-02' where membership_id=%s", (a,))
        b = self.join('p901', 'org-b')
        self.consent(b, 'p901', 'org-b', 'individual', at='2026-11-03')
        history = self.db.execute("select org_id,sharing,withdrawn from org.consents where participant_id='p901' "
                                  'order by consent_id').fetchall()
        self.assertEqual(history, [('org-a', 'individual', False), ('org-a', 'group_only', True),
                                   ('org-b', 'individual', False)])
        self.assertEqual(self.current('p901'), ('org-b', 'individual', False, True))
        self.assertTrue(self.rejected("update org.memberships set org_id='org-b' where membership_id=%s", (a,)))
        self.assertTrue(self.rejected("update org.memberships set left_on=null where membership_id=%s", (a,)))
        self.assertTrue(self.rejected('insert into org.consents(membership_id,participant_id,org_id,consent_version) '
                                      "values (%s,'p901','org-b','1.0')", (a,)))  # consent must match its episode

    def test_access_decisions_from_rows_the_viewer_actually_reads(self):
        from sentra.access import resolve
        self.db.execute("insert into audit.participants values ('p903'),('p904')")
        self.db.execute("insert into org.org_users(org_id,email,role) values ('org-b','officer@b.test','officer')")
        shown, hidden = self.join('p903', 'org-b'), self.join('p904', 'org-b')
        self.consent(shown, 'p903', 'org-b', 'individual')
        self.consent(hidden, 'p904', 'org-b', 'individual', at='2026-11-01')
        self.consent(hidden, 'p904', 'org-b', withdrawn=True, at='2026-11-02')
        with self.db.transaction():
            self.db.execute('set local role sentra_viewer')
            cursor = self.db.cursor(row_factory=self.psycopg.rows.dict_row)
            users = cursor.execute('select org_id,email,role,active from org.org_users').fetchall()
            consents = cursor.execute('select participant_id,org_id,sharing,withdrawn,membership_open '
                                      'from org.current_consent').fetchall()
        access = resolve('officer@b.test', team_emails=[], org_users=users, consents=consents)
        self.assertTrue(access.can_view_individual('p903'))
        self.assertFalse(access.can_view_individual('p904'))
        self.assertEqual(access.group_contributors(['p903', 'p904']), {'p903'})

    def test_viewer_reads_only_and_other_roles_see_nothing(self):
        for statement in ("insert into org.organizations values ('evil','Evil')",
                          'delete from org.memberships', "update org.org_users set role='officer'"):
            with self.subTest(statement=statement):
                self.assertTrue(self.rejected('set local role sentra_viewer; ' + statement))
        for role in ('anon', 'authenticated', 'sentra_collector'):
            with self.subTest(role=role):
                self.assertTrue(self.rejected(f'set local role {role}; select * from org.consents'))


if __name__ == '__main__':
    unittest.main()
