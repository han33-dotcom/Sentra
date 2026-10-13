"""Synthetic pagination, crash recovery and independent provider outcomes."""
from datetime import date
import unittest
from sentra.daily_plan import day_jobs
from sentra.errors import SentraError


class CloudCollectTests(unittest.TestCase):
    def module(self):
        try:
            from sentra import cloud_collect
            return cloud_collect
        except ImportError: self.fail('Cloud collector not implemented')

    def test_progress_follows_page_storage_and_fresh_process_resumes(self):
        m=self.module(); job=day_jobs('whoop',date(2026,10,7))[2]
        class Store:
            current=None; durable=[]; fail=True
            def progress(self,j): return self.current
            def start(self,j,execution):
                if self.current is None: self.current={'cursor':'','seen':[],'pages':0,'received':0,'status':'running','execution_id':execution}
                return self.current
            def page(self,j,cursor,payload,body,next_cursor,progress):
                if cursor and self.fail: raise SentraError('synthetic storage failure')
                self.durable.append(cursor)
                self.current={**progress,'cursor':next_cursor,'pages':progress['pages']+1,
                              'status':'running' if next_cursor else 'complete'}
                return {'changed':1,'unchanged':0}
            def failed(self,j,message,outcome='failed'): self.current['status']='failed'
        store=Store(); fetched=[]
        def fetch(j,c):
            fetched.append(c)
            return {'records':[],'next_token':'page2' if not c else None},b'{"synthetic":true}'
        with self.assertRaises(SentraError): m.collect_job(store,job,fetch,'run1')
        self.assertEqual(store.current['cursor'],'page2')
        self.assertEqual(store.durable,[''])
        store.fail=False
        self.assertEqual(m.collect_job(store,job,fetch,'run2')['status'],'complete')
        self.assertEqual(fetched,['','page2','page2'])
        before=list(fetched)
        self.assertEqual(m.collect_job(store,job,fetch,'run2')['status'],'skipped')
        self.assertEqual(fetched,before)

    def test_invalid_or_looping_cursor_does_not_checkpoint(self):
        m=self.module(); job=day_jobs('whoop',date(2026,10,7))[2]
        class Store:
            wrote=False
            def progress(self,j): return None
            def start(self,j,e): return {'cursor':'repeat','seen':[],'pages':0,'status':'running','execution_id':e}
            def page(self,*args): self.wrote=True
            def failed(self,*args): pass
        for cursor in ('repeat',42):
            store=Store()
            with self.assertRaises(SentraError): m.collect_job(store,job,lambda *args:({'records':[],'next_token':cursor},b'{}'),'run')
            self.assertFalse(store.wrote)

    def test_one_provider_failure_does_not_prevent_the_other(self):
        m=self.module(); calls=[]
        def run(provider):
            calls.append(provider)
            if provider=='google_health': raise SentraError('synthetic reconnect required')
            return {'status':'succeeded'}
        result=m.independent_providers(['google_health','whoop'],run)
        self.assertEqual(calls,['google_health','whoop'])
        self.assertEqual(result[0]['status'],'failed')
        self.assertEqual(result[1]['status'],'succeeded')

    def test_unexpected_provider_exception_is_sanitized_and_other_runs(self):
        m=self.module(); calls=[]
        def run(provider):
            calls.append(provider)
            if provider=='google_health': raise ValueError('synthetic sensitive payload')
            return {'status':'succeeded'}
        result=m.independent_providers(['google_health','whoop'],run)
        self.assertEqual(calls,['google_health','whoop'])
        self.assertEqual(result[0]['status'],'failed')
        self.assertNotIn('sensitive payload',result[0]['message'])
