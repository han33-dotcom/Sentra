"""Lossless compaction (sql/009_compact_series.sql, sentra.compaction) on a real PostgreSQL server.

Opt-in: set SENTRA_TEST_DATABASE_URL to an admin connection on a throwaway PostgreSQL 15+ server
(never the shared Supabase project). Each run creates and drops its own database.
"""
import os
import re
from pathlib import Path
import unittest
from uuid import uuid4

from sentra import compaction
from sentra.tiers import tier_query
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
        cls.db.execute("""create schema auth; create table auth.users(id uuid primary key);
            create function auth.uid() returns uuid language sql as $$select null::uuid$$;
            create schema storage;
            create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
            create table storage.objects(bucket_id text,metadata jsonb);""")
        for filename in ('001_foundation.sql','002_permissions.sql','003_numeric_precision.sql',
                         '004_daily_collection.sql','005_viewer_status.sql','006_parquet_tiers.sql',
                         '007_organization_access.sql','008_self_service_enrollment.sql',
                         '009_compact_series.sql','012_compact_writes.sql'):
            migration = Path('sql',filename).read_text(encoding='utf-8')
            migration = re.sub(r'create role (sentra_[a-z]+) login[^;]+;',
                lambda m: f"do $role$ begin if not exists(select 1 from pg_roles where rolname='{m[1]}') then {m[0]} end if; end $role$;",migration)
            cls.db.execute(migration)
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
        self.db.execute('update collector_private.compact_control set enabled=false')
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

    def tier_rows(self):
        query, values = tier_query('measurements', series=True)
        return sorted(self.db.execute(query, values).fetchall(), key=repr)

    def test_tiers_publish_the_same_rows_after_per_field_rows_are_removed(self):
        self.rows(RESPONSE, ['12', None, '7.50', '0'], resolution='60.0')
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        before = self.tier_rows()
        self.assertEqual(len(before), 4)  # per-field rows present: compact copies are not read twice
        measurements_only, values = tier_query('measurements', series=False)
        self.assertEqual(before, sorted(self.db.execute(measurements_only, values).fetchall(), key=repr))
        # Simulates the gated phase-3 deletion on this throwaway database only.
        self.db.execute('delete from audit.measurements where source_response_id=%s', (RESPONSE,))
        self.assertEqual(self.tier_rows(), before)

    def collector(self):
        """The real collector write path on this throwaway database; capacity checks are not under test."""
        from sentra.shared_backend import SharedBackend
        backend = SharedBackend.__new__(SharedBackend)
        backend.db, backend.guard, backend.reserve = self.db, lambda **_: None, lambda amount: None
        return backend

    def viewer(self):
        from sentra.viewer_reader import ViewerReader
        from sentra.shared import Limits
        reader = ViewerReader({}, Limits(), lambda: 'operator@test.invalid', db=self.db)
        reader.reserve = lambda amount: None  # synthetic local database has no egress service
        return reader

    def normalized_records(self):
        self.rows(RESPONSE, ['12', None, '7.50', '0'], resolution='60.0')
        rows = self.db.execute('select to_jsonb(m) from audit.measurements m order by record_key').fetchall()
        return [{**{k:m[k] for k in ('participant_id','provider','dataset','record_key','source_response_id','collected_at')},
                 'session_type':None,'vendor_fields':{},'measurements':[{**m,'vendor_metric':m['metric']}]}
                for (m,) in rows]

    def test_compact_collector_batches_retries_and_corrections_preserve_all_columns(self):
        from copy import deepcopy
        records = self.normalized_records()
        backend = self.collector()
        backend.put_records(records)  # disabled by default: established per-field conversion
        before = self.db.execute('select row_to_json(m)::text from audit.measurements m order by record_key').fetchall()
        self.db.execute('update collector_private.compact_control set enabled=true')
        backend.put_records(records[:2]); backend.put_records(records[2:])
        backend.put_records(records)  # same-response retry must not duplicate readings
        self.assertEqual(self.db.execute('select count(*) from audit.measurements').fetchone()[0],0)
        self.assertEqual(self.db.execute('select row_to_json(m)::text from audit.series_rows m order by record_key').fetchall(),before)
        self.assertEqual(backend.counts('p01','google_health')['measurements'],4)
        self.assertEqual(backend.verify_projections('p01','google_health')['measurement_mismatches'],0)
        revised = deepcopy(records[0])
        revised['source_response_id'] = revised['measurements'][0]['source_response_id'] = 'b'*64
        revised['measurements'][0]['value'] = 99
        backend.put_records([revised])
        omitted = {**records[1],'source_response_id':'b'*64,'measurements':[]}
        backend.put_records([omitted])
        self.assertEqual(len(self.tier_rows()),3)
        self.assertEqual(sorted(str(r[5]) for r in self.tier_rows()),['0','7.5','99'])
        self.assertEqual(self.db.execute('select count(*) from audit.series_rows').fetchone()[0],3)
        self.assertEqual(backend.verify_projections('p01','google_health')['measurement_mismatches'],0)
        with self.assertRaisesRegex(SentraError,'Compact collector writes'):
            compaction.compact(self.db,self.guard,'p01','google_health','minute_steps',repair=True)
        self.db.execute('update collector_private.compact_control set enabled=false')
        with self.assertRaisesRegex(SentraError,'compact-only readings'):
            compaction.compact(self.db,self.guard,'p01','google_health','minute_steps',repair=True)
        self.assertEqual(len(self.tier_rows()),3)

    def test_compact_collector_failure_rolls_back_records_arrays_and_projection_deletion(self):
        from copy import deepcopy
        records = self.normalized_records()
        backend = self.collector(); backend.put_records(records)
        self.db.execute('update collector_private.compact_control set enabled=true')
        backend.put_records(records)
        before = self.db.execute('select row_to_json(m)::text from audit.series_rows m order by record_key').fetchall()
        invalid = deepcopy(records[0]); invalid['measurements'] *= 2
        with self.assertRaisesRegex(SentraError,'Duplicate measurement'):
            backend.put_records([invalid])
        self.assertEqual(self.db.execute('select row_to_json(m)::text from audit.series_rows m order by record_key').fetchall(),before)
        self.assertEqual(backend.verify_projections('p01','google_health')['measurement_mismatches'],0)
        backend.guard = lambda **_: (_ for _ in ()).throw(SentraError('capacity stop'))
        with self.assertRaisesRegex(SentraError,'capacity stop'):
            backend.put_records(records)
        self.assertEqual(self.db.execute('select row_to_json(m)::text from audit.series_rows m order by record_key').fetchall(),before)

    def test_compact_writer_uses_collector_permissions_and_keeps_sparse_path(self):
        from copy import deepcopy
        records = self.normalized_records()
        sparse = deepcopy(records[0])
        sparse.update(dataset='daily_steps', source_response_id='d'*64)
        sparse['measurements'][0].update(dataset='daily_steps', source_response_id='d'*64)
        self.db.execute('''insert into audit.raw_response_manifest values (%s,'p01','google_health','daily_steps',
            'e','{}','daily',now(),'x',%s,1,'{}')''', ('d'*64,'c'*64))
        self.db.execute('update collector_private.compact_control set enabled=true')
        self.db.execute('set role sentra_collector')
        try:
            backend = self.collector(); backend.put_records([*records,sparse])
            self.assertEqual(backend.counts('p01','google_health')['measurements'],5)
            self.assertEqual(backend.verify_projections('p01','google_health')['measurement_mismatches'],0)
            self.assertEqual(self.db.execute('select dataset,count(*) from audit.measurements group by dataset').fetchall(),[('daily_steps',1)])
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.db.execute('update collector_private.compact_control set enabled=false')
        finally:
            self.db.execute('reset role')
        # The report counts logical readings while charging their actual compact payload.
        backend.usage = lambda: {'audit_bytes':1000000}
        from sentra.capacity import snapshot
        counts = snapshot(backend)['measurement_rows']
        self.assertEqual(sum(r['rows'] for r in counts),5)
        self.db.execute('set role sentra_enrollment')
        try:
            status = self.db.execute("select enrollment_private.participation_status('p01')").fetchone()[0]
            self.assertEqual(status['latest_measurement_day'],'2026-10-01')
            self.assertTrue(status['collection_paused'])
            self.assertEqual(status['assessment'],'not_available')
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.db.execute('select * from audit.series')
        finally:
            self.db.execute('reset role')
        report = backend.growth_report()
        dense = next(r for r in report['datasets'] if r['dataset']=='minute_steps')
        self.assertEqual(dense['measurements'],4)
        physical = self.db.execute("select (select sum(pg_column_size(record)) from audit.records where dataset='minute_steps')+(select sum(pg_column_size(s)) from audit.series s)").fetchone()[0]
        self.assertEqual(dense['stored_payload_bytes'],int(physical))

    def test_viewer_preserves_catalog_metrics_context_and_readings_after_compaction(self):
        from datetime import date
        from sentra.viewer_data import Selection
        from unittest.mock import patch
        self.rows(RESPONSE, ['12', None, '7.50'], resolution='60.0')
        self.db.execute('''insert into audit.connection_state values
            ('p01','google_health','minute_steps','authorized',null,'[]','{}',now())
            on conflict do nothing''')
        reader = self.viewer()
        selection = Selection('p01', 'google_health', 'minute_steps', date(2026,10,1), date(2026,10,2))
        def snapshot():
            return (reader.catalog(), reader.metrics(selection), reader.measurements(selection), reader.records(selection))
        before = snapshot()
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.assertEqual(snapshot(), before)  # no duplicate when both representations exist
        self.db.execute('delete from audit.measurements')  # disposable database only
        self.assertEqual(snapshot(), before)
        self.assertEqual(len(before[2]), 3)
        # Both size and row limits apply to expanded compact rows before transfer.
        with patch('sentra.viewer_reader.MAX_ROWS', 2):
            with self.assertRaisesRegex(SentraError, 'Narrow'):
                reader.measurements(selection)
        with patch('sentra.viewer_reader.MAX_BYTES', 1):
            with self.assertRaisesRegex(SentraError, 'Narrow'):
                reader.records(selection)

    def test_viewer_ignores_obsolete_compact_readings_and_prefers_corrections(self):
        from datetime import date
        from sentra.viewer_data import Selection
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        selection = Selection('p01', 'google_health', 'minute_steps', date(2026,10,1), date(2026,10,2))
        reader = self.viewer()
        self.db.execute('update audit.measurements set value=14 where record_key=%s', (f'{RESPONSE[:4]}-0001',))
        self.assertEqual([str(r['value']) for r in reader.measurements(selection)], ['12', '14'])
        self.collector().put_records([{'participant_id':'p01', 'provider':'google_health', 'dataset':'minute_steps',
            'record_key':f'{RESPONSE[:4]}-0000', 'source_response_id':'b'*64,
            'collected_at':'2026-10-02T00:00:00Z', 'measurements':[], 'session_type':None}])
        self.assertEqual([str(r['value']) for r in reader.measurements(selection)], ['14'])
        self.assertEqual(len(reader.records(selection)), 1)

    def test_viewer_uses_legacy_schema_without_compact_view(self):
        from datetime import date
        from sentra.viewer_data import Selection
        self.rows(RESPONSE, ['12'])
        # Roll back the schema change so other cases retain the installed migration.
        with self.db.transaction(force_rollback=True):
            self.db.execute('drop view audit.series_rows')
            reader = self.viewer()
            selection = Selection('p01', 'google_health', 'minute_steps', date(2026,10,1), date(2026,10,2))
            self.assertEqual(len(reader.measurements(selection)), 1)
            self.assertEqual(len(reader.metrics(selection)), 1)

    def test_a_reading_omitted_by_a_newer_response_is_not_republished(self):
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        # A newer response replaces the first record and no longer contains its reading.
        self.collector().put_records([{'participant_id': 'p01', 'provider': 'google_health', 'dataset': 'minute_steps',
            'record_key': f'{RESPONSE[:4]}-0000', 'source_response_id': 'b' * 64,
            'collected_at': '2026-10-02T00:00:00Z', 'measurements': [], 'session_type': None}])
        current = self.db.execute("select count(*) from audit.measurements where record_key=%s",
                                  (f'{RESPONSE[:4]}-0000',)).fetchone()[0]
        self.assertEqual(current, 0)
        self.assertEqual([str(r[5]) for r in self.tier_rows()], ['13'])  # the obsolete 12 stays unpublished
        # The untouched second record is still published from its compact copy once its row is removed.
        self.db.execute('delete from audit.measurements where source_response_id=%s', (RESPONSE,))
        self.assertEqual([str(r[5]) for r in self.tier_rows()], ['13'])

    def test_a_per_field_correction_wins_over_a_stale_compact_copy(self):
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.db.execute("update audit.measurements set value=14 where record_key=%s", (f'{RESPONSE[:4]}-0001',))
        values = sorted(r[5] for r in self.tier_rows())
        self.assertEqual([str(v) for v in values], ['12', '14'])

    def test_a_later_correction_shows_as_a_mismatch_until_rebuilt(self):
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.db.execute("update audit.measurements set value=14 where record_key=%s", (f'{RESPONSE[:4]}-0001',))
        self.assertEqual(compaction.verify(self.db, 'p01', 'google_health', 'minute_steps')['mismatched_responses'], 1)
        compaction.build(self.db, 'p01', 'google_health', 'minute_steps', [RESPONSE])
        self.assertEqual(compaction.verify(self.db, 'p01', 'google_health', 'minute_steps')['mismatched_responses'], 0)

    def test_repair_rebuilds_corrected_and_moved_readings_through_the_public_path(self):
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.db.execute("update audit.measurements set value=14 where record_key=%s", (f'{RESPONSE[:4]}-0000',))
        result = compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.assertEqual((result['compacted_responses'], result['mismatched_responses']), (0, 1))  # ordinary run cannot fix it
        result = compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps', repair=True)
        self.assertEqual((result['compacted_responses'], result['mismatched_responses'], result['verified_rows']), (1, 0, 2))
        # A corrected record moves to a newer original response: the old copy must not keep the reading.
        moved = 'b' * 64
        self.db.execute("update audit.records set source_response_id=%s where record_key=%s", (moved, f'{RESPONSE[:4]}-0001'))
        self.db.execute("update audit.measurements set source_response_id=%s where record_key=%s", (moved, f'{RESPONSE[:4]}-0001'))
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.assertEqual(compaction.verify(self.db, 'p01', 'google_health', 'minute_steps')['mismatched_responses'], 1)
        result = compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps', repair=True)
        self.assertEqual((result['mismatched_responses'], result['verified_responses'], result['verified_rows']), (0, 2, 2))
        self.db.execute("delete from audit.measurements where source_response_id=%s", (moved,))  # every reading gone
        with self.assertRaisesRegex(SentraError,'compact-only readings'):
            compaction.compact(self.db,self.guard,'p01','google_health','minute_steps',repair=True)
        # Only a later authoritative record that omits the reading makes its compact copy obsolete.
        self.collector().put_records([{'participant_id':'p01','provider':'google_health','dataset':'minute_steps',
            'record_key':f'{RESPONSE[:4]}-0001','source_response_id':RESPONSE,
            'collected_at':'2026-10-03T00:00:00Z','measurements':[],'session_type':None}])
        result = compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps', repair=True)
        self.assertEqual((result['mismatched_responses'], result['verified_responses']), (0, 1))
        self.assertEqual(self.db.execute('select count(*) from audit.series where source_response_id=%s', (moved,)).fetchone()[0], 0)

    def test_cli_exits_nonzero_while_any_copy_is_stale(self):
        from argparse import Namespace
        from unittest import mock
        from sentra import shared_cli
        self.rows(RESPONSE, ['12', '13'])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        self.db.execute("update audit.measurements set value=14 where record_key=%s", (f'{RESPONSE[:4]}-0000',))
        backend = mock.Mock(db=self.db, guard=self.guard)
        connection = mock.Mock(private_dir=Path('.private'))
        run = lambda command, **extra: shared_cli.run_command(Namespace(
            command=command, config=Path('config/local.toml'), participant='p01', provider='google_health',
            dataset='minute_steps', **extra))
        with mock.patch.object(shared_cli, 'local_cipher'), \
                mock.patch.object(shared_cli, 'load_connection', return_value=connection), \
                mock.patch.object(shared_cli, 'read_shared', return_value=({}, None, Path('.private'))), \
                mock.patch.object(shared_cli, 'SharedBackend', return_value=backend), mock.patch('builtins.print'):
            self.assertEqual(run('shared-compact-verify'), 1)
            self.assertEqual(run('shared-compact', limit=200, repair=False), 1)
            self.assertEqual(run('shared-compact', limit=200, repair=True), 0)
            self.assertEqual(run('shared-compact-verify'), 0)

    def test_sparse_datasets_are_refused(self):
        with self.assertRaises(SentraError):
            compaction.compact(self.db, self.guard, 'p01', 'whoop', 'recovery')

    def test_sizes_report_measured_bytes(self):
        self.rows(RESPONSE, [str(i) for i in range(60)])
        compaction.compact(self.db, self.guard, 'p01', 'google_health', 'minute_steps')
        report = compaction.sizes(self.db, 'p01', 'google_health', 'minute_steps')
        self.assertEqual((report['measurement_rows'], report['series_rows']), (60, 1))
        self.assertGreater(report['ratio'], 1)


    def removal_fixture(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import Mock
        from sentra import compact_removal as removal
        import json, hashlib
        self.db.execute("update collector_private.observation_control set settings='{\"enabled\":false}',updated_at=now()-interval '1 hour'")
        self.rows(RESPONSE,['12',None,'7.50','0'],resolution='60.0')
        self.rows('b'*64,['3'])
        compaction.compact(self.db,self.guard,'p01','google_health','minute_steps')
        backend=self.collector(); backend.credentials={'url':'https://source.invalid'}
        now=datetime.now(timezone.utc)
        plan=removal.preview(backend,'p01','google_health','minute_steps',limit=1,now=now)
        # Archive authentication/count validation has its own real encrypted backup suite.
        # Here the synthetic archive reader exercises exact row inclusion and transactional gates.
        rows=self.db.execute('select to_jsonb(m) from audit.measurements m').fetchall()
        reader=Mock(info={'files':{'measurements-00000':{}}})
        reader.path.read_bytes.return_value=b'synthetic encrypted manifest'
        reader.read.return_value='\n'.join(json.dumps(row) for row, in rows).encode()
        verified={'created_at':(now-timedelta(minutes=1)).isoformat(),'selection':{},'not_covered':[],
                  'project_url':backend.credentials['url'],'tables':{'measurements':5,'series':2},'originals':2}
        evidence={'backup_manifest_sha256':hashlib.sha256(reader.path.read_bytes()).hexdigest(),
                  'status':'restored_and_verified','source_project_url':backend.credentials['url'],
                  'target_project_url':'https://isolated.invalid','isolation_verified':True,
                  'counts':verified['tables'],'originals_verified':2,
                  'retention_decision_url':'https://github.com/han33-dotcom/Sentra/issues/29'}
        return removal,backend,plan,reader,verified,evidence

    def test_removal_preserves_logical_readings_records_and_other_responses(self):
        from unittest.mock import patch,Mock
        m,b,plan,reader,verified,evidence=self.removal_fixture()
        before=self.tier_rows(); check=Mock()
        with patch.object(m,'verify_backup',return_value=verified):
            result=m.remove(b,plan,reader,evidence,['owner-a','owner-b'],check_approvals=check)
        self.assertEqual(result['rows'],4)
        self.assertEqual(self.tier_rows(),before)
        self.assertEqual(self.db.execute('select count(*) from audit.records').fetchone()[0],5)
        self.assertEqual(self.db.execute('select count(*) from audit.measurements').fetchone()[0],1)
        check.assert_called_once_with(['owner-a','owner-b'],plan['sha256'],m.digest(evidence))

    def test_removal_stops_for_changed_state_missing_backup_or_approval(self):
        from unittest.mock import patch,Mock
        m,b,plan,reader,verified,evidence=self.removal_fixture()
        check=Mock()
        with patch.object(m,'verify_backup',return_value=verified):
            for changed in ({**evidence,'isolation_verified':False},{**evidence,'target_project_url':plan['project_url']}):
                with self.assertRaises(SentraError): m.remove(b,plan,reader,changed,[],check_approvals=check)
            check.assert_not_called()
            with self.assertRaisesRegex(SentraError,'approval rejected'):
                m.remove(b,plan,reader,evidence,[],check_approvals=Mock(side_effect=SentraError('approval rejected')))
            reader.read.return_value=b''
            with self.assertRaisesRegex(SentraError,'every current row'):
                m.remove(b,plan,reader,evidence,[],check_approvals=check)
            self.db.execute('update audit.measurements set value=99 where source_response_id=%s',(RESPONSE,))
            with self.assertRaisesRegex(SentraError,'lossless'):
                m.remove(b,plan,reader,evidence,[],check_approvals=check)
        self.assertEqual(self.db.execute('select count(*) from audit.measurements').fetchone()[0],5)

    def test_removal_preview_requires_paused_additive_current_data(self):
        m,b,plan,reader,verified,evidence=self.removal_fixture()
        self.db.execute('update collector_private.compact_control set enabled=true')
        with self.assertRaisesRegex(SentraError,'Compact collector writes'):
            m.preview(b,'p01','google_health','minute_steps')
        self.db.execute('update collector_private.compact_control set enabled=false')
        self.db.execute("update collector_private.observation_control set settings='{\"enabled\":true}'")
        with self.assertRaisesRegex(SentraError,'paused'):
            m.preview(b,'p01','google_health','minute_steps')
        self.db.execute("update collector_private.observation_control set settings='{\"enabled\":false}'")


class DenseDatasetTests(unittest.TestCase):
    def test_removal_owner_comments_bind_exact_plan_and_recovery_evidence(self):
        from unittest.mock import Mock
        from sentra import compact_removal as m
        import json
        def response(author,body=None):
            r=Mock(status_code=200)
            r.__enter__=Mock(return_value=r); r.__exit__=Mock(return_value=False)
            r.iter_content.return_value=[json.dumps({'user':{'login':author},
                'issue_url':'https://api.github.com/repos/han33-dotcom/Sentra/issues/105',
                'body':body or 'APPROVE SENTRA PHASE3 plan EVIDENCE recovery'}).encode()]
            return r
        urls=['https://github.com/han33-dotcom/Sentra/pull/105#issuecomment-'+str(i) for i in (1,2)]
        m.approval_comments(urls,'plan','recovery',get=Mock(side_effect=[response(a) for a in m.OWNERS]))
        for responses in ([response('han33-dotcom'),response('han33-dotcom')],
                          [response(a,'APPROVE SENTRA PHASE3 old EVIDENCE recovery') for a in m.OWNERS]):
            with self.assertRaises(SentraError): m.approval_comments(urls,'plan','recovery',get=Mock(side_effect=responses))

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
