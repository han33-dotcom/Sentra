"""Stage 3 commands; no scheduled collection or browser application."""
import json
import gzip
from pathlib import Path

import psycopg
import requests

from .config import load_connection,require_agreement
from .errors import SentraError
from .local_store import LocalStore
from .providers import PROVIDERS
from .shared_backend import SharedBackend,PrivateStorage,connect_db,BUCKET
from .shared_backup import make_backup,BackupReader,restore_backup
from .shared_config import read_shared
from .shared_setup import bootstrap,read_admin,set_budget
from .shared_sync import sync_store,compare_store
from .vault import local_cipher


def add_commands(sub):
    p = sub.add_parser('shared-bootstrap',help='Deploy schema/private permissions to an existing verified Free project')
    p.add_argument('--egress-baseline-bytes',type=int,required=True)
    p = sub.add_parser('shared-budget',help='Refresh verified organization uncached-egress baseline without resetting reservations')
    p.add_argument('--egress-baseline-bytes',type=int,required=True)
    sub.add_parser('shared-status')
    sub.add_parser('shared-growth')
    sub.add_parser('shared-check-access')
    for name in ('shared-sync','shared-verify'):
        p = sub.add_parser(name)
        p.add_argument('provider',choices=[*PROVIDERS,'all'])
        if name == 'shared-verify': p.add_argument('--originals',action='store_true')
    p = sub.add_parser('shared-backup')
    p.add_argument('--participant')
    p.add_argument('--provider',choices=PROVIDERS)
    p.add_argument('--dataset')
    p = sub.add_parser('shared-restore',help='Restore health-only backup into a new isolated private schema')
    p.add_argument('backup',type=Path)
    p.add_argument('--empty-audit',action='store_true',help='Operational restoration only into completely empty initialized audit tables')


def expect_denial(code, body, *, kind):
    try:
        error = json.loads(body)
        status = str(error.get('statusCode',code))
        label = str(error.get('error','')).lower()
        message = str(error.get('message','')).lower()
    except (ValueError,TypeError,AttributeError):
        raise SentraError('Access verification inconclusive: expected a provider permission response.') from None
    permission = status in ('401','403') and ('unauthorized' in label or 'accessdenied' in label.replace(' ','')
                    or 'permission' in message or 'row-level security' in message)
    hidden = kind == 'anonymous' and status == '404' and ('bucket not found' in label or 'not_found' in label)
    if code not in (400,401,403,404) or not (permission or hidden):
        raise SentraError('Access verification inconclusive: a service/request failure does not prove denial.')


def check_access(config,cipher,backend):
    viewer,_,_ = read_shared(config,cipher,role='viewer')
    db = connect_db(viewer)
    try:
        backend.reserve(65_536)
        read = db.execute('select count(*) from audit.records').fetchone()[0]
        for statement in ('update audit.records set content_sha256=content_sha256 where false',
                          'select encrypted_token_bundle from collector_private.provider_credentials limit 0',
                          'select * from collector_private.storage_members limit 0',
                          'select * from collector_private.daily_jobs limit 0',
                          'select * from collector_private.observation_control limit 0',
                          'set role sentra_collector'):
            try: db.execute(statement)
            except psycopg.errors.InsufficientPrivilege: continue
            raise SentraError('Viewer privilege check failed; stop before sharing any viewer credentials.')
        source = backend.db.execute('select object_location,content_sha256,compressed_bytes from audit.raw_response_manifest limit 1').fetchone()
        if not source:
            raise SentraError('Upload a small sample before demonstrating private original-response access.')
        location,digest,size = source
        reader = PrivateStorage(viewer,backend.reserve)
        reader.get(location.split('/',1)[1],digest,maximum=max(size*2,65_536))
        code,body = reader.request('POST','permission-probe.json.gz',data=gzip.compress(b'{"synthetic_permission_probe":true}'),maximum=65_536)
        expect_denial(code,body,kind='write')
        backend.reserve(size*2+65_536)
        with requests.get(viewer['url']+'/storage/v1/object/public/'+location,
                headers={'apikey':viewer['publishable_key']},timeout=(10,30),allow_redirects=False,stream=True) as response:
            if response.status_code == 200:
                raise SentraError('Anonymous original response unexpectedly readable; stop and restrict the bucket.')
            error_body = bytearray()
            for chunk in response.iter_content(16384):
                error_body.extend(chunk)
                if len(error_body)>65536: raise SentraError('Access-verification error response too large.')
            expect_denial(response.status_code,error_body,kind='anonymous')
        return {'status':'passed','viewer_readable_records':read,'viewer_health_writes':'denied',
                'viewer_credentials':'denied','viewer_role_escalation':'denied','viewer_storage_read':'passed',
                'viewer_storage_write':'denied','anonymous_storage':'denied'}
    finally:
        db.close()


