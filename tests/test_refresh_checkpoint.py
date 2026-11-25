"""Failure and resume regression tests with synthetic dashboard sources."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

from cryptography.fernet import Fernet
from sentra import monthly_tiers as m
from sentra import wellness_refresh
from sentra.refresh_checkpoint import RefreshCheckpoint, PLAN_ALLOWANCE
from sentra.shared import Limits
import test_monthly_tiers as fixtures
from test_tiers import Bucket,NOW


class RecoveryTests(unittest.TestCase):
    def test_publication_allowance_is_unavailable_to_source_reads(self):
        reader=fixtures.MonthlyTests().reader()
        limits=Limits(monthly_egress_bytes=80_000_000)
        reader.limits=limits
        def stop(*args,**kwargs):
            self.assertEqual(reader.limits.monthly_egress_bytes,71_000_000)
            raise RuntimeError('source interrupted')
        with patch.object(wellness_refresh,'latest_run',return_value=None),patch.object(m,'build',side_effect=stop):
            with self.assertRaisesRegex(RuntimeError,'source interrupted'):
                wellness_refresh.refresh(reader,limits,Bucket(),incremental=True,finish_allowance=9_000_000)
        self.assertEqual(reader.limits,limits)

    def test_resuming_rejects_stale_inputs_but_accepts_its_own_tier_publication(self):
        with TemporaryDirectory() as tmp:
            cache=RefreshCheckpoint(tmp,Fernet(Fernet.generate_key()),'synthetic',
                                    expected_sources={'x':[4]},expected_objects={'x':'old'})
            cache.verify_plan({'x':[4]},{'x':'old'})
            cache.record_prepared({'x':[4]},{'x':'prepared'})
            cache.verify_plan({'x':[4]},{'x':'prepared'})
            with self.assertRaisesRegex(Exception,'sources changed'):
                cache.verify_plan({'x':[5]},{'x':'old'})
            with self.assertRaisesRegex(Exception,'tiers changed'):
                cache.verify_plan({'x':[4]},{'x':'foreign'})

    def test_changed_sessions_do_not_refetch_measurements_or_heart_rate(self):
        fixture=fixtures.MonthlyTests()
        reader=fixture.reader()
        bucket=Bucket()
        signatures,queries=fixture.inventory()
        with patch.object(m,'inventory',return_value=(signatures,queries)):
            objects,report=m.build(reader,Limits(),bucket,now=NOW)
            m.publish(objects,report,bucket,reader,Limits())
            signatures=dict(signatures)
            signatures['sessions/2026-10']=[2,'changed','changed']
            reader.read_partition.reset_mock()
            with patch.object(m,'inventory',return_value=(signatures,queries)):
                current,_=m.build(reader,Limits(),bucket,now=NOW)
            self.assertEqual(reader.read_partition.call_count,1)
            self.assertIn('(sessions)',reader.read_partition.call_args.args[0])
            self.assertEqual(current,objects)

    def test_authenticated_cache_detects_swapped_files(self):
        with TemporaryDirectory() as tmp:
            cache=RefreshCheckpoint(Path(tmp),Fernet(Fernet.generate_key()),'synthetic')
            cache.save('a',{'example':b'private bytes'})
            cache.save('b',{'another':b'second'})
            self.assertNotIn(b'private bytes',cache.path(['group','a']).read_bytes())
            cache.path(['group','b']).write_bytes(cache.path(['group','a']).read_bytes())
            with self.assertRaisesRegex(Exception,'identity mismatch'):
                cache.load('b')

    @unittest.skipUnless(os.getenv('SENTRA_TEST_DATABASE_URL'),'requires disposable local PostgreSQL')
    def test_disconnect_resumes_without_charging_completed_page(self):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        url=os.environ['SENTRA_TEST_DATABASE_URL']
        self.assertIn(conninfo_to_dict(url)['host'],('localhost','127.0.0.1','::1'))
        query="""select i,('2026-11-23'::date + i) as day, 1.20::numeric as val,
                 case when mod(i,2)=0 then jsonb_build_object('a',i) end as detail
                 from generate_series(0,1099) i"""
        with TemporaryDirectory() as tmp, psycopg.connect(url) as db:
            cache=RefreshCheckpoint(tmp,Fernet(Fernet.generate_key()),'synthetic')
            reader=Mock(db=db,read_bytes=0,max_read_bytes=2_000_000)
            reader.reserve.side_effect=[None,None,RuntimeError('disconnected')]
            with self.assertRaisesRegex(RuntimeError,'disconnected'):
                cache.read_partition(reader,query,(),['source','v1'])
            reader.reserve.reset_mock(side_effect=True)
            reader.read_bytes=0
            rows=cache.read_partition(reader,query,(),['source','v1'])
            expected=db.execute('select * from ('+query+') q order by q::text collate "C"').fetchall()
            self.assertEqual(rows,expected)
            self.assertEqual(reader.reserve.call_count,3)  # Plan and two remaining pages.
            reader.reserve.reset_mock()
            self.assertEqual(cache.read_partition(reader,query,(),['source','v1']),expected)
            reader.reserve.assert_called_once_with(PLAN_ALLOWANCE)
            reader.reserve.reset_mock()
            self.assertEqual(cache.read_partition(reader,query,(),['source','new fingerprint']),expected)
            self.assertEqual(reader.reserve.call_count,4)
