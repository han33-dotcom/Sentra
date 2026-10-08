"""One-time Free-project bootstrap. Admin credentials never enter runtime bundles."""
from datetime import datetime, timezone
import json
from pathlib import Path
import hashlib
import secrets
from uuid import uuid4

from psycopg import sql
import requests

from .errors import SentraError
from .shared_backend import connect_db
from .shared_config import save_credentials


def read_admin(private):
    try:
        value = json.loads((private / 'supabase-admin.json').read_text(encoding='utf-8-sig'))
        if value['confirmed_free_plan'] is not True:
            raise ValueError
        certificate = (private / 'supabase-ca.crt').resolve()
        if not certificate.is_file():
            raise ValueError
        value['db']['sslrootcert'] = str(certificate)
        if (not value['url'].startswith('https://') or not value['url'].endswith('.supabase.co')
                or not value['db']['host'].endswith(('.pooler.supabase.com','.supabase.co'))):
            raise ValueError
        return value
    except (OSError,ValueError,KeyError,TypeError):
        raise SentraError('Complete .private/supabase-admin.json and save the official certificate as .private/supabase-ca.crt.') from None


def set_budget(db, baseline):
    if type(baseline) is not int or not 0 <= baseline < 3_500_000_000:
        raise SentraError('Verified organization egress baseline must be below 3.5 GB.')
    # Never reset already-reserved usage when updating a baseline.
    db.execute('''insert into collector_private.egress_budget(month,baseline_bytes,verified_at)
        values (date_trunc('month',now())::date,%s,now()) on conflict (month)
        do update set baseline_bytes=greatest(collector_private.egress_budget.baseline_bytes,excluded.baseline_bytes),
        verified_at=excluded.verified_at''',(baseline,))


def get_or_create_storage_user(db,admin,account,*,http=requests):
    existing = db.execute('select id from auth.users where email=%s',(account['email'],)).fetchone()
    if existing:
        return str(existing[0])
    try:
        response = http.post(admin['url']+'/auth/v1/admin/users',
            headers={'apikey':admin['secret_key'],'Authorization':'Bearer '+admin['secret_key']},
            json={'email':account['email'],'password':account['storage_password'],'email_confirm':True},
            timeout=(10,30),allow_redirects=False)
        if response.status_code not in (200,201): raise ValueError
        return response.json()['id']
    except (requests.RequestException,ValueError,KeyError):
        raise SentraError('Restricted Storage account creation incomplete; repeat bootstrap to recover any created account. No provider tokens uploaded.') from None


def bootstrap(private, cipher, *, baseline):
    admin = read_admin(private)
    db = connect_db(admin)
    journal = private / 'shared' / 'setup.enc'
    try:
        if journal.exists():
            state = json.loads(cipher.decrypt(journal.read_bytes()))
            if state['url'] != admin['url']:
                raise SentraError('Setup journal belongs to another project; preserve it and review configuration.')
        else:
            state = {'url':admin['url'],'migrations':[], 'accounts':{}}
        from .vault import atomic_write
        def checkpoint():
            atomic_write(journal,cipher.encrypt(json.dumps(state).encode()))
        repo = Path(__file__).resolve().parents[2]
        for migration in ('001_foundation.sql','002_permissions.sql','003_numeric_precision.sql','004_daily_collection.sql'):
            content = (repo / 'sql' / migration).read_text(encoding='utf-8')
            digest = hashlib.sha256(content.encode()).hexdigest()
            installed = None
            if db.execute("select to_regclass('collector_private.schema_versions')").fetchone()[0]:
                installed = db.execute('select sha256 from collector_private.schema_versions where version=%s',(migration,)).fetchone()
            if installed:
                if installed[0] != digest:
                    raise SentraError('Installed SQL differs from the repository version; review a new migration instead of resetting the database.')
                continue
            # The migration marker is committed with its schema, even if the local journal write fails.
            body = content.rstrip().removesuffix('commit;')
            marker = sql.SQL('''create table if not exists collector_private.schema_versions(version text primary key,sha256 text not null);
              revoke all on collector_private.schema_versions from public,anon,authenticated,sentra_viewer;
              insert into collector_private.schema_versions values ({},{}); commit;''').format(sql.Literal(migration),sql.Literal(digest))
            # sentra_viewer only exists after the second migration.
            marker_text = marker.as_string(db)
            if migration == '001_foundation.sql': marker_text = marker_text.replace(',sentra_viewer','')
            db.execute(body + marker_text)
            state['migrations'].append(migration); checkpoint()
        for role in ('collector','viewer'):
            db_role = 'sentra_' + role
            account = state['accounts'].get(role)
            if not account:
                account = {'password':secrets.token_urlsafe(36),'email':f'sentra-{role}-{uuid4().hex}@sentra.invalid',
                           'storage_password':secrets.token_urlsafe(36),'user_id':None}
                state['accounts'][role] = account; checkpoint()
            db.execute(sql.SQL('alter role {} password {}').format(sql.Identifier(db_role),sql.Literal(account['password'])))
            if not account['user_id']:
                account['user_id'] = get_or_create_storage_user(db,admin,account); checkpoint()
            db.execute('insert into collector_private.storage_members values (%s,%s) on conflict do nothing',(account['user_id'],role))
            dbinfo = dict(admin['db'])
            # Shared Supavisor usernames carry project reference after the role name.
            old_user = dbinfo['user']
            dbinfo['user'] = db_role + ('.'+old_user.split('.',1)[1] if '.pooler.supabase.com' in dbinfo['host'] else '')
            dbinfo['password'] = account['password']
            save_credentials(private,role,{'db':dbinfo,'url':admin['url'],'publishable_key':admin['publishable_key'],
                'storage_email':account['email'],'storage_password':account['storage_password']},cipher)
        set_budget(db,baseline)
        return {'status':'configured','plan':'Free','roles':['collector','viewer'],'bucket':'sentra-originals','provider_tokens_uploaded':False}
    finally:
        db.close()
