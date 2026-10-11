"""Synthetic parquet tier build: read-only role, egress/object guards, tier contents and sizes."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import unittest

import pyarrow.parquet as pq
from pglast import parse_sql

from sentra.errors import SentraError
from sentra.shared import CapacityStop, Limits
from sentra.tiers import AuditReader, HOT_DAYS, TIER_BUCKET, build, publish

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
T = lambda days, seconds=0: NOW - timedelta(days=days) + timedelta(seconds=seconds)

ROWS = {
    'hr_raw': [('p01', 'google_health', T(1, s), Decimal(60 + s % 5)) for s in range(0, 180, 5)]
              + [('p01', 'google_health', T(HOT_DAYS + 2), Decimal(70))],
    'hr_minute': [('p01', 'google_health', T(1), '/heartRate/beatsPerMinuteAvg', Decimal('62.4')),
                  ('p01', 'google_health', T(1), '/heartRate/beatsPerMinuteMin', Decimal(60)),
                  ('p01', 'google_health', T(1), '/heartRate/beatsPerMinuteMax', Decimal(66))],
    'measurements': [('p01', 'google_health', 'daily_steps', 'k1', '/steps/countSum', Decimal(8123), 'steps',
                      'vendor_summary', 'available', None, None, None, {'date': {'year': 2026, 'month': 10, 'day': 9}}, '8123'),
                     ('p01', 'google_health', 'daily_steps', 'k2', '/steps/countSum', None, 'steps',
                      'vendor_summary', 'missing', None, None, None, {'year': 2026, 'month': 10, 'day': 8}, None),
                     ('p01', 'google_health', 'activity-level', 'l1', '/activityLevel/activityLevelType', None, None,
                      'unknown', 'available', None, T(2), T(2, 600), None, 'LIGHTLY_ACTIVE')],
    'sessions': [('p02', 'whoop', 'sleep', 's1', 'sleep', T(2), T(2, 25_000), 'SCORED', True)],
}


class FakeDB:
    """Mimics the psycopg calls AuditReader uses; records every statement."""
    def __init__(self, role='sentra_viewer', fail_reserve=False):
        self.role, self.fail_reserve, self.statements, self.reserved = role, fail_reserve, [], []

    def execute(self, query, values=()):
        self.statements.append(query)
        result = None
        if query == 'select session_user':
            result = (self.role,)
        elif 'sentra_reserve_viewer_egress' in query:
            if self.fail_reserve:
                import psycopg
                raise psycopg.errors.RaiseException('capacity_stop')
            self.reserved.append(values[0])
        elif 'sentra_viewer_status' in query:
            result = ({'database_bytes': 290_000_000, 'object_bytes': 1_000_000, 'egress_bytes': 100_000_000,
                       'audit_bytes': 250_000_000},)
        elif query.startswith('select count(*)'):
            name = next(n for n in ROWS if self.current == n)
            result = (len(ROWS[name]), 200 * len(ROWS[name]))
        return type('Result', (), {'fetchone': lambda _self: result})()

    @contextmanager
    def transaction(self):
        yield

    @contextmanager
    def cursor(self, name):
        db = self
        class Cursor:
            itersize = 0
            def execute(self, query, values): db.statements.append(query)
            def fetchall(self): return list(ROWS[name.removeprefix('sentra_tiers_')])
        yield Cursor()


class Reader(AuditReader):
    def read(self, name):
        self.db.current = name
        return super().read(name)


class Storage:
    def __init__(self, code=200): self.code, self.calls = code, []
    def request(self, method, key, **kw):
        self.calls.append((method, key, kw['upsert'], kw['content_type'])); return self.code, b''


class TierTests(unittest.TestCase):
    def test_migration_parses_and_keeps_originals_immutable(self):
        text = Path('sql/006_parquet_tiers.sql').read_text(encoding='utf-8')
        self.assertGreaterEqual(len(parse_sql(text)), 5)
        self.assertIn("'sentra-tiers'", text)
        self.assertNotIn("bucket_id='sentra-originals'", text)
        self.assertNotIn('for delete', text)

    def test_only_the_read_only_viewer_role_may_read(self):
        with self.assertRaises(SentraError):
            AuditReader(FakeDB(role='sentra_collector'), Limits())

    def test_build_reserves_egress_and_produces_expected_tiers(self):
        db = FakeDB(); reader = Reader(db, Limits())
        objects, report = build(reader, Limits(), now=NOW)
        self.assertEqual(sorted(objects), ['hr_minute/p01.parquet', 'hr_raw/p01.parquet', 'measurements.parquet', 'sessions.parquet'])
        self.assertTrue(any('read only' in s for s in db.statements))
        self.assertGreater(sum(db.reserved), reader.read_bytes)
        raw = pq.read_table(io.BytesIO(objects['hr_raw/p01.parquet']))
        self.assertEqual(raw.num_rows, 36)  # the reading older than 30 days leaves the hot tier
        self.assertEqual(str(raw.schema.field('bpm').type), 'uint16')
        minute = pq.read_table(io.BytesIO(objects['hr_minute/p01.parquet'])).to_pylist()
        self.assertEqual({r['source'] for r in minute}, {'sentra_from_raw', 'vendor_60s_rollup'})
        vendor = next(r for r in minute if r['source'] == 'vendor_60s_rollup')
        self.assertEqual((round(vendor['mean'], 1), vendor['min'], vendor['max'], vendor['n']), (62.4, 60, 66, None))
        self.assertEqual(sum(r['n'] for r in minute if r['source'] == 'sentra_from_raw'), 37)  # warm tier keeps old minutes
        measures = pq.read_table(io.BytesIO(objects['measurements.parquet'])).to_pylist()
        steps = [m for m in measures if m['dataset'] == 'daily_steps']
        self.assertEqual([(m['civil_date'], m['value']) for m in steps], [('2026-10-08', None), ('2026-10-09', 8123.0)])
        level = next(m for m in measures if m['dataset'] == 'activity-level')
        self.assertEqual((level['vendor_value'], level['end_ts'] - level['ts']), ('"LIGHTLY_ACTIVE"', 600))
        self.assertEqual(report['projection']['employees'], 10)
        self.assertEqual(report['tiers']['hr_raw']['person_days'], 1)
        self.assertIsNotNone(report['projection']['audit_database_bytes'])

    def test_egress_cap_and_exhausted_budget_stop_before_reading_rows(self):
        db = FakeDB(); reader = Reader(db, Limits(), max_read_bytes=1_000)
        with self.assertRaises(CapacityStop):
            build(reader, Limits(), now=NOW)
        with self.assertRaises(CapacityStop):
            build(Reader(FakeDB(fail_reserve=True), Limits()), Limits(), now=NOW)

    def test_publish_checks_object_capacity_and_upserts_only_tier_bucket(self):
        reader = Reader(FakeDB(), Limits())
        objects, report = build(reader, Limits(), now=NOW)
        storage = Storage()
        result = publish(objects, report, storage, reader, Limits())
        self.assertEqual((result['uploaded'], result['bucket']), (5, TIER_BUCKET))
        self.assertTrue(all(call[2] for call in storage.calls))
        self.assertIn(('POST', 'size_report.json', True, 'application/json'), storage.calls)
        tight = Limits(object_bytes=1_000_000 + 20_000_000 + 1, reserve_bytes=20_000_000)
        with self.assertRaises(CapacityStop):
            publish(objects, report, Storage(), reader, tight)
        with self.assertRaises(SentraError):
            publish(objects, report, Storage(code=403), reader, Limits())

    def test_local_output_writes_files_without_upload(self):
        reader = Reader(FakeDB(), Limits())
        objects, report = build(reader, Limits(), now=NOW)
        with tempfile.TemporaryDirectory() as folder:
            storage = Storage()
            publish(objects, report, storage, reader, Limits(), local_dir=folder)
            self.assertEqual(storage.calls, [])
            self.assertTrue((Path(folder) / 'hr_raw' / 'p01.parquet').is_file())
            self.assertTrue((Path(folder) / 'size_report.json').is_file())


if __name__ == '__main__':
    unittest.main()
