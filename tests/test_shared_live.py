"""Opt-in synthetic PostgreSQL checks, all audit writes rolled back.

Run: $env:SENTRA_LIVE_TESTS='1'; python -m unittest discover -s tests -p test_shared_live.py
Never read real participant rows. Use the configured least-privilege collector.
"""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from cryptography.fernet import Fernet
from psycopg.types.json import Jsonb
import psycopg

from sentra.datasets import plan_jobs
from sentra.local_store import LocalStore
from sentra.shared_backend import SharedBackend
from sentra.shared_config import read_shared
from sentra.vault import local_cipher
from sentra.errors import SentraError
from sentra.shared_backup import BackupWriter,BackupReader,restore_backup,TABLES
from sentra.shared_setup import read_admin
from sentra.shared_backend import connect_db


@unittest.skipUnless(os.environ.get('SENTRA_LIVE_TESTS') == '1','opt-in synthetic cloud transaction')
class SharedLiveTests(unittest.TestCase):
    def test_restore_refuses_populated_audit_and_rolls_back_content_mismatch(self):
        cipher=local_cipher()
        credentials,limits,private=read_shared(Path('config/local.toml'),cipher)
        backend=SharedBackend(credentials,limits)
        admin=connect_db(read_admin(private))
        try:
            with tempfile.TemporaryDirectory(dir=private) as folder:
                writer=BackupWriter(Path(folder),cipher,max_bytes=1_000_000)
                writer.write('participants-00000',b'{"participant_id":"p9999","created_at":"2026-10-01T00:00:00+00:00"}\n',rows=1)
                counts=dict.fromkeys(TABLES,0); counts['participants']=1
                fingerprints=dict.fromkeys(TABLES,'0'*64); fingerprints['participants']='f'*64
                reader=BackupReader(writer.finish({'tables':counts,'table_fingerprints':fingerprints,'objects':{}}),cipher)
                with self.assertRaisesRegex(SentraError,'empty'):
                    restore_backup(reader,backend,admin,empty_audit=True)
                before=admin.execute("select nspname from pg_namespace where nspname like 'sentra_restore_%'").fetchall()
                with self.assertRaisesRegex(SentraError,'row content'):
                    restore_backup(reader,backend,admin)
                self.assertEqual(before,admin.execute("select nspname from pg_namespace where nspname like 'sentra_restore_%'").fetchall())
        finally:
            backend.close(); admin.close()

    def test_corrections_projection_corruption_and_atomic_rollback(self):
        credentials,limits,_ = read_shared(Path('config/local.toml'),local_cipher())
        backend = SharedBackend(credentials,limits)
        try:
            backend.reserve_external(3_000_000) # Covers test queries even though inner budget writes roll back.
            backend.lock()
            if backend.db.execute("select 1 from audit.participants where participant_id='p9999'").fetchone():
                self.skipTest('reserved synthetic participant ID already in use')
            with tempfile.TemporaryDirectory() as folder:
                store = LocalStore(SimpleNamespace(provider='whoop',participant_id='p9999',private_dir=Path(folder)),Fernet(Fernet.generate_key()))
                job = next(j for j in plan_jobs('whoop',date(2026,10,1),date(2026,10,8)) if j.dataset=='sleep')
                record = {'id':'synthetic-sleep','start':'2026-10-01T00:00:00Z','end':'2026-10-01T01:00:00Z',
                          'score_state':'SCORED','score':{'average_heart_rate':70.12345678901234,'max_heart_rate':90}}
                store.start_job(job)
                payload = {'records':[record]}
                store.save_page(job,'',payload,json.dumps(payload).encode(),'')
                r = next(store.iter_records()); m = store.manifests()[0]
                with backend.db.transaction(force_rollback=True):
                    backend.db.execute("insert into audit.participants(participant_id) values ('p9999')")
                    backend.db.execute('insert into audit.raw_response_manifest values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (m['response_id'],'p9999','whoop','sleep','synthetic',Jsonb({}),'synthetic',m['collected_at'],
                         'synthetic-not-uploaded',m['content_sha256'],m['compressed_bytes'],Jsonb(m)))
                    backend.put_records([r])
                    backend.verify_projections('p9999','whoop')
                    backend.db.execute("update audit.measurements set value=999 where participant_id='p9999' and metric='/score/average_heart_rate'")
                    with self.assertRaises(SentraError): backend.verify_projections('p9999','whoop')
                    corrected = json.loads(json.dumps(r))
                    corrected['measurements'] = [x for x in corrected['measurements'] if x['metric']!='/score/max_heart_rate']
                    for x in corrected['measurements']:
                        if x['metric']=='/score/average_heart_rate': x.update(value=71,vendor_value=71)
                    backend.put_records([corrected])
                    backend.verify_projections('p9999','whoop')
                    self.assertEqual(backend.db.execute("select count(*) from audit.measurements where participant_id='p9999' and metric='/score/max_heart_rate'").fetchone()[0],0)
                    broken = json.loads(json.dumps(corrected)); broken['measurements'][0]['value_kind']='invalid_kind'
                    with self.assertRaises(psycopg.Error): backend.put_records([broken])
                    backend.verify_projections('p9999','whoop')
                    backend.db.execute("update audit.sessions set score_state='corrupt' where participant_id='p9999'")
                    with self.assertRaises(SentraError): backend.verify_projections('p9999','whoop')
                    backend.put_records([corrected])
                    # A wide vendor record must verify within a bounded statement deadline.
                    # This exposes repeated JSON expansion / quadratic metric joins.
                    wide = json.loads(json.dumps(corrected))
                    template = wide['measurements'][0]
                    wide['measurements'] = [{**template,'metric':f'/synthetic/{i}',
                                             'source_pointer':f'/records/0/synthetic/{i}'} for i in range(600)]
                    backend.put_records([wide])
                    backend.db.execute('set local statement_timeout=2000')
                    backend.verify_projections('p9999','whoop')
            self.assertIsNone(backend.db.execute("select 1 from audit.participants where participant_id='p9999'").fetchone())
        finally:
            backend.close() # Releases advisory lock, including on test failure.
