"""Operator-only, resumable credential handoff; no health data in configuration."""
from dataclasses import asdict
import json
from pathlib import Path
from cryptography.fernet import Fernet
from .config import require_agreement
from .errors import SentraError
from .shared_config import read_shared
from .vault import atomic_write


def connection_payload(c):
    return {name:getattr(c,name) for name in ('provider','participant_id','agreed','client_id','client_secret','redirect_uri','publishing_status')}


def handoff(repository,c,local,cipher):
    require_agreement(c)
    with repository.lock(c.participant_id,c.provider),local.lock:
        row=repository.read(c.participant_id,c.provider,required=False); token=local.read()
        if row and row['refresh_status']=='reconnect_pending':
            raise SentraError('Reconnect unfinished; repeat cloud-connect --reauthorize.')
        if row and row['refresh_status']!='handoff_pending':
            if not token.get('cloud_owned'): raise SentraError('Cloud/local ownership conflict; inspect before reconnecting.')
            return # Never overwrite an active, potentially rotated token from a stale laptop copy.
        if not token.get('cloud_owned'):
            value={'connection':connection_payload(c),'token':token}
            body=cipher.encrypt(json.dumps(value).encode())
            if row: repository.write(c.participant_id,c.provider,body,'handoff_pending',row['version'])
            else: repository.insert(c.participant_id,c.provider,body,'handoff_pending')
            local.write({**token,'cloud_owned':True})
        elif not row:
            raise SentraError('Cloud-owned marker exists without cloud credentials; inspect cloud state/key.')
        row=repository.read(c.participant_id,c.provider)
        repository.write(c.participant_id,c.provider,row['encrypted_token_bundle'],'active',row['version'])


def prepare(config,local_cipher):
    credentials,limits,private=read_shared(config,local_cipher)
    file=private/'cloud'/'setup.enc'
    if file.exists(): value=json.loads(local_cipher.decrypt(file.read_bytes()))
    else: value={'token_key':Fernet.generate_key().decode(),'version':1}
    if value.get('config') and value['config']['credentials']['url']!=credentials['url']:
        raise SentraError('Cloud key belongs to another project; preserve it and review configuration.')
    certificate=Path(credentials['db']['sslrootcert']).read_text(encoding='utf-8')
    credentials=json.loads(json.dumps(credentials)); credentials['db'].pop('sslrootcert')
    from .config import load_connection
    connections=[load_connection(config,p,require_client=False) for p in ('google_health','whoop')]
    for c in connections: require_agreement(c)
    value['config']={'credentials':credentials,'certificate_pem':certificate,'limits':asdict(limits),
                     'confirmed_free_plan':True,'participants':{c.provider:c.participant_id for c in connections}}
    atomic_write(file,local_cipher.encrypt(json.dumps(value).encode()))
    return value


def read_setup(config,cipher):
    _,_,private=read_shared(config,cipher)
    try: return json.loads(cipher.decrypt((private/'cloud'/'setup.enc').read_bytes()))
    except Exception: raise SentraError('Cloud setup missing/unreadable; run cloud-prepare first.') from None
