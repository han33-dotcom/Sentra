import json,unittest
from contextlib import nullcontext
from types import SimpleNamespace
from cryptography.fernet import Fernet
from sentra.errors import SentraError

class HandoffTests(unittest.TestCase):
    def test_interrupted_handoff_resumes_without_overwriting_rotated_cloud_token(self):
        from sentra.cloud_setup import handoff
        key=Fernet(Fernet.generate_key()); c=SimpleNamespace(provider='whoop',participant_id='p9999',agreed=True,client_id='synthetic',client_secret='synthetic',redirect_uri='http://localhost:8765/callback',publishing_status='unknown')
        class Repo:
            row=None; fail=True
            def lock(self,*a): return nullcontext()
            def read(self,*a,required=True): return self.row
            def insert(self,pid,provider,b,status): self.row={'encrypted_token_bundle':b,'version':1,'refresh_status':status}
            def write(self,pid,provider,b,status,version):
                if self.fail and status=='active': raise SentraError('synthetic disconnect')
                self.row={'encrypted_token_bundle':b,'version':version+1,'refresh_status':status}
        class Local:
            lock=nullcontext(); value={'refresh_token':'synthetic'}
            def read(self): return dict(self.value)
            def write(self,value): self.value=value
        r=Repo(); v=Local()
        with self.assertRaises(SentraError): handoff(r,c,v,key)
        self.assertTrue(v.value['cloud_owned']); self.assertEqual(r.row['refresh_status'],'handoff_pending')
        r.fail=False; handoff(r,c,v,key)
        value=json.loads(key.decrypt(r.row['encrypted_token_bundle'])); value['token']['refresh_token']='rotated'
        r.row['encrypted_token_bundle']=key.encrypt(json.dumps(value).encode())
        handoff(r,c,v,key)
        self.assertEqual(json.loads(key.decrypt(r.row['encrypted_token_bundle']))['token']['refresh_token'],'rotated')
        self.assertNotIn('cloud_owned',value['token'])

    def test_local_authorization_is_blocked_for_cloud_owned_copy(self):
        from sentra.auth import authorize
        from unittest.mock import patch
        c=SimpleNamespace(provider='whoop',agreed=True)
        v=SimpleNamespace(lock=nullcontext(),read=lambda:{'cloud_owned':True})
        with patch('sentra.auth.webbrowser.open') as opened,self.assertRaisesRegex(SentraError,'cloud'):
            authorize(c,v)
        opened.assert_not_called()

    def test_reconnect_keeps_durable_ownership_before_and_after_new_token_write(self):
        from sentra.cloud_cli import reconnect
        from unittest.mock import patch
        key=Fernet(Fernet.generate_key())
        c=SimpleNamespace(provider='whoop',participant_id='p9999',agreed=True,client_id='synthetic',client_secret='synthetic',redirect_uri='http://localhost:8765/callback',publishing_status='unknown')
        class Repo:
            row={'encrypted_token_bundle':b'synthetic','version':1,'refresh_status':'active'}
            def lock(self,*a): return nullcontext()
            def read(self,*a): return dict(self.row)
            def write(self,pid,provider,b,status,version): self.row=dict(encrypted_token_bundle=b,version=version+1,refresh_status=status)
        class Local:
            lock=nullcontext(); value={'cloud_owned':True,'refresh_token':'old'}
            def read(self): return dict(self.value)
            def write(self,value): self.value=value
        for was_owned,interrupted_after_write in ((True,False),(True,True),(False,False),(False,True)):
            repo=Repo(); local=Local(); persisted=[]
            local.value={**local.value,'cloud_owned':was_owned}
            def abrupt(c,v):
                if interrupted_after_write: v.write({'refresh_token':'new'})
                persisted.append(dict(local.value)) # State a hard process kill would leave; no finally executes in reality.
                raise BaseException('synthetic abrupt stop')
            with patch('sentra.cloud_cli.authorize',side_effect=abrupt),self.assertRaises(BaseException):
                reconnect(repo,c,local,key)
            self.assertTrue(persisted[0].get('cloud_owned'))
            self.assertEqual(repo.row['refresh_status'],'reconnect_pending')
