"""Operator setup and reconnect commands; scheduled runtime has no admin key."""
from datetime import date
import hashlib,json,os,subprocess,sys
from pathlib import Path
from psycopg.types.json import Jsonb
from filelock import FileLock
from cryptography.fernet import Fernet
from .auth import authorize
from .cloud_setup import prepare,read_setup,handoff,connection_payload
from .cloud_tokens import TokenRepository
from .config import load_connection,require_agreement
from .errors import SentraError
from .daily_plan import collection_control
from .shared_backend import connect_db,SharedBackend
from .shared_config import read_shared
from .shared_setup import read_admin
from .vault import local_cipher,TokenVault


def add_commands(sub):
    sub.add_parser('cloud-prepare',help='Deploy additive daily-state schema and prepare separate encrypted cloud key/config')
    sub.add_parser('cloud-github-secrets',help='Configure private repository secrets with schedule paused; no commits/pushes')
    p=sub.add_parser('cloud-connect',help='Move credential ownership to hosted state, or reconnect under cloud/local locks')
    p.add_argument('provider',choices=('google_health','whoop'))
    p.add_argument('--reauthorize',action='store_true')
    p=sub.add_parser('cloud-run-local',help='Launch the same isolated environment-based collector used by Actions')
    p.add_argument('--mode',choices=('daily','initial','recovery'),default='daily')
    p.add_argument('--provider',choices=('all','google_health','whoop'),default='all')
    p.add_argument('--start',type=date.fromisoformat); p.add_argument('--end',type=date.fromisoformat)
    p.add_argument('--dataset')
    p=sub.add_parser('cloud-window',help='Approved ongoing daily collection, bounded legacy window, or pause')
    p.add_argument('--start',type=date.fromisoformat)
    p.add_argument('--ongoing',action='store_true',help='No automatic end date; quota/auth gates and explicit pause still apply')
    p.add_argument('--pause',action='store_true')
    p.add_argument('--approved',action='store_true',help='Operator confirms human approval of published collection controls')


def install_schema(private):
    db=connect_db(read_admin(private))
    try:
        if not db.execute('select pg_try_advisory_lock(735003)').fetchone()[0]: raise SentraError('Shared writer is busy; repeat cloud-prepare later.')
        file=Path(__file__).resolve().parents[2]/'sql'/'004_daily_collection.sql'
        text=file.read_text(encoding='utf-8'); digest=hashlib.sha256(text.encode()).hexdigest()
        row=db.execute('select sha256 from collector_private.schema_versions where version=%s',(file.name,)).fetchone()
        if row:
            if row[0]!=digest: raise SentraError('Installed daily schema differs; use a new migration instead of resetting.')
            return
        # Marker and additive schema commit together; no quota baseline is reset/reverified here.
        from psycopg import sql
        marker=sql.SQL('insert into collector_private.schema_versions values ({},{}); commit;').format(sql.Literal(file.name),sql.Literal(digest))
        db.execute(text.rstrip().removesuffix('commit;')+marker.as_string(db))
    finally: db.close()


def reconnect(repo,c,vault,cipher):
    require_agreement(c)
    with repo.lock(c.participant_id,c.provider),vault.lock:
        row=repo.read(c.participant_id,c.provider)
        vault.write({**vault.read(),'cloud_owned':True})
        repo.write(c.participant_id,c.provider,row['encrypted_token_bundle'],'reconnect_pending',row['version'])
        class ReconnectVault:
            # Only this locked operator adapter may bypass the ordinary local guard.
            # Every durable write keeps ownership true, including after a hard kill.
            lock=vault.lock
            def read(self):
                token=vault.read(); token.pop('cloud_owned',None); return token
            def write(self,token): vault.write({**token,'cloud_owned':True})
        authorize(c,ReconnectVault())
        token=ReconnectVault().read()
        body=cipher.encrypt(json.dumps({'connection':connection_payload(c),'token':token}).encode())
        row=repo.read(c.participant_id,c.provider)
        repo.write(c.participant_id,c.provider,body,'handoff_pending',row['version'])
        row=repo.read(c.participant_id,c.provider)
        repo.write(c.participant_id,c.provider,body,'active',row['version'])


def run_command(args):
    # Reject ambiguous operator input before connecting or consuming quota.
    if args.command=='cloud-window':
        settings=collection_control(start=args.start,pause=args.pause,approved=args.approved,ongoing=args.ongoing)
    cipher=local_cipher(); credentials,limits,private=read_shared(args.config,cipher)
    if args.command=='cloud-prepare':
        with FileLock(str(private/'cloud-setup.lock'),timeout=10):
            install_schema(private); prepare(args.config,cipher)
        print('Daily schema and separate cloud key/config ready; observation remains paused and no credentials displayed.')
        return 0
    setup=read_setup(args.config,cipher)
    if args.command=='cloud-github-secrets':
        from .cloud_github import configure
        print(json.dumps(configure(setup))); return 0
    if args.command=='cloud-run-local':
        env=dict(os.environ,SENTRA_COLLECTOR_CONFIG=json.dumps(setup['config']),SENTRA_TOKEN_KEY=setup['token_key'])
        command=[sys.executable,'-m','sentra.cloud_run','--mode',args.mode,'--provider',args.provider]
        for field in ('start','end','dataset'):
            value=getattr(args,field)
            if value is not None: command.extend(['--'+field,str(value)])
        return subprocess.run(command,env=env).returncode
    backend=SharedBackend(credentials,limits)
    try:
        backend.lock()
        # Pausing transfers no health data and must remain possible at a quota stop.
        if args.command!='cloud-window' or not args.pause:backend.reserve(65536)
        if args.command=='cloud-connect':
            c=load_connection(args.config,args.provider); require_agreement(c)
            vault=TokenVault(private,c.provider,c.participant_id,cipher)
            repo=TokenRepository(backend.db); cloud_cipher=Fernet(setup['token_key'].encode())
            backend.guard(database_add=65536)
            if args.reauthorize: reconnect(repo,c,vault,cloud_cipher)
            else: handoff(repo,c,vault,cloud_cipher)
            print(f'{c.provider}: credentials managed in encrypted cloud state; stale local copy cannot refresh. No token values displayed.')
        elif args.command=='cloud-window':
            if not args.pause:backend.guard()
            backend.db.execute('update collector_private.observation_control set settings=%s,updated_at=now() where singleton',(Jsonb(settings),))
            print(json.dumps(settings))
        return 0
    finally: backend.close()
