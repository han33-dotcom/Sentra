"""Synthetic shared-storage boundary checks; never real participant fixtures."""
import importlib
import gzip
import requests
from types import SimpleNamespace
from contextlib import nullcontext
import unittest


class SharedTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('sentra.shared')
        except ModuleNotFoundError:
            self.fail('Stage 3 shared-storage module not implemented')

    def test_capacity_reserve_and_unknown_usage_fail_closed(self):
        m = self.module()
        limits = m.Limits(database_bytes=350_000_000, object_bytes=700_000_000,
                          monthly_egress_bytes=3_500_000_000, reserve_bytes=20_000_000)
        limits.check({'database_bytes': 328_000_000, 'object_bytes': 1, 'egress_bytes': 1}, database_add=1_000_000)
        for usage in ({'database_bytes': 330_000_000, 'object_bytes': 1, 'egress_bytes': 1},
                      {'database_bytes': 1, 'object_bytes': 1, 'egress_bytes': None}):
            with self.assertRaises(m.CapacityStop):
                limits.check(usage, database_add=1)

    def test_thresholds_cannot_exceed_free_allowances(self):
        m = self.module()
        for kwargs in ({'database_bytes': 500_000_000}, {'object_bytes': 1_000_000_000},
                       {'monthly_egress_bytes': 5_000_000_000}, {'reserve_bytes': -1}):
            with self.assertRaises(m.SentraError):
                m.Limits(**kwargs)

    def test_object_key_separates_participant_and_requires_hash(self):
        m = self.module()
        self.assertEqual(m.object_key('whoop', 'p02', 'a' * 64), 'whoop/p02/' + 'a' * 64 + '.json.gz')
        for provider, participant, digest in [('x', 'p02', 'a' * 64), ('whoop', '../p01', 'a' * 64), ('whoop', 'p02', '../bad')]:
            with self.assertRaises(m.SentraError):
                m.object_key(provider, participant, digest)

    def test_signature_preserves_unknown_fields_and_changes(self):
        m = self.module()
        record = {'record_key': '1', 'dataset': 'cycle', 'vendor_fields': {'new': 7}, 'measurements': []}
        self.assertEqual(m.signature(record), m.signature(dict(reversed(list(record.items())))))
        self.assertNotEqual(m.signature(record), m.signature({**record, 'vendor_fields': {'new': 8}}))

    def test_access_denial_requires_provider_permission_evidence(self):
        cli = importlib.import_module('sentra.shared_cli')
        for code in (429,500,503):
            with self.assertRaises(self.module().SentraError):
                cli.expect_denial(code,b'{"error":"Unavailable"}',kind='write')
        with self.assertRaises(self.module().SentraError):
            cli.expect_denial(400,b'{"error":"InvalidRequest"}',kind='write')
        cli.expect_denial(400,b'{"statusCode":"403","error":"Unauthorized","message":"new row violates row-level security policy"}',kind='write')
        cli.expect_denial(404,b'{"statusCode":"404","error":"Bucket not found"}',kind='anonymous')

    def test_setup_adopts_user_after_ambiguous_creation(self):
        setup = importlib.import_module('sentra.shared_setup')
        state = {'id':None,'posts':0}
        db = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: (state['id'],) if state['id'] else None))
        def post(*args,**kwargs):
            state.update(id='00000000-0000-0000-0000-000000000001',posts=state['posts']+1)
            raise requests.Timeout('synthetic ambiguous response')
        http = SimpleNamespace(post=post)
        account = {'email':'synthetic@sentra.invalid','storage_password':'synthetic-password'}
        admin = {'url':'https://example.supabase.co','secret_key':'synthetic-key'}
        with self.assertRaises(self.module().SentraError): setup.get_or_create_storage_user(db,admin,account,http=http)
        user = setup.get_or_create_storage_user(db,admin,account,http=http)
        self.assertEqual(user,state['id'])
        self.assertEqual(state['posts'],1)

    def test_database_estimate_uses_lossless_shared_context(self):
        m = self.module()
        from sentra.local_store import compact_record,expanded_record
        context = {'record_key':'synthetic','vendor_time':{'interval':'x'*200},'source_pointer':'/records/0'}
        record = {**context,'vendor_fields':{'new_unknown_field':7},'measurements':[
            {**context,'metric':f'/score/x{i}','vendor_metric':f'/score/x{i}','vendor_value':i,'source_pointer':f'/records/0/score/x{i}'} for i in range(50)]}
        self.assertEqual(m.signature(record),m.signature(expanded_record(compact_record(record))))
        self.assertLess(m.database_estimate(record),len(importlib.import_module('sentra.datasets').canonical(record).encode())*10+50*2048)

    def test_sync_does_not_advance_state_after_failed_write_and_resumes(self):
        sync = importlib.import_module('sentra.shared_sync')
        m = self.module()
        record = {'participant_id':'p02','provider':'whoop','dataset':'cycle','record_key':'1',
                  'measurements':[], 'vendor_fields':{'unknown':7}}
        class Store:
            lock = private_lock = nullcontext()
            connection = SimpleNamespace(participant_id='p02',provider='whoop')
            db = SimpleNamespace(execute=lambda *args: [])
            def reload(self): pass
            def manifests(self): return [{'response_id':'m'}]
            def original_bytes(self, manifest): return b'{"records":[]}'
            def iter_records(self): return iter([record])
        class Backend:
            failed = True
            hashes = {}
            manifests = set()
            advanced = False
            def lock(self): pass
            def unlock(self): pass
            def has_manifest(self, key): return key in self.manifests
            def put_manifest(self, manifest, body):
                assert gzip.decompress(body) == b'{"records":[]}'
                self.manifests.add(manifest['response_id'])
            def record_hashes(self, *args): return dict(self.hashes)
            def put_records(self, records):
                if records and self.failed:
                    raise m.SentraError('simulated interrupted transaction')
                for r in records: self.hashes[r['record_key']] = m.signature(r)
            def save_state(self, *args): self.advanced = True
            def counts(self, *args): return {}
            def usage(self): return {}
        backend = Backend()
        with self.assertRaises(m.SentraError): sync.sync_store(Store(),backend)
        self.assertFalse(backend.advanced)
        backend.failed = False
        result = sync.sync_store(Store(),backend)
        self.assertTrue(backend.advanced)
        self.assertEqual(result['uploaded_manifests'],0)
        self.assertEqual(result['changed_records'],1)
        again = sync.sync_store(Store(),backend)
        self.assertEqual((again['changed_records'],again['unchanged_records']),(0,1))
        backend.hashes = {}
        store = Store()
        store.iter_records = lambda: iter([{**record,'record_key':'2'}, {**record,'dataset':'sleep','record_key':'3'}])
        multiple = sync.sync_store(store,backend)
        self.assertEqual(multiple['changed_records'],2)


if __name__ == '__main__':
    unittest.main()
