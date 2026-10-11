"""Operator setup/export: identity-only web client plus restricted viewer credentials."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets

import psycopg
from psycopg import sql

from .errors import SentraError
from .shared_backend import connect_db
from .shared_config import read_shared
from .shared_setup import read_admin
from .vault import atomic_write, local_cipher
from .viewer_config import app_url, emails


def build_secrets(credentials,limits,certificate,client,allowed,url):
    try:
        url=app_url(url)
        allowed=emails(allowed)
        web=client['web']
        redirect=url+'/oauth2callback'
        if (credentials['db']['user'].split('.')[0]!='sentra_viewer'
                or redirect not in web['redirect_uris']
                or not web['client_id'].endswith('.apps.googleusercontent.com') or not web['client_secret']):
            raise ValueError
        q=lambda value:json.dumps(value,ensure_ascii=True)
        lines=['# Private viewer-only secrets. Never commit, log or offer as a download.',
               '[viewer]', 'confirmed_free_plan = true', 'allowed_emails = '+q(allowed),
               'certificate_pem = '+q(certificate)]
        for k in ('url','publishable_key','storage_email','storage_password'):
            lines.append(k+' = '+q(credentials[k]))
        lines+=['','[viewer.db]']
        for k,v in credentials['db'].items():
            if k!='sslrootcert': lines.append(k+' = '+q(v))
        lines+=['','[viewer.limits]']+[k+' = '+str(v) for k,v in asdict(limits).items()]
        lines+=['','[auth]','redirect_uri = '+q(redirect),'cookie_secret = '+q(secrets.token_urlsafe(48)),
                'client_id = '+q(web['client_id']),'client_secret = '+q(web['client_secret']),
                'server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"',
                'expose_tokens = []','client_kwargs = { scope = "openid email profile", prompt = "select_account" }','']
        return '\n'.join(lines)
    except Exception:
        raise SentraError('Use a separate Google web identity client with the exact viewer callback and authorized emails; collector credentials are forbidden.') from None


def migrate(private):
    db=connect_db(read_admin(private))
    try:
        path=Path(__file__).resolve().parents[2]/'sql'/'005_viewer_status.sql'
        content=path.read_text(encoding='utf-8')
        digest=hashlib.sha256(content.encode()).hexdigest()
        found=db.execute('select sha256 from collector_private.schema_versions where version=%s',(path.name,)).fetchone()
        if found:
            if found[0]!=digest: raise SentraError('Installed viewer migration differs; use a reviewed additive migration.')
            return
        if not db.execute("select 1 from collector_private.schema_versions where version='004_daily_collection.sql'").fetchone():
            raise SentraError('Complete Stage 4 shared schema before deploying viewer status.')
        body=content.rstrip().removesuffix('commit;')
        marker=sql.SQL('insert into collector_private.schema_versions values ({},{}); commit;').format(
            sql.Literal(path.name),sql.Literal(digest)).as_string(db)
        db.execute(body+marker)
    except psycopg.Error:
        raise SentraError('Viewer migration unavailable; sensitive database details omitted.') from None
    finally: db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description='Prepare read-only Sentra viewer; no provider requests')
    parser.add_argument('--config',type=Path,default=Path('config/local.toml'))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('migrate')
    prepare=sub.add_parser('prepare')
    prepare.add_argument('--client',type=Path,default=Path('.private/viewer/google-identity-client.json'))
    prepare.add_argument('--team',type=Path,default=Path('.private/viewer/team.json'))
    prepare.add_argument('--url',default='http://localhost:8501')
    args=parser.parse_args(argv)
    try:
        cipher=local_cipher()
        credentials,limits,private=read_shared(args.config,cipher,role='viewer')
        if args.command=='migrate':
            migrate(private)
            print('Read-only viewer status migration configured; collection remains paused.')
            return 0
        client_path,team_path=args.client.resolve(),args.team.resolve()
        if not client_path.is_relative_to(private) or not team_path.is_relative_to(private):
            raise SentraError('Keep identity client and team list beneath ignored .private.')
        client=json.loads(client_path.read_text(encoding='utf-8-sig'))
        # Do not reuse the wearable collector OAuth client's credential in the viewer.
        collector_path=private/'google-client.json'
        if collector_path.exists():
            collector=json.loads(collector_path.read_text(encoding='utf-8-sig'))
            original=collector.get('installed',collector.get('web',{})).get('client_id')
            if original==client.get('web',{}).get('client_id'):
                raise SentraError('Create a separate identity-only client; do not give the viewer the collector client secret.')
        team=json.loads(team_path.read_text(encoding='utf-8-sig'))['allowed_emails']
        result=build_secrets(credentials,limits,Path(credentials['db']['sslrootcert']).read_text(),client,team,args.url)
        local=args.url.rstrip('/')=='http://localhost:8501'
        target=Path('.streamlit/secrets.toml') if local else private/'viewer'/'secrets.cloud.toml'
        atomic_write(target,result.encode())
        print('Private viewer secrets saved to '+str(target)+'; no credential values displayed.')
        return 0
    except (SentraError,OSError,ValueError,KeyError):
        print('Viewer setup incomplete. Check the identity client, team file, registered callback and docs/stage-5-viewer.md; secret details omitted.')
        return 1


if __name__=='__main__': raise SystemExit(main())