def run_command(args):
    cipher = local_cipher()
    connection = load_connection(args.config,'google_health',require_client=False)
    private = connection.private_dir
    if args.command == 'shared-bootstrap':
        print(json.dumps(bootstrap(private,cipher,baseline=args.egress_baseline_bytes)))
        return 0
    if args.command == 'shared-budget':
        db = connect_db(read_admin(private))
        try: set_budget(db,args.egress_baseline_bytes)
        finally: db.close()
        print('Organization egress baseline refreshed; existing reservations retained.')
        return 0
    credentials,limits,private = read_shared(args.config,cipher)
    backend = SharedBackend(credentials,limits)
    try:
        if args.command == 'shared-status':
            print(json.dumps(backend.usage(),indent=2))
        elif args.command == 'shared-growth':
            print(json.dumps(backend.growth_report(),indent=2))
        elif args.command == 'shared-check-access':
            print(json.dumps(check_access(args.config,cipher,backend)))
        elif args.command in ('shared-sync','shared-verify'):
            providers = list(PROVIDERS) if args.provider == 'all' else [args.provider]
            failed = False
            for provider in providers:
                try:
                    connection = load_connection(args.config,provider,require_client=False)
                    require_agreement(connection)
                    if args.command == 'shared-sync':
                        backend.reserve(16384)
                        if backend.db.execute('select 1 from collector_private.provider_credentials where participant_id=%s and provider=%s',
                                              (connection.participant_id,provider)).fetchone():
                            raise SentraError('Connection is cloud-managed; use cloud collection. An old local snapshot must not overwrite cloud corrections or coverage.')
                    store = LocalStore(connection,cipher)
                    if args.command == 'shared-sync':
                        result = sync_store(store,backend,notify=lambda dataset: print(f'{provider} {dataset}: shared transfer',flush=True))
                    else:
                        result = compare_store(store,backend)
                        if args.originals:
                            print(f'{provider}: record and searchable-value comparisons passed; verifying private originals',flush=True)
                            done = set()
                            for m in store.manifests():
                                key = f"{provider}/{connection.participant_id}/{m['content_sha256']}.json.gz"
                                if key not in done:
                                    backend.storage.get(key,m['content_sha256'],maximum=max(m['compressed_bytes']*2,65_536))
                                    done.add(key)
                                    if len(done) % 50 == 0:
                                        print(f'{provider}: {len(done)} original objects verified',flush=True)
                            result['verified_original_objects'] = len(done)
                    print(json.dumps({'provider':provider,**result}),flush=True)
                except SentraError as error:
                    print(f'{provider}: {error} Stored batches retained.',flush=True)
                    failed = True
                except psycopg.Error as error:
                    print(f'{provider}: shared database operation stopped ({type(error).__name__}, SQLSTATE {error.sqlstate or "unavailable"}); sensitive details omitted. Stored batches retained.',flush=True)
                    failed = True
            return int(failed)
        elif args.command == 'shared-backup':
            for provider in PROVIDERS:
                require_agreement(load_connection(args.config,provider,require_client=False))
            path = make_backup(backend,private/'backups',cipher,participant=args.participant,provider=args.provider,dataset=args.dataset)
            print('Encrypted private backup manifest: '+str(path))
        elif args.command == 'shared-restore':
            path = args.backup.resolve()
            if not path.is_relative_to(private/'backups'):
                raise SentraError('Save the encrypted backup beneath .private/backups before restoring.')
            db = connect_db(read_admin(private))
            try: result = restore_backup(BackupReader(path,cipher),backend,db,empty_audit=args.empty_audit)
            finally: db.close()
            print(json.dumps(result))
        return 0
    finally:
        backend.close()
