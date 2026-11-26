"""Purpose labels must never weaken the durable allowance ledger."""
import os
from pathlib import Path
from datetime import date
import re
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from sentra.egress import reserve

URL = os.environ.get('SENTRA_TEST_DATABASE_URL')


class EgressCompatibilityTests(unittest.TestCase):
    def test_november_proof_is_specific_to_date_and_deployment_key(self):
        from datetime import datetime, timezone
        from sentra.viewer_config import november_hosted_proof
        now = datetime(2026, 11, 26, tzinfo=timezone.utc)
        hosted = {'redirect_uri': 'https://sentra-wearable-audit.streamlit.app/oauth2callback',
                  'cookie_secret': 'example-host-only-key'}
        proof = november_hosted_proof(hosted, now)
        self.assertEqual(len(proof), 64)
        self.assertNotEqual(proof, november_hosted_proof(dict(hosted, cookie_secret='other-key'), now))
        self.assertIsNone(november_hosted_proof(dict(hosted, redirect_uri='http://localhost:8501/oauth2callback'), now))
        self.assertIsNone(november_hosted_proof(hosted, now.replace(month=12, day=1)))

    def test_only_absent_migration_uses_legacy_signature(self):
        for present, expected in ((False,(10,100)),(True,(10,100,'verify'))):
            db=Mock()
            db.execute.return_value.fetchone.return_value=(present,)
            reserve(db,10,100,'verify')
            self.assertEqual(db.execute.call_args.args[1],expected)
        db=Mock()
        cursor=Mock(); cursor.fetchone.return_value=(True,)
        db.execute.side_effect=[cursor,psycopg.errors.RaiseException('capacity_stop')]
        with self.assertRaises(psycopg.Error): reserve(db,10,100,'verify')
        self.assertEqual(db.execute.call_count,2)  # no unchecked fallback after rejection


