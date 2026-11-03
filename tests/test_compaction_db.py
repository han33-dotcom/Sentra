"""Lossless compaction (sql/009_compact_series.sql, sentra.compaction) on a real PostgreSQL server.

Opt-in: set SENTRA_TEST_DATABASE_URL to an admin connection on a throwaway PostgreSQL 15+ server
(never the shared Supabase project). Each run creates and drops its own database.
"""
import os
from pathlib import Path
import unittest
from uuid import uuid4

from sentra import compaction
from sentra.errors import SentraError

URL = os.environ.get('SENTRA_TEST_DATABASE_URL')
ROLES = ('anon', 'authenticated', 'sentra_collector', 'sentra_viewer')
RESPONSE = 'a' * 64


@unittest.skipUnless(URL, 'set SENTRA_TEST_DATABASE_URL to a throwaway PostgreSQL server to run')
class CompactionDatabaseTests(unittest.TestCase):
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
            server.execute(f'create database {cls.name}')
        cls.db = psycopg.connect(make_conninfo(URL, dbname=cls.name), autocommit=True)
        cls.db.execute('create schema auth; create table auth.users(id uuid primary key)')
        cls.db.execute(Path('sql/001_foundation.sql').read_text(encoding='utf-8'))
        cls.db.execute(Path('sql/009_compact_series.sql').read_text(encoding='utf-8'))
        cls.db.execute("insert into audit.participants values ('p01')")
        for response in (RESPONSE, 'b' * 64):
            cls.db.execute('''insert into audit.raw_response_manifest values (%s,'p01','google_health','minute_steps',
                'e','{}','minute',now(),'x',%s,1,'{}')''', (response, 'c' * 64))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with cls.psycopg.connect(URL, autocommit=True) as server:
            server.execute(f'drop database {cls.name}')

    def setUp(self):
        self.db.execute('delete from audit.series; delete from audit.measurements; delete from audit.records')

    def rows(self, response, values, *, resolution='60'):
        for i, value in enumerate(values):
            key = f'{response[:4]}-{i:04d}'
            self.db.execute('''insert into audit.records values ('p01','google_health','minute_steps',%s,%s,'{}',%s,now())''',
                            (key, 'c' * 64, response))
            self.db.execute('''insert into audit.measurements values ('p01','google_health','minute_steps',%s,'/steps/countSum',
                %s,'count',%s,null,'vendor_summary','available',null,'2026-10-01T08:00Z'::timestamptz + %s * interval '1 minute',
                '2026-10-01T08:01Z'::timestamptz + %s * interval '1 minute',null,'start','{"t":1}',now(),%s,'minute rollup',%s,%s)''',
                (key, value, '{"v": %d}' % i if i % 2 else None, i, i, resolution, response, f'/m/{i}'))

    def guard(self, **_):
        self.guarded = True

    def test_compaction_is_lossless_including_nulls_and_numeric_scale(self):
        self.rows(RESPONSE, ['12', None, '7.50', '0'], resolution='60.0')
        self.rows('b' * 64, ['3'])
        result = compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps', limit=1)
        self.assertEqual((result['compacted_responses'], result['verified_rows'], result['pending_responses']), (1, 4, 1))
        self.assertTrue(self.guarded)
        same = self.db.execute('''select count(*) from (select row_to_json(t)::text from audit.measurements t
            where source_response_id=%s except all select row_to_json(t)::text from audit.series_rows t) d''',
                               (RESPONSE,)).fetchone()[0]
        self.assertEqual(same, 0)
        self.assertEqual(self.db.execute('select count(*) from audit.measurements').fetchone()[0], 5)  # nothing deleted
        result = compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.assertEqual((result['compacted_responses'], result['pending_responses']), (1, 0))

    def test_a_later_correction_shows_as_a_mismatch_until_rebuilt(self):
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.db.execute("update audit.measurements set value=14 where record_key=%s", (f'{RESPONSE[:4]}-0001',))
        self.assertEqual(compaction.verify(self.db, 'p01', 'google_health', 'minute_steps')['mismatched_responses'], 1)
        compaction.build(self.db, 'p01', 'google_health', 'minute_steps', [RESPONSE])
        self.assertEqual(compaction.verify(self.db, 'p01', 'google_health', 'minute_steps')['mismatched_responses'], 0)

    def test_sparse_datasets_are_refused(self):
        with self.assertRaises(SentraError):
            compaction.compact(self.db, self.guard, 'p01', 'whoop', 'recovery')

    def test_sizes_report_measured_bytes(self):
        self.rows(RESPONSE, [str(i) for i in range(60)])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        report = compaction.sizes(self.db, 'p01', 'google_health', 'minute_steps')
        self.assertEqual((report['measurement_rows'], report['series_rows']), (60, 1))
        self.assertGreater(report['ratio'], 1)


class DenseDatasetTests(unittest.TestCase):
    def test_migration_parses_and_never_deletes_measurements(self):
        from pglast import parse_sql
        text = Path('sql/009_compact_series.sql').read_text(encoding='utf-8')
        self.assertGreaterEqual(len(parse_sql(text)), 10)
        for statement in ('delete from', 'truncate', 'drop ', 'alter table audit.measurements'):
            self.assertNotIn(statement, text.lower())
        self.assertNotIn('delete from audit.measurements', Path(compaction.__file__).read_text(encoding='utf-8'))

    def test_only_dense_datasets_qualify(self):
        self.assertTrue(compaction.is_dense('minute_steps'))
        self.assertTrue(compaction.is_dense('original_heart-rate'))
        self.assertFalse(compaction.is_dense('daily-resting-heart-rate'))
