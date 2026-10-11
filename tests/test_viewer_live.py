"""Opt-in synthetic viewer filter/permissions transaction; rolls all health writes back."""
from datetime import date
import os
from pathlib import Path
import unittest

import psycopg
from psycopg.types.json import Jsonb

from sentra.shared_config import read_shared
from sentra.shared_backend import connect_db
from sentra.shared_setup import read_admin
from sentra.vault import local_cipher


@unittest.skipUnless(os.environ.get('SENTRA_LIVE_TESTS')=='1','opt-in synthetic viewer transaction')
class ViewerLiveTests(unittest.TestCase):
    def test_egress_reservation_survives_rolled_back_read_transaction(self):
        from sentra.viewer_reader import ViewerReader
        credentials,limits,_=read_shared(Path('config/local.toml'),local_cipher(),role='viewer')
        viewer=ViewerReader(credentials,limits,lambda:'synthetic-test')
        try:
            before=viewer.usage()['egress_bytes']
            with viewer.db.transaction(force_rollback=True):
                viewer.reserve(123456)
            after=viewer.usage()['egress_bytes']
            self.assertGreaterEqual(after-before,123456+32768)
        finally:viewer.close()

    def test_selected_civil_point_interval_search_and_permissions(self):
        from sentra.viewer_reader import ViewerReader, Selection
        credentials,limits,private=read_shared(Path('config/local.toml'),local_cipher(),role='viewer')
        viewer=ViewerReader(credentials,limits,lambda:'synthetic-test')
        admin=connect_db(read_admin(private))
        try:
            # Reserve outside rollback: test network use remains in the conservative ledger.
            viewer.reserve(2_000_000)
            self.assertFalse(viewer.usage()['observation']['enabled'])
            for query in ('select * from collector_private.provider_credentials limit 0',
                          'update audit.measurements set value=0 where false',
                          'select * from collector_private.observation_control limit 0'):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): viewer.db.execute(query)
            if admin.execute("select 1 from audit.participants where participant_id='p9998'").fetchone():
                self.skipTest('reserved synthetic participant already exists')
            with admin.transaction(force_rollback=True):
                admin.execute('set transaction isolation level repeatable read')
                admin.execute("insert into audit.participants(participant_id) values ('p9998')")
                source='b'*64
                admin.execute('''insert into audit.raw_response_manifest values (%s,'p9998','google_health','daily_steps',
                  'synthetic',%s,'synthetic',now(),'synthetic-not-uploaded',%s,1,%s)''',(source,Jsonb({}),source,Jsonb({})))
                points=[('civil',None,None,None,{'year':2026,'month':10,'day':7}),
                        ('nested',None,None,None,{'date':{'year':2026,'month':10,'day':7},'time':{}}),
                        ('start','2026-10-06T21:00:00Z',None,None,None),
                        ('outside','2026-10-07T21:00:00Z',None,None,None),
                        ('sleep',None,'2026-10-06T19:00:00Z','2026-10-07T05:00:00Z',None)]
                for key,point,start,end,civil in points:
                    admin.execute('''insert into audit.records values ('p9998','google_health','daily_steps',%s,%s,%s,%s,now())''',
                                  (key,source,Jsonb({'provisional':True}),source))
                    admin.execute('''insert into audit.measurements values ('p9998','google_health','daily_steps',%s,
                     '/synthetic',123,'steps',%s,'steps','vendor_summary','available',%s,%s,%s,%s,
                     'synthetic',%s,now(),60,'synthetic',%s,'/synthetic')''',
                     (key,Jsonb(123),point,start,end,Jsonb(civil),Jsonb({}),source))
                class SyntheticReader(ViewerReader):
                    def reserve(self,amount): viewer.reserve(amount)
                reader=SyntheticReader(credentials,limits,lambda:'synthetic-test',db=admin)
                # Supabase's postgres is not superuser and cannot SET ROLE to the
                # restricted login. Test SQL with rolled-back admin fixtures;
                # independently verify permissions with the real viewer above.
                f=Selection('p9998','google_health','daily_steps',date(2026,10,7),date(2026,10,8))
                rows=reader.measurements(f)
                self.assertEqual({r['record_key'] for r in rows},{'civil','nested','start','sleep'})
                empty=reader.measurements(Selection('p9998','google_health','daily_steps',date(2026,10,7),date(2026,10,8),search="%' OR true --_"))
                self.assertEqual(empty,[])
            self.assertIsNone(admin.execute("select 1 from audit.participants where participant_id='p9998'").fetchone())
        finally:
            viewer.close();admin.close()
