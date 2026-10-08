"""Synthetic rotation, ambiguous persistence and ownership boundaries."""
from contextlib import nullcontext
from types import SimpleNamespace
import json,time,unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from sentra.auth import access_token
from sentra.errors import SentraError


class CloudTokenTests(unittest.TestCase):
    def vault(self):
        try:
            from sentra.cloud_tokens import CloudTokenVault
        except ImportError: self.fail('Cloud token vault not implemented')
        cipher=Fernet(Fernet.generate_key())
        connection=SimpleNamespace(provider='whoop',participant_id='p9999',agreed=True,client_id='synthetic',client_secret='synthetic')
        token={'access_token':'old-synthetic','refresh_token':'old-refresh','expires_at':0,'scope':['offline'],
               'authorized_at':1,'reconnect_required':False}
        class Repo:
            row={'encrypted_token_bundle':cipher.encrypt(json.dumps({'connection':vars(connection),'token':token}).encode()),'version':1,'refresh_status':'active'}
            writes=0; fail_final=False
            def lock(self,*args): return nullcontext()
            def read(self,*args): return dict(self.row)
            def write(self,pid,provider,body,status,version):
                if version!=self.row['version']: raise SentraError('Concurrent token update')
                self.writes+=1
                if self.fail_final and self.writes==2: raise SentraError('Synthetic persist failure')
                self.row=dict(encrypted_token_bundle=body,version=version+1,refresh_status=status)
        repo=Repo()
        return CloudTokenVault(repo,'p9999','whoop',cipher),repo,connection

    def test_rotated_token_is_saved_before_return_and_used_after_fresh_process(self):
        v,repo,c=self.vault()
        result=SimpleNamespace(status_code=200,json=lambda:{'access_token':'new-synthetic','refresh_token':'new-refresh','expires_in':3600})
        with patch('sentra.auth.requests.post',return_value=result): self.assertEqual(access_token(c,v),'new-synthetic')
        self.assertEqual(repo.writes,2)
        self.assertEqual(v.read()['refresh_token'],'new-refresh')
        self.assertEqual(repo.row['refresh_status'],'active')

    def test_ambiguous_rotation_or_final_persistence_requires_reconnect(self):
        for fail_final in (False,True):
            v,repo,c=self.vault(); repo.fail_final=fail_final
            result=SimpleNamespace(status_code=200,json=lambda:{'access_token':'new','refresh_token':'new-refresh','expires_in':3600})
            kwargs={'return_value':result} if fail_final else {'side_effect':TimeoutError('synthetic')}
            with patch('sentra.auth.requests.post',**kwargs),self.assertRaises(SentraError): access_token(c,v)
            self.assertTrue(v.read()['reconnect_required'])
            with patch('sentra.auth.requests.post') as request,self.assertRaises(SentraError): access_token(c,v)
            request.assert_not_called()

    def test_local_cloud_owned_copy_cannot_refresh_stale_tokens(self):
        _,_,c=self.vault()
        v=SimpleNamespace(lock=nullcontext(),read=lambda:{'cloud_owned':True,'expires_at':0})
        with patch('sentra.auth.requests.post') as request,self.assertRaisesRegex(SentraError,'cloud'):
            access_token(c,v)
        request.assert_not_called()