@unittest.skipUnless(URL,'set SENTRA_TEST_DATABASE_URL to a disposable PostgreSQL server')
class EgressDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='sentra_egress_test_'+uuid4().hex[:12]
        with psycopg.connect(URL,autocommit=True) as server:
            for role in ('anon','authenticated'):
                if not server.execute('select 1 from pg_roles where rolname=%s',(role,)).fetchone():
                    server.execute(f'create role {role}')
            server.execute(f'create database {cls.name}')
        cls.db=psycopg.connect(make_conninfo(URL,dbname=cls.name),autocommit=True)
        cls.db.execute('''create schema auth; create table auth.users(id uuid primary key);
            create function auth.uid() returns uuid language sql as $$select null::uuid$$;
            create schema storage;
            create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
            create table storage.objects(bucket_id text,metadata jsonb);''')
        for name in ('001_foundation.sql','002_permissions.sql','004_daily_collection.sql','005_viewer_status.sql'):
            source=Path('sql',name).read_text()
            source=re.sub(r'create role (sentra_[a-z]+) login[^;]+;',
                lambda m:f"do $role$ begin if not exists(select 1 from pg_roles where rolname='{m[1]}') then {m[0]} end if; end $role$;",source)
            cls.db.execute(source)
        cls.db.execute("insert into collector_private.egress_budget values(date_trunc('month',now())::date,100,123,now())")
        cls.db.execute(Path('sql/013_egress_purpose.sql').read_text())
        cls.migrated=cls.db.execute('select baseline_bytes,reserved_bytes from collector_private.egress_budget').fetchone()
        cls.history=cls.db.execute('select purpose,reserved_bytes from collector_private.egress_purposes').fetchall()
        before=cls.db.execute('select * from collector_private.egress_budget').fetchall()
        cls.db.execute(Path('sql/015_approved_egress_ceiling.sql').read_text())
        # Substitute a deterministic clock exclusively in this disposable test database.
        sql = Path('sql/018_november_hosted_viewer.sql').read_text()
        cls.db.execute(sql.replace('clock_timestamp()', "current_setting('test.grant_clock')::timestamptz"))
        cls.headroom_preserved=(before==cls.db.execute('select * from collector_private.egress_budget').fetchall()
            and cls.history==cls.db.execute('select purpose,reserved_bytes from collector_private.egress_purposes').fetchall())

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with psycopg.connect(URL,autocommit=True) as server:
            server.execute(f'drop database {cls.name}')

    def setUp(self):
        self.db.execute('reset session authorization')
        self.db.execute('delete from collector_private.egress_purposes')
        self.db.execute('update collector_private.egress_budget set baseline_bytes=100,reserved_bytes=0,verified_at=now()')

    def test_checkpoint_reservation_tracks_bytes_and_refuses_over_budget_read(self):
        from psycopg.types.json import Jsonb
        from sentra.cloud_store import CloudStore
        from sentra.daily_plan import day_jobs
        from sentra.shared import Limits, CapacityStop
        from sentra.shared_backend import SharedBackend

        with patch('sentra.shared_backend.connect_db', return_value=self.db):
            backend = SharedBackend({}, Limits(monthly_egress_bytes=100_000))
        store = CloudStore(backend, 'p99', 'whoop')
        job = day_jobs('whoop', date(2026, 1, 1))[0]
        self.assertIsNone(store.progress(job))
        self.db.execute("insert into audit.participants(participant_id) values ('p99')")
        payload = {'cursor': 'ü' * 1024}
        size = self.db.execute("""insert into collector_private.daily_jobs
            (participant_id,provider,dataset,job_key,progress) values ('p99','whoop',%s,%s,%s)
            returning octet_length(progress::text)""", (job.dataset, job.key, Jsonb(payload))).fetchone()[0]
        self.assertEqual(store.progress(job), payload)
        reserved = self.db.execute('select reserved_bytes from collector_private.egress_budget').fetchone()[0]
        self.assertEqual(reserved, 3 * 4096 + size)
        self.db.execute('update collector_private.egress_budget set baseline_bytes=%s',
                        (100_000 - reserved - 8192 - size,))
        with self.assertRaises(CapacityStop):
            store.progress(job)
        self.assertEqual(self.db.execute('select reserved_bytes from collector_private.egress_budget').fetchone()[0],
                         reserved + 4096)

    def test_hosted_grant_is_atomic_private_bounded_and_expires(self):
        db = self.db
        db.execute("set test.grant_clock='2026-11-26 20:00:00+00'")
        db.execute("insert into collector_private.november_viewer_grant(proof_digest) values(sha256('fixture'::bytea))")
        db.execute('update collector_private.egress_budget set baseline_bytes=4499999900')
        call = 'select public.sentra_reserve_november_hosted_viewer(%s,4500000000,%s)'
        db.execute('set session authorization sentra_collector')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            db.execute(call, (200, 'fixture'))
        db.execute('set session authorization sentra_viewer')
        with self.assertRaises(psycopg.Error):
            reserve(db, 200, 4500000000, 'viewer', viewer=True)
        with self.assertRaises(psycopg.Error):
            db.execute(call, (200, 'other'))
        db.execute("set test.grant_clock='2026-12-01 00:00:00+00'")
        with self.assertRaises(psycopg.Error):
            db.execute(call, (200, 'fixture'))
        db.execute("set test.grant_clock='2026-11-30 23:59:59+00'")
        db.execute('reset session authorization')
        db.execute("update collector_private.egress_budget set verified_at=now()-interval '8 days'")
        db.execute('set session authorization sentra_viewer')
        with self.assertRaises(psycopg.Error):
            db.execute(call, (200, 'fixture'))
        db.execute('reset session authorization')
        db.execute('update collector_private.egress_budget set verified_at=now()')
        db.execute('set session authorization sentra_viewer')
        for amount in (200, 49999800):
            db.execute(call, (amount, 'fixture'))
        with self.assertRaises(psycopg.Error):
            db.execute(call, (1, 'fixture'))
        db.execute('reset session authorization')
        self.assertEqual(db.execute('select spent_bytes from collector_private.november_viewer_grant').fetchone(), (50000000,))
        self.assertEqual(db.execute('select baseline_bytes,reserved_bytes from collector_private.egress_budget').fetchone(),
                         (4499999900, 50000000))
        self.assertEqual(db.execute('select purpose,reserved_bytes from collector_private.egress_purposes').fetchall(),
                         [('viewer', 50000000)])

    def test_object_lookup_is_scoped_to_provider_participant_and_digest(self):
        from sentra.shared import Limits
        from sentra.shared_backend import SharedBackend

        with patch('sentra.shared_backend.connect_db', return_value=self.db):
            backend = SharedBackend({}, Limits())
        self.db.execute("insert into audit.participants(participant_id) values ('p98')")
        digest = 'a' * 64
        self.assertFalse(backend.has_object('whoop', 'p98', digest))
        self.db.execute("""insert into audit.raw_response_manifest values
            (%s,'p98','whoop','cycle','synthetic','{}','daily',now(),'synthetic',%s,0,'{}')""",
                        ('b' * 64, digest))
        self.assertTrue(backend.has_object('whoop', 'p98', digest))
        self.assertFalse(backend.has_object('google_health', 'p98', digest))
        self.assertFalse(backend.has_object('whoop', 'p97', digest))
        self.assertFalse(backend.has_object('whoop', 'p98', 'c' * 64))

    def test_migration_keeps_prior_reservations_and_baseline(self):
        self.assertEqual(self.migrated,(100,123))
        self.assertEqual(self.history,[('prior_unattributed',123)])
        self.assertTrue(self.headroom_preserved)

    def test_approved_ceiling_accepts_old_ceiling_usage_and_still_stops_at_new_limit(self):
        self.db.execute('update collector_private.egress_budget set baseline_bytes=3600000000')
        self.db.execute('set session authorization sentra_viewer')
        reserve(self.db,100,4500000000,'viewer',viewer=True)
        self.db.execute('select public.sentra_reserve_viewer_egress(100,4500000000)')
        self.db.execute('reset session authorization')
        self.assertEqual(self.db.execute('select baseline_bytes,reserved_bytes from collector_private.egress_budget').fetchone(),
                         (3600000000,200))
        self.db.execute('update collector_private.egress_budget set baseline_bytes=4499999799')
        self.db.execute('set session authorization sentra_viewer')
        with self.assertRaises(psycopg.Error): reserve(self.db,1,4500000000,'viewer',viewer=True)
        self.db.execute('reset session authorization')
        self.assertEqual(self.db.execute('select reserved_bytes from collector_private.egress_budget').fetchone()[0],200)

    def test_legacy_and_new_calls_share_one_atomic_ledger(self):
        self.db.execute('set session authorization sentra_collector')
        reserve(self.db,20,1000,'backup')
        reserve(self.db,30,1000,'verify')
        self.db.execute('select collector_private.reserve_egress(40,1000)')
        usage=self.db.execute('select collector_private.usage()').fetchone()[0]
        self.assertEqual(usage['egress_bytes'],190)
        self.assertEqual(usage['egress_reserved_by_purpose'],{'backup':20,'verify':30,'collector':40})
        for query in ('select * from collector_private.egress_purposes',
                      "update collector_private.egress_purposes set reserved_bytes=0"):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.db.execute(query)
        with self.assertRaises(psycopg.Error): reserve(self.db,810,1000,'backup')
        self.assertEqual(self.db.execute('select collector_private.usage()').fetchone()[0],usage)

    def test_viewer_limits_purposes_and_failures_preserve_accounting(self):
        self.db.execute('set session authorization sentra_viewer')
        reserve(self.db,10,1000,'tiers',viewer=True)
        self.db.execute('select public.sentra_reserve_viewer_egress(20,1000)')
        for amount,ceiling,purpose in ((-1,1000,'tiers'),(100000001,3500000000,'tiers'),
                                     (1,4500000001,'tiers'),(1,1000,'backup'),(1,1000,None)):
            with self.assertRaises(psycopg.Error): reserve(self.db,amount,ceiling,purpose,viewer=True)
        with self.assertRaises(psycopg.Error): reserve(self.db,1,1000,'collector')
        self.db.execute('reset session authorization')
        self.assertEqual(self.db.execute('select reserved_bytes from collector_private.egress_budget').fetchone()[0],30)
        self.assertEqual(dict(self.db.execute('select purpose,reserved_bytes from collector_private.egress_purposes').fetchall()),{'tiers':10,'viewer':20})
        self.db.execute("update collector_private.egress_budget set verified_at=now()-interval '8 days'")
        with self.assertRaises(psycopg.Error): reserve(self.db,1,1000,'verify')
        self.assertEqual(self.db.execute('select reserved_bytes from collector_private.egress_budget').fetchone()[0],30)
