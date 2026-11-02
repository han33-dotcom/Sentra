"""Static checks for sql/007_organization_access.sql (organization access and consent schema)."""
from pathlib import Path
import re
import unittest

from pglast import ast, parse_sql

PATH = Path('sql/007_organization_access.sql')
TABLES = {'organizations', 'org_users', 'memberships', 'consents'}
EXCLUDED = re.compile(r'(location|latitude|longitude|gps|route|address|phone|name$|password|token|secret)')


def statements(text):
    return [raw.stmt for raw in parse_sql(text)]


def tables(text):
    return {s.relation.relname: s for s in statements(text)
            if isinstance(s, ast.CreateStmt) and s.relation.schemaname == 'org'}


def columns(stmt):
    return {e.colname: e for e in stmt.tableElts if isinstance(e, ast.ColumnDef)}


class OrganizationAccessMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATH.read_text(encoding='utf-8')
        cls.lower = cls.text.lower()

    def test_parses_as_one_transaction(self):
        parsed = statements(self.text)
        self.assertIsInstance(parsed[0], ast.TransactionStmt)
        self.assertIsInstance(parsed[-1], ast.TransactionStmt)
        self.assertEqual(set(tables(self.text)), TABLES)

    def test_no_destructive_statements(self):
        for keyword in ('drop ', 'truncate ', 'delete from', 'alter table audit.', 'update '):
            self.assertNotIn(keyword, self.lower)

    def test_rls_is_forced_on_every_org_table(self):
        self.assertIn("schemaname='org'", self.text)
        for clause in ('enable row level security', 'force row level security',
                       'revoke all on org.%I from public,anon,authenticated,sentra_collector'):
            self.assertIn(clause, self.text)

    def test_viewer_gets_read_only_access_and_nobody_else_gets_any(self):
        grants = [s for s in statements(self.text) if isinstance(s, ast.GrantStmt) and s.is_grant]
        self.assertTrue(grants)
        for grant in grants:
            grantees = {g.rolename for g in grant.grantees}
            self.assertEqual(grantees, {'sentra_viewer'})
            privileges = {p.priv_name for p in grant.privileges or ()}
            self.assertLessEqual(privileges, {'select', 'usage'})
        self.assertNotIn('for insert', self.lower)
        self.assertNotIn('for update', self.lower)
        self.assertNotIn('for delete', self.lower)
        self.assertNotIn('for all', self.lower)

    def test_sharing_defaults_to_group_only(self):
        consent = columns(tables(self.text)['consents'])
        self.assertIn('sharing', consent)
        self.assertIn("default 'group_only' check (sharing in ('group_only','individual'))", self.text)
        self.assertIn('demonstration boolean not null default false', self.text)

    def test_consent_history_is_append_only_and_latest_row_wins(self):
        self.assertIn('generated always as identity', self.text)
        self.assertIn('withdrawn boolean not null default false', self.text)
        self.assertIn('with (security_invoker=true)', self.text)
        self.assertIn('distinct on (participant_id)', self.text)
        self.assertIn('order by participant_id,recorded_at desc,consent_id desc', self.text)

    def test_participants_link_to_existing_pseudonyms_only(self):
        self.assertIn('participant_id text primary key references audit.participants', self.text)
        self.assertIn('references org.memberships(participant_id,org_id)', self.text)

    def test_roles_are_limited(self):
        self.assertIn("role in ('officer','reviewer')", self.text)
        self.assertIn('email = lower(email)', self.text)

    def test_no_location_identity_or_credential_columns(self):
        for name, stmt in tables(self.text).items():
            for column in columns(stmt).keys() - {'display_name'} if name == 'organizations' else columns(stmt):
                with self.subTest(table=name, column=column):
                    self.assertIsNone(EXCLUDED.search(column))


if __name__ == '__main__':
    unittest.main()
