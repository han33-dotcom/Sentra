"""Bounded phase-3 preview/removal. Originals, records, sparse rows and series are preserved."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
import re

import requests
from psycopg.types.json import Jsonb

from . import compaction
from .datasets import canonical
from .errors import SentraError
from .shared_backup import chunks,verify_backup

OWNERS=frozenset(('han33-dotcom','MohamadNasrallah'))
MAX_ROWS=100_000
MAX_BACKUP_SELECTION=32_000_000


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _paused(db):
    settings,updated=db.execute('select settings,updated_at from collector_private.observation_control where singleton').fetchone()
    if settings.get('enabled') is not False:
        raise SentraError('Collection must be explicitly paused before a storage preview/removal.')
    compaction._require_additive_mode(db)
    return updated.isoformat()


def _lock_tables(db):
    db.execute('lock table audit.measurements,audit.series,audit.records,collector_private.observation_control in share row exclusive mode')
    if db.execute("select to_regclass('collector_private.compact_control') is not null").fetchone()[0] is True:
        db.execute('lock table collector_private.compact_control in share row exclusive mode')


def _snapshot(db,scope,responses):
    where=compaction.SCOPE+' and source_response_id=any(%s)'
    params=(*scope,responses)
    count,size=db.execute(f'''select count(*),coalesce(sum(pg_column_size(m)),0)
        from audit.measurements m where {where}''',params).fetchone()
    if not 0<count<=MAX_ROWS or size>MAX_BACKUP_SELECTION:
        raise SentraError('Removal scope must contain 1–100,000 rows within 32 MB; use a smaller response batch.')
    fingerprint=db.execute(f'''select
        md5(coalesce(string_agg(md5(row_to_json(m)::text),'' order by record_key,metric),''))
        from audit.measurements m where {where}''',params).fetchone()[0]
    # Exact multiset comparison supplements the approved fingerprint, including all 22 columns.
    mismatch=db.execute(f'''with m as (select row_to_json(m)::text row from audit.measurements m where {where}),
        s as (select row_to_json(s)::text row from audit.series_rows s where {where})
        select exists((select * from m except all select * from s) union all
                      (select * from s except all select * from m))''',(*params,*params)).fetchone()[0]
    stale=db.execute(f'''select exists(select 1 from audit.measurements m where {where}
        and not exists(select 1 from audit.records r where
        (r.participant_id,r.provider,r.dataset,r.record_key,r.source_response_id)=
        (m.participant_id,m.provider,m.dataset,m.record_key,m.source_response_id)))''',params).fetchone()[0]
    if mismatch or stale:
        raise SentraError('Scope is not a lossless, current compact copy; no removal permitted.')
    return {'rows':int(count),'row_payload_bytes':int(size),'row_fingerprint':fingerprint}


def preview(backend,participant,provider,dataset,*,limit=20,now=None):
    if not 1<=limit<=200: raise SentraError('Preview response limit must be 1–200.')
    scope=compaction._scope(participant,provider,dataset)
    now=now or datetime.now(timezone.utc)
    backend.reserve(131072); backend.lock()
    try:
        with backend.db.transaction():
            _lock_tables(backend.db); paused=_paused(backend.db)
            responses=[r[0] for r in backend.db.execute(f'''select distinct source_response_id
                from audit.measurements where {compaction.SCOPE} order by 1 limit %s''',(*scope,limit)).fetchall()]
            state=_snapshot(backend.db,scope,responses)
            plan={'format':1,'project_url':backend.credentials['url'],'scope':list(scope),'responses':responses,
                  'created_at':now.isoformat(),'expires_at':(now+timedelta(days=1)).isoformat(),
                  'collection_control_updated_at':paused,**state}
            return {**plan,'sha256':digest(plan)}
    finally: backend.unlock()


def approval_comments(urls,plan_hash,evidence_hash,*,get=requests.get):
    """Read the two actual owner comments; this function never posts or approves anything."""
    if len(urls)!=2: raise SentraError('Two owner approval comment URLs are required.')
    authors=set(); pull=None
    marker=f'APPROVE SENTRA PHASE3 {plan_hash} EVIDENCE {evidence_hash}'
    for url in urls:
        match=re.fullmatch(r'https://github.com/han33-dotcom/Sentra/pull/(\d+)#issuecomment-(\d+)',url)
        if not match or (pull and pull!=match[1]): raise SentraError('Approvals must be comments on the same Sentra PR.')
        pull=match[1]
        with get('https://api.github.com/repos/han33-dotcom/Sentra/issues/comments/'+match[2],
                 timeout=(10,30),allow_redirects=False,stream=True) as response:
            if response.status_code!=200: raise SentraError('Owner approval could not be verified.')
            data=bytearray()
            for part in response.iter_content(16384):
                data.extend(part)
                if len(data)>1_000_000: raise SentraError('Approval response exceeds bounds.')
            comment=json.loads(data)
        if (comment.get('issue_url')!='https://api.github.com/repos/han33-dotcom/Sentra/issues/'+pull
                or marker not in comment.get('body','').splitlines()):
            raise SentraError('Owner approval does not cover this exact preview and recovery evidence.')
        authors.add(comment.get('user',{}).get('login'))
    if authors!=OWNERS: raise SentraError('Both designated storage owners must approve this exact operation.')


def _backup_rows(reader,plan,db):
    """Prove the removed logical rows are actually in the verified archive, without downloading DB rows."""
    db.execute('create temp table sentra_removal_backup(like audit.measurements) on commit drop')
    total_bytes=0; scope=tuple(plan['scope']); responses=set(plan['responses'])
    for name in chunks(reader.info,'measurements'):
        batch=[]
        for line in reader.read(name).splitlines():
            row=json.loads(line)
            if tuple(row[k] for k in ('participant_id','provider','dataset'))!=scope or row['source_response_id'] not in responses:
                continue
            total_bytes+=len(line)
            if total_bytes>MAX_BACKUP_SELECTION: raise SentraError('Backup selection exceeds 32 MB; use a smaller preview.')
            batch.append(row)
        if batch:
            db.execute('insert into sentra_removal_backup select * from jsonb_populate_recordset(null::audit.measurements,%s)',(Jsonb(batch),))
    missing=db.execute(f'''select exists(select to_jsonb(m) from audit.measurements m
        where {compaction.SCOPE} and source_response_id=any(%s)
        except all select to_jsonb(b) from sentra_removal_backup b)''',(*scope,plan['responses'])).fetchone()[0]
    if missing: raise SentraError('The verified backup does not contain every current row in this removal scope.')


def remove(backend,plan,reader,evidence,approval_urls,*,now=None,check_approvals=approval_comments):
    now=now or datetime.now(timezone.utc)
    unsigned={k:v for k,v in plan.items() if k!='sha256'}
    if (plan.get('format')!=1 or plan.get('sha256')!=digest(unsigned)
            or plan.get('project_url')!=backend.credentials['url']
            or not datetime.fromisoformat(plan['created_at'])<=now<datetime.fromisoformat(plan['expires_at'])):
        raise SentraError('Preview is changed, expired or names another project.')
    verified=verify_backup(reader)
    backup_hash=hashlib.sha256(reader.path.read_bytes()).hexdigest()
    created=datetime.fromisoformat(verified['created_at'])
    if (verified['project_url']!=plan['project_url'] or any((verified.get('selection') or {}).values())
            or verified['not_covered'] or 'series' not in verified['tables']
            or not now-timedelta(days=1)<=created<=datetime.fromisoformat(plan['created_at'])
            or created<datetime.fromisoformat(plan['collection_control_updated_at'])):
        raise SentraError('A fresh full verified backup taken after this paused control state is required.')
    if (evidence.get('backup_manifest_sha256')!=backup_hash or evidence.get('status')!='restored_and_verified'
            or evidence.get('source_project_url')!=plan['project_url']
            or not evidence.get('target_project_url') or evidence['target_project_url']==plan['project_url']
            or evidence.get('isolation_verified') is not True or evidence.get('counts')!=verified['tables']
            or evidence.get('originals_verified')!=verified['originals']
            or not re.fullmatch(r'https://github.com/han33-dotcom/Sentra/(?:issues|pull)/\d+(?:#issuecomment-\d+)?',evidence.get('retention_decision_url',''))):
        raise SentraError('Matching isolated recovery and recorded retention decision evidence is required.')
    check_approvals(approval_urls,plan['sha256'],digest(evidence))
    backend.reserve(262144); backend.guard(database_add=2*plan['row_payload_bytes']+1_000_000); backend.lock()
    try:
        with backend.db.transaction():
            _lock_tables(backend.db)
            if _paused(backend.db)!=plan['collection_control_updated_at']:
                raise SentraError('Collection control changed after preview; create a fresh preview.')
            scope=compaction._scope(*plan['scope'])
            current=_snapshot(backend.db,scope,plan['responses'])
            if any(current[k]!=plan[k] for k in current): raise SentraError('Rows changed after preview; no rows removed.')
            _backup_rows(reader,plan,backend.db)
            removed=backend.db.execute(f'delete from audit.measurements where {compaction.SCOPE} and source_response_id=any(%s)',
                                       (*scope,plan['responses'])).rowcount
            if removed!=plan['rows']: raise SentraError('Removal count changed; transaction rolled back.')
            from .tiers import COMPACT_ONLY
            logical=backend.db.execute(f'''select count(*) from audit.series_rows c
                where {compaction.SCOPE} and source_response_id=any(%s) and {COMPACT_ONLY}''',
                (*scope,plan['responses'])).fetchone()[0]
            if logical!=removed: raise SentraError('Logical row count changed; transaction rolled back.')
        return {'status':'removed_verified_duplicates','rows':removed,'plan_sha256':plan['sha256'],
                'vacuum_performed':False,'meaning':'Records, originals and compact rows retained. Measure database size separately; DELETE does not reclaim the file size.'}
    finally: backend.unlock()
