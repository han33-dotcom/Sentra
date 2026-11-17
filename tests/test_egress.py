"""Purpose labels must never weaken the durable allowance ledger."""
import os
from pathlib import Path
import re
import unittest
from unittest.mock import Mock
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from sentra.egress import reserve

URL = os.environ.get('SENTRA_TEST_DATABASE_URL')


class EgressCompatibilityTests(unittest.TestCase):
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
