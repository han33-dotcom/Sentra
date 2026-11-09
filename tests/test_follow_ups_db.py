"""Behaviour of sql/010_follow_ups.sql on a real PostgreSQL server (#31).

Opt-in: set SENTRA_TEST_DATABASE_URL to an admin connection on a throwaway PostgreSQL 15+ server
(never the shared Supabase project). Each run creates and drops its own database.
"""
import os
from pathlib import Path
import unittest
from uuid import uuid4

URL = os.environ.get('SENTRA_TEST_DATABASE_URL')
ROLES = ('anon', 'authenticated', 'sentra_collector', 'sentra_viewer')
OFFICER, REVIEWER, OTHER = 'officer@a.test', 'reviewer@a.test', 'officer@b.test'


@unittest.skipUnless(URL, 'set SENTRA_TEST_DATABASE_URL to a throwaway PostgreSQL server to run')
class FollowUpDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import make_conninfo
        cls.psycopg = psycopg
        cls.name = 'sentra_test_' + uuid4().hex[:12]
        with psycopg.connect(URL, autocommit=True) as server:
            for role in ROLES:
                if not server.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                    server.execute(f'create role {role} nologin nosuperuser nobypassrls')
            if server.execute("select 1 from pg_roles where rolname='sentra_followups'").fetchone():
                server.execute('drop role sentra_followups')  # created by the migration under test
            server.execute(f'create database {cls.name}')
        cls.db = psycopg.connect(make_conninfo(URL, dbname=cls.name), autocommit=True)
        cls.db.execute("create schema audit; create table audit.participants(participant_id text primary key)")
        cls.db.execute("insert into audit.participants values ('p901'),('p902'),('p903')")
        for name in ('007_organization_access.sql', '010_follow_ups.sql'):
            cls.db.execute(Path('sql', name).read_text(encoding='utf-8'))
        cls.db.execute("insert into org.organizations values ('org-a','A'),('org-b','B')")
        cls.db.execute("insert into org.org_users(org_id,email,role,active) values "
                       "('org-a',%s,'officer',true),('org-a',%s,'reviewer',true),('org-b',%s,'officer',true),"
                       "('org-a','former@a.test','officer',false)", (OFFICER, REVIEWER, OTHER))
        for pid, sharing in (('p901', 'individual'), ('p902', 'group_only')):
            m = cls.db.execute("insert into org.memberships(participant_id,org_id,joined_on) values (%s,'org-a',"
                               "'2026-11-01') returning membership_id", (pid,)).fetchone()[0]
            cls.db.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version,sharing) "
                           "values (%s,%s,'org-a','1.0',%s)", (m, pid, sharing))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with cls.psycopg.connect(URL, autocommit=True) as server:
            server.execute(f'drop database {cls.name}')
            server.execute('drop role if exists sentra_followups')

    def as_role(self, role, sql, params=()):
        with self.db.transaction():
            self.db.execute(f'set local role {role}')
            return self.db.execute(sql, params).fetchall()

    def open(self, actor=OFFICER, org='org-a', pid='p901', assignee=REVIEWER, note='Asked about sleep pattern.'):
        return self.as_role('sentra_followups', 'select org.open_follow_up(%s,%s,%s,%s,%s)',
                            (actor, org, pid, assignee, note))[0][0]

    def update(self, fid, status, actor=OFFICER, assignee=REVIEWER, note='Checked in.'):
        self.as_role('sentra_followups', 'select org.update_follow_up(%s,%s,%s,%s,%s)', (actor, fid, status, assignee, note))

    def refused(self, call, *args, **kwargs):
        try:
            call(*args, **kwargs)
        except self.psycopg.Error:
            return True
        return False

    def test_officer_records_assigns_and_tracks_history(self):
        fid = self.open()
        self.update(fid, 'ongoing', note='Agreed to review next week.')
        self.update(fid, 'resolved', assignee=OFFICER, note='Pattern back to usual.')
        history = self.as_role('sentra_viewer', 'select status,assignee,actor from org.follow_up_events '
                               'where follow_up_id=%s order by event_id', (fid,))
        self.assertEqual(history, [('open', REVIEWER, OFFICER), ('ongoing', REVIEWER, OFFICER), ('resolved', OFFICER, OFFICER)])

    def test_the_current_assignee_records_progress_on_their_own_follow_up(self):
        fid = self.open(assignee=REVIEWER)
        self.update(fid, 'ongoing', actor=REVIEWER, note='Talked it through.')          # reviewer, assigned
        other = self.open(assignee=OFFICER)
        self.assertTrue(self.refused(self.update, other, 'resolved', actor=REVIEWER))  # not their assignment
        self.assertTrue(self.refused(self.open, actor=REVIEWER))                       # reviewers never open

    def test_group_follow_up_needs_no_participant(self):
        fid = self.open(pid=None, note='Several people reported short sleep after night shifts.')
        self.assertEqual(self.as_role('sentra_viewer', 'select participant_id from org.follow_ups where follow_up_id=%s',
                                      (fid,)), [(None,)])

    def test_only_active_officers_of_the_organization_can_write(self):
        self.assertTrue(self.refused(self.open, actor=REVIEWER))           # reviewers are assigned, not authors
        self.assertTrue(self.refused(self.open, actor='former@a.test'))    # inactive
        self.assertTrue(self.refused(self.open, actor=OTHER))              # another organization
        self.assertTrue(self.refused(self.open, assignee=OTHER))           # assignee outside the organization
        self.assertTrue(self.refused(self.open, note='   '))
        self.assertTrue(self.refused(self.open, note='x' * 501))

    def test_notes_need_individual_sharing_and_stop_after_withdrawal(self):
        self.assertTrue(self.refused(self.open, pid='p902'))   # group_only
        self.assertTrue(self.refused(self.open, pid='p903'))   # not enrolled
        fid = self.open(pid='p901')
        m = self.db.execute("select membership_id from org.memberships where participant_id='p901'").fetchone()[0]
        self.db.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version,sharing,withdrawn,"
                        "recorded_at) values (%s,'p901','org-a','1.0','group_only',true,now()+interval '1 second')", (m,))
        try:
            self.assertTrue(self.refused(self.update, fid, 'ongoing'))
        finally:  # restore individual sharing for the other tests
            self.db.execute("insert into org.consents(membership_id,participant_id,org_id,consent_version,sharing,"
                            "recorded_at) values (%s,'p901','org-a','1.0','individual',now()+interval '2 seconds')", (m,))

    def test_concurrent_writes_follow_the_serialized_event_order(self):
        from psycopg.conninfo import make_conninfo
        fid = self.open(assignee=OFFICER)
        a = self.psycopg.connect(make_conninfo(URL, dbname=self.name))       # transaction A starts first
        b = self.psycopg.connect(make_conninfo(URL, dbname=self.name), autocommit=True)
        self.addCleanup(a.close); self.addCleanup(b.close)
        a.execute('set role sentra_followups'); a.execute('select 1')        # A's now() is fixed here
        b.execute('set role sentra_followups')
        b.execute('select org.update_follow_up(%s,%s,%s,%s,%s)', (OFFICER, fid, 'ongoing', REVIEWER, 'To reviewer.'))
        a.execute('select org.update_follow_up(%s,%s,%s,%s,%s)', (OFFICER, fid, 'resolved', OFFICER, 'Back to officer.'))
        a.commit()
        reader, _ = self.reader()
        current = {r['follow_up_id']: r for r in reader.follow_up_rows('org-a', ['p901'])[0]}[fid]
        self.assertEqual((current['status'], current['assignee']), ('resolved', OFFICER))  # A wrote last
        # The reviewer lost the assignment when A committed, despite A's earlier recorded_at.
        self.assertTrue(self.refused(self.update, fid, 'ongoing', actor=REVIEWER, assignee=REVIEWER))

    def reader(self):
        from unittest.mock import Mock
        from psycopg.conninfo import make_conninfo
        from sentra.shared import Limits
        from sentra.viewer_reader import ViewerReader
        db = self.psycopg.connect(make_conninfo(URL, dbname=self.name), autocommit=True)
        db.execute('set role sentra_viewer')
        self.addCleanup(db.close)
        budget = Mock()
        return ViewerReader({}, Limits(), lambda: 'officer@a.test', db=db, budget_db=budget), budget

    def test_reader_scopes_before_the_page_limit_and_reports_the_latest_state(self):
        mine = self.open(pid=None, note='Group check-in planned.')
        for i in range(60):  # newer records in another organization exceed the page size
            self.open(actor=OTHER, org='org-b', pid=None, assignee=OTHER, note=f'b{i}')
        for i in range(12):  # history longer than the page shows, then a final resolution
            self.update(mine, 'ongoing', note=f'step {i}')
        self.update(mine, 'resolved', note='Closed after review.')
        reader, budget = self.reader()
        rows, events = reader.follow_up_rows('org-a', ['p901'])
        found = {r['follow_up_id']: r for r in rows}
        self.assertIn(mine, found)
        self.assertTrue(all(r['org_id'] == 'org-a' for r in rows))
        self.assertEqual((found[mine]['status'], found[mine]['note'], found[mine]['event_count']),
                         ('resolved', 'Closed after review.', 14))
        trail = [e for e in events if e['follow_up_id'] == mine]
        self.assertEqual((len(trail), trail[-1]['status']), (reader.FOLLOW_UP_HISTORY, 'resolved'))
        reserved = [c.args[1][0] for c in budget.execute.call_args_list]
        self.assertGreaterEqual(reserved[1], reader.FOLLOW_UP_PAGE * reader.FOLLOW_UP_HISTORY * 2_000)  # 500 4-byte chars
        self.assertEqual(len(reader.follow_up_rows()[0]), reader.FOLLOW_UP_PAGE)  # team: all, still bounded

    def test_history_is_append_only_and_roles_stay_narrow(self):
        fid = self.open()
        for sql in ('update org.follow_up_events set note=%s where follow_up_id=%s',
                    'delete from org.follow_up_events where follow_up_id=%s and %s is not null'):
            with self.subTest(sql=sql):
                self.assertTrue(self.refused(self.db.execute, sql, ('changed', fid)))   # even the admin path
        self.assertTrue(self.refused(self.db.execute, 'truncate org.follow_up_events'))
        self.assertTrue(self.refused(self.as_role, 'sentra_viewer', 'select org.open_follow_up(%s,%s,%s,%s,%s)',
                                     (OFFICER, 'org-a', 'p901', REVIEWER, 'x')))        # viewer stays read-only
        self.assertTrue(self.refused(self.as_role, 'sentra_viewer', "insert into org.follow_ups(org_id,opened_by) "
                                     "values ('org-a',%s)", (OFFICER,)))
        self.assertTrue(self.refused(self.as_role, 'sentra_followups', 'select * from org.follow_up_events'))
        self.assertTrue(self.refused(self.as_role, 'sentra_followups', "insert into org.follow_ups(org_id,opened_by) "
                                     "values ('org-a',%s)", (OFFICER,)))


if __name__ == '__main__':
    unittest.main()
