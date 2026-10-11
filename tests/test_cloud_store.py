"""Synthetic page failures cannot advance durable request coverage."""
from datetime import date
import unittest
from sentra.daily_plan import day_jobs
from sentra.errors import SentraError


class CloudStoreTests(unittest.TestCase):
    def test_record_failure_does_not_checkpoint(self):
        from sentra.cloud_store import CloudStore
        class Backend:
            wrote_manifest=False
            def put_manifest(self,*a): self.wrote_manifest=True
            def put_records(self,*a): raise SentraError('synthetic quota stop')
        class Store(CloudStore):
            cycles=lambda *a:{}
            changed=lambda s,rs:rs
            save_progress=lambda *a: (_ for _ in ()).throw(AssertionError('checkpoint before storage'))
        b=Backend(); s=Store(b,'p02','whoop')
        job=day_jobs('whoop',date(2026,10,7))[0]
        p={'pages':0,'received':0,'seen':[],'execution_id':'test'}
        with self.assertRaises(SentraError):
            s.page(job,'',{'records':[{'id':123,'score_state':'UNSCORED'}]},b'{"records":[]}','',p)
        self.assertTrue(b.wrote_manifest)

    def test_same_page_can_checkpoint_empty_result(self):
        from sentra.cloud_store import CloudStore
        class Backend:
            def put_manifest(self,*a): pass
        class Store(CloudStore):
            def save_progress(self,j,p,*,complete=False): self.saved=(p,complete)
        s=Store(Backend(),'p02','whoop'); job=day_jobs('whoop',date(2026,10,7))[0]
        counts=s.page(job,'',{'records':[]},b'{"records":[]}','',{'pages':0,'received':0,'seen':[],'execution_id':'test'})
        self.assertEqual(counts,{'changed':0,'unchanged':0})
        self.assertEqual(s.saved[0]['status'],'complete'); self.assertTrue(s.saved[1])

    def test_malformed_whoop_missing_records_cannot_mean_empty_coverage(self):
        from sentra.cloud_store import CloudStore
        s=CloudStore(object(),'p02','whoop')
        with self.assertRaises(SentraError):
            s.page(day_jobs('whoop',date(2026,10,7))[0],'',{},b'{}','',{'pages':0,'received':0,'seen':[]})
