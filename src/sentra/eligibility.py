"""Publish only versioned assessment availability after the corresponding board succeeds."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from psycopg.types.json import Jsonb

from .errors import SentraError
from .organization import valid_days
from .processing.board import BOARD_VERSION
from .processing.pipeline import ASSESSMENT_VERSION
from .shared import Limits
from .shared_backend import SharedBackend
from .shared_config import validate_credentials


def metadata(board):
    if (board.get('assessment_version') != ASSESSMENT_VERSION
            or board.get('board_version') != BOARD_VERSION):
        raise SentraError('Eligibility requires the current published board contract.')
    people=board.get('people')
    if not isinstance(people,list) or len(people)>100:
        raise SentraError('Eligibility publication exceeds the bounded pilot scope.')
    result=[]; seen=set()
    for person in people:
        pid=person.get('id') if isinstance(person,dict) else None
        if not isinstance(pid,str) or not re.fullmatch(r'p[0-9]{2,4}',pid) or pid in seen:
            raise SentraError('Eligibility publication has an invalid participant directory.')
        seen.add(pid)
        latest=max(valid_days(person),key=lambda d:d['d'],default=None)
        complete=None
        if latest:
            if latest.get('a') in ('partial','insufficient'):
                complete=False
            elif latest.get('a') is None and latest.get('lvl') in ('green','amber','red'):
                complete=True
        result.append({'participant_id':pid,'day':latest['d'] if latest else None,'assessable':complete})
    return result


def publish(backend,board):
    rows=metadata(board)
    published=datetime.fromisoformat(board['built_at'])
    if published.tzinfo is None:
        raise SentraError('Eligibility needs an explicit publication timezone.')
    digest=hashlib.sha256(json.dumps(board,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    backend.guard(database_add=131072)
    installed=backend.db.execute("select to_regprocedure('collector_private.publish_assessment_eligibility(timestamptz,text,text,jsonb)') is not null").fetchone()[0] is True
    if not installed:
        return 'migration_unavailable'  # Never infer eligibility from signup or arbitrary readings.
    backend.db.execute('select collector_private.publish_assessment_eligibility(%s,%s,%s,%s)',
                       (published,ASSESSMENT_VERSION,digest,Jsonb(rows)))
    return 'published'


def from_config(config,folder):
    """Use the existing collector DB role for the bounded metadata write; no token key needed."""
    try:
        if config.get('confirmed_free_plan') is not True: raise ValueError
        credentials=dict(config['credentials']); credentials['db']=dict(credentials['db'])
        if credentials['db']['user'].split('.')[0]!='sentra_collector': raise ValueError
        certificate=Path(folder)/'eligibility-ca.crt'
        certificate.write_text(config['certificate_pem'],encoding='utf-8')
        credentials['db']['sslrootcert']=str(certificate)
        validate_credentials(credentials,Path(folder))
        backend=SharedBackend(credentials,Limits(**config['limits']))
        backend.egress_purpose='processing'
        return backend
    except Exception:
        raise SentraError('Eligibility publisher configuration unavailable; no metadata written.') from None
