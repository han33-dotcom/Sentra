"""Hosted credential files stay encrypted and outside Git."""
import json
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

from .errors import SentraError
from .shared import Limits
from .vault import atomic_write


def read_shared(path, cipher, *, role='collector'):
    try:
        conf = tomllib.loads(Path(path).read_text(encoding='utf-8'))
        section = conf['shared']
        private = (Path(path).parent / conf['private_dir']).resolve()
        if private != (Path(path).parent.parent / '.private').resolve():
            raise ValueError
        credential = private / 'shared' / (role + '.enc')
        value = json.loads(cipher.decrypt(credential.read_bytes()))
        validate_credentials(value, private)
        limits = Limits(**{k: v for k, v in section.items() if k in Limits.__dataclass_fields__})
        if section.get('confirmed_free_plan') is not True:
            raise SentraError('Confirm the organization remains on Supabase Free before shared operations.')
        return value, limits, private
    except SentraError:
        raise
    except Exception:
        raise SentraError('Hosted configuration or encrypted credentials unavailable. See docs/stage-3-storage.md.') from None


def validate_credentials(value, private):
    url = urlsplit(value['url'])
    if (url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.supabase.co')
            or url.path not in ('', '/') or url.query or url.fragment or url.username or url.port):
        raise ValueError('invalid project URL')
    db = value['db']
    if not (db['host'].endswith('.pooler.supabase.com') or db['host'].endswith('.supabase.co')):
        raise ValueError('invalid database host')
    certificate = Path(db['sslrootcert']).resolve()
    if not certificate.is_relative_to(private.resolve()) or not certificate.is_file():
        raise ValueError('save the official database certificate beneath .private')
    if db.get('sslmode', 'verify-full') != 'verify-full':
        raise ValueError('certificate verification required')
    for key in ('publishable_key', 'storage_email', 'storage_password'):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError('missing credential')


def save_credentials(private, role, value, cipher):
    if role not in ('collector', 'viewer'):
        raise SentraError('Invalid hosted role.')
    atomic_write(private / 'shared' / (role + '.enc'), cipher.encrypt(json.dumps(value).encode()))
