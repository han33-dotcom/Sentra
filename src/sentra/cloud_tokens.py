"""Separate-key cloud credentials, serialized refresh and versioned persistence."""
from contextlib import contextmanager
import hashlib,json
from types import SimpleNamespace
from cryptography.fernet import InvalidToken

from .errors import SentraError


class TokenRepository:
    def __init__(self,db): self.db=db

    @contextmanager
    def lock(self,pid,provider):
        key=int.from_bytes(hashlib.sha256(f'sentra-token/{pid}/{provider}'.encode()).digest()[:8],'big',signed=True)
        if not self.db.execute('select pg_try_advisory_lock(%s)',(key,)).fetchone()[0]:
            raise SentraError('Provider authorization is busy; retry after the active process finishes.')
        try: yield
        finally: self.db.execute('select pg_advisory_unlock(%s)',(key,))

    def read(self,pid,provider,*,required=True):
        row=self.db.execute('select encrypted_token_bundle,version,refresh_status from collector_private.provider_credentials where participant_id=%s and provider=%s',(pid,provider)).fetchone()
        if not row:
            if not required: return None
            raise SentraError('Cloud connection missing; run cloud-connect for this participant.')
        return dict(encrypted_token_bundle=bytes(row[0]),version=row[1],refresh_status=row[2])

    def insert(self,pid,provider,body,status):
        self.db.execute('insert into collector_private.provider_credentials values (%s,%s,%s,%s,1,%s,now())',
                        (pid,provider,body,'cloud-v1',status))

    def write(self,pid,provider,body,status,version):
        with self.db.transaction():
            result=self.db.execute('''update collector_private.provider_credentials set encrypted_token_bundle=%s,
              version=version+1,refresh_status=%s,updated_at=now() where participant_id=%s and provider=%s and version=%s''',
              (body,status,pid,provider,version))
            if result.rowcount!=1: raise SentraError('Cloud credential version changed; stop and inspect authorization.')
            self.db.execute('update audit.connection_state set authorization_status=%s,updated_at=now() where participant_id=%s and provider=%s',
                            ('authorized' if status=='active' else 'reconnect_required',pid,provider))


class CloudTokenVault:
    def __init__(self,repository,pid,provider,cipher):
        self.repository,self.pid,self.provider,self.cipher=repository,pid,provider,cipher

    @property
    def lock(self): return self.repository.lock(self.pid,self.provider)

    def envelope(self):
        row=self.repository.read(self.pid,self.provider)
        if row['refresh_status'] in ('handoff_pending','reconnect_pending'):
            raise SentraError('Cloud authorization handoff/reconnect incomplete; repeat the operator command.')
        try:
            value=json.loads(self.cipher.decrypt(row['encrypted_token_bundle']))
            c=value['connection']; token=value['token']
            if c['provider']!=self.provider or c['participant_id']!=self.pid or c.get('agreed') is not True or not isinstance(token,dict): raise ValueError
        except (ValueError,KeyError,TypeError,InvalidToken):
            raise SentraError('Cloud authorization cannot be decrypted/validated; inspect cloud key or reconnect.') from None
        return row,value

    def connection(self): return SimpleNamespace(**self.envelope()[1]['connection'])

    def read(self): return self.envelope()[1]['token']

    def write(self,token):
        row,value=self.envelope(); value['token']=token
        self.repository.write(self.pid,self.provider,self.cipher.encrypt(json.dumps(value).encode()),
                              'refresh_pending' if token.get('reconnect_required') else 'active',row['version'])
