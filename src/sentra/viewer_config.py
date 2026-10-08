"""Viewer-only managed secrets; never load a collector bundle in the hosted app."""
import re
from pathlib import Path
from urllib.parse import urlsplit

from .errors import SentraError
from .shared import Limits
from .shared_config import validate_credentials


def emails(items):
    if not isinstance(items,(list,tuple)) or not 1<=len(items)<=20:
        raise ValueError
    result=[]
    for item in items:
        if not isinstance(item,str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',item): raise ValueError
        result.append(item.strip().lower())
    return sorted(set(result))


def app_url(url):
    parsed=urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError
    if url.rstrip('/')=='http://localhost:8501': return url.rstrip('/')
    if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.streamlit.app') or parsed.port:
        raise ValueError
    return url.rstrip('/')


def runtime_settings(secrets, folder):
    try:
        section=secrets['viewer'].to_dict() if hasattr(secrets['viewer'],'to_dict') else dict(secrets['viewer'])
        fields={'db','url','publishable_key','storage_email','storage_password',
                'certificate_pem','confirmed_free_plan','allowed_emails','limits'}
        if set(section)!=fields or section['confirmed_free_plan'] is not True: raise ValueError
        allowed=emails(section['allowed_emails'])
        db=dict(section['db'])
        if (db.get('user','').split('.')[0]!='sentra_viewer'
                or set(db)-{'user','password','host','port','dbname','sslmode'}): raise ValueError
        certificate=Path(folder)/'supabase-ca.crt'
        certificate.write_text(section['certificate_pem'],encoding='utf-8')
        certificate.chmod(0o600)
        db['sslrootcert']=str(certificate)
        credentials={k:section[k] for k in ('url','publishable_key','storage_email','storage_password')}
        credentials['db']=db
        validate_credentials(credentials,Path(folder))
        limits=Limits(**dict(section['limits']))
        if (limits.database_bytes>350_000_000 or limits.object_bytes>700_000_000
                or limits.monthly_egress_bytes>3_500_000_000 or limits.reserve_bytes<20_000_000): raise ValueError
        auth=dict(secrets['auth'])
        if (auth.get('server_metadata_url')!='https://accounts.google.com/.well-known/openid-configuration'
                or len(auth.get('cookie_secret',''))<43
                or auth.get('expose_tokens',[])!=[]
                or dict(auth.get('client_kwargs',{})).get('scope')!='openid email profile'):
            raise ValueError
        app_url(auth['redirect_uri'].removesuffix('/oauth2callback'))
        if not auth['redirect_uri'].endswith('/oauth2callback'): raise ValueError
        return credentials,limits,allowed
    except Exception:
        raise SentraError('Viewer configuration missing or invalid. Ask the operator to complete viewer-only managed secrets.') from None
