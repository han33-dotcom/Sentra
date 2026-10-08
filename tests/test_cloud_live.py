"""Opt-in hosted checks; synthetic data only, rolled back, no original upload."""
from datetime import date
import json,os,unittest
from pathlib import Path
from unittest.mock import patch
from sentra.cloud_store import CloudStore
from sentra.cloud_tokens import TokenRepository
from sentra.daily_plan import day_jobs
from sentra.errors import SentraError
from sentra.shared_backend import SharedBackend,connect_db
from sentra.shared_config import read_shared
from sentra.vault import local_cipher

@unittest.skipUnless(os.environ.get('SENTRA_TEST_CLOUD')=='1','opt-in synthetic shared database check')
class CloudLiveTests(unittest.TestCase):
    def test_checkpoint_semantic_noop_correction_and_lock(self):
        credentials,limits,_=read_shared(Path('config/local.toml'),local_cipher())
        b=SharedBackend(credentials,limits)
        try:
            b.reserve_external(10_000_000); b.lock()
            if b.db.execute("select 1 from audit.participants where participant_id='p9999'").fetchone():
                self.skipTest('synthetic ID already in use')
            with b.db.transaction(force_rollback=True),patch.object(b.storage,'put'):
                b.db.execute("insert into audit.participants(participant_id) values ('p9999')")
                s=CloudStore(b,'p9999','whoop'); j=next(j for j in day_jobs('whoop',date(2026,10,7)) if j.dataset=='sleep')
                p=s.start(j,'synthetic1')
                raw={'id':'synthetic','start':'2026-10-07T00:00:00Z','end':'2026-10-07T01:00:00Z','score_state':'SCORED',
                     'score':{'average_heart_rate':70.12345678901234,'max_heart_rate':90}}
                payload={'records':[raw]}; body=json.dumps(payload).encode()
                self.assertEqual(s.page(j,'',payload,body,'page2',p)['changed'],1)
                self.assertEqual(s.states(),{}) # More pages remain; no interval claim.
                durable=s.progress(j)
                with patch.object(b,'put_records',side_effect=SentraError('synthetic storage failure')):
                    corrected=json.loads(body); corrected['records'][0]['score']['average_heart_rate']=71
                    with self.assertRaises(SentraError): s.page(j,'page2',corrected,json.dumps(corrected).encode(),'',durable)
                self.assertEqual(s.progress(j)['cursor'],'page2'); self.assertEqual(s.states(),{})
                self.assertEqual(s.page(j,'page2',payload,body,'',durable)['unchanged'],1)
                self.assertEqual(s.progress(j)['status'],'complete')
                self.assertEqual(s.states()['sleep'][0]['requested_civil_end'],'2026-10-08')
                before=b.db.execute("select source_response_id,collected_at from audit.records where participant_id='p9999'").fetchone()
                p=s.start(j,'synthetic2'); self.assertEqual(s.page(j,'',payload,body,'',p)['changed'],0)
                self.assertEqual(before,b.db.execute("select source_response_id,collected_at from audit.records where participant_id='p9999'").fetchone())
                corrected['records'][0]['score'].pop('max_heart_rate')
                p=s.start(j,'synthetic3'); self.assertEqual(s.page(j,'',corrected,json.dumps(corrected).encode(),'',p)['changed'],1)
                b.verify_content('p9999','whoop'); b.verify_projections('p9999','whoop')
                self.assertEqual(b.db.execute("select count(*) from audit.measurements where participant_id='p9999' and metric='/score/max_heart_rate'").fetchone()[0],0)
                repo=TokenRepository(b.db)
                repo.insert('p9999','whoop',b'synthetic-no-real-token','active')
                repo.write('p9999','whoop',b'synthetic-new-token','refresh_pending',1)
                self.assertEqual(repo.read('p9999','whoop')['version'],2)
                self.assertEqual(b.db.execute("select authorization_status from audit.connection_state where participant_id='p9999'").fetchone()[0],'reconnect_required')
                with self.assertRaises(SentraError): repo.write('p9999','whoop',b'synthetic','active',1)
                repo.write('p9999','whoop',b'synthetic-final','active',2)
                self.assertEqual(b.db.execute("select authorization_status from audit.connection_state where participant_id='p9999'").fetchone()[0],'authorized')
                other=connect_db(credentials)
                try:
                    with TokenRepository(b.db).lock('p9999','whoop'):
                        with self.assertRaises(SentraError):
                            with TokenRepository(other).lock('p9999','whoop'): pass
                    with TokenRepository(other).lock('p9999','whoop'): pass
                finally: other.close()
            self.assertIsNone(b.db.execute("select 1 from audit.participants where participant_id='p9999'").fetchone())
        finally: b.close()
