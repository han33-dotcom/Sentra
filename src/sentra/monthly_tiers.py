"""Monthly derived partitions, invalidated by complete source fingerprints, not a lookback guess.

One read-only snapshot covers fingerprints and changed rows. Old/corrected/removed
months are detected even when their timestamps or collection watermark move backwards.
Immutable content-addressed objects precede one complete manifest replacement.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile

from .errors import SentraError
from . import tiers as t

VERSION='monthly-v1'
MAX_PARTITIONS=1200
MAX_CACHE_BYTES=500_000_000
SOURCE_GROUPS=(('hr_raw','hr_minute'),('measurements',),('sessions',))


def group_signature(signatures, month, names):
    return [signatures.get(f'{name}/{month}') for name in names]


def rebuild_group(reader, queries, signatures, month, names, now, checkpoint):
    rows={}
    for name in names:
        rows[name]=[]
        if f'{name}/{month}' in signatures:
            query,values=queries[name]
            scoped=f'select * from ({query}) q where {month_expression(name)}=%s'
            params=(*values,month)
            if checkpoint is None:
                rows[name]=reader.read_partition(scoped,params)
            else:
                rows[name]=checkpoint.read_partition(reader,scoped,params,(VERSION,name,month,signatures[f'{name}/{month}']))
    if names==('measurements',):
        return {'measurements.parquet':t.parquet_bytes(t.measurements_table(rows['measurements']))}
    if names==('sessions',):
        return {'sessions.parquet':t.parquet_bytes(t.sessions_table(rows['sessions']))}
    hot,warm=t.hr_tables(rows['hr_raw'],rows['hr_minute'],now)
    return {f'{name}/{pid}.parquet':t.parquet_bytes(table)
            for name,tables in zip(names,(hot,warm)) for pid,table in tables.items()}


def lock(reader):
    reader.reserve(16384)
    if not reader.db.execute('select pg_try_advisory_lock(735048)').fetchone()[0]:
        raise SentraError('Another tier publisher is active; retry after it finishes.')


def unlock(reader):
    reader.db.execute('select pg_advisory_unlock(735048)')


def month_expression(name):
    if name=='sessions': return "coalesce(to_char(started_at at time zone 'UTC','YYYY-MM'),'undated')"
    if name=='hr_raw': return "to_char(measured_at at time zone 'UTC','YYYY-MM')"
    if name=='hr_minute': return "to_char(interval_start at time zone 'UTC','YYYY-MM')"
    # Preserve invalid/undated civil metadata in its own partition; never invent a date.
    civil="coalesce(civil_date->'date',civil_date)"
    return f"""coalesce(to_char(coalesce(measured_at,interval_start) at time zone 'UTC','YYYY-MM'),
        case when {civil}->>'year' ~ '^[0-9]{{4}}$' and {civil}->>'month' ~ '^[0-9]{{1,2}}$'
          then ({civil}->>'year')||'-'||lpad({civil}->>'month',2,'0') end,'undated')"""


def inventory(reader):
    result={}; queries={}
    reader.reserve(1_000_000)
    for name in ('hr_raw','hr_minute','measurements','sessions'):
        query,values=t.tier_query(name,series=reader._has_series())
        queries[name]=(query,values)
        # Two independent halves of a row hash plus row count: order independent and
        # sensitive to omitted fields, numeric scale, provenance and old corrections.
        rows=reader.db.execute(f'''select {month_expression(name)} as partition_month,count(*),
            sum(('x'||substr(md5(row_to_json(q)::text),1,16))::bit(64)::bigint::numeric)::text,
            sum(('x'||substr(md5(row_to_json(q)::text),17,16))::bit(64)::bigint::numeric)::text
            from ({query}) q group by 1 order by 1 limit {MAX_PARTITIONS+1}''',values).fetchall()
        for month,count,a,b in rows: result[f'{name}/{month}']=[int(count),a,b]
        if len(result)>MAX_PARTITIONS: raise SentraError('Monthly inventory exceeds the bounded pilot history.')
    return result,queries


def previous(storage):
    code,body=storage.request('GET','size_report.json',maximum=1_000_000)
    if code!=200:
        if t._missing(code,body): return {},{}
        raise SentraError('Previous tier report unavailable; nothing published.')
    report=json.loads(body)
    if report.get('layout')!=VERSION: return {},{}  # version change forces a complete source rebuild
    if sum(report.get('objects',{}).values())>MAX_CACHE_BYTES:
        raise SentraError('Previous monthly cache exceeds the bounded read cap.')
    with tempfile.TemporaryDirectory(prefix='sentra-monthly-') as folder:
        if not t._download(storage,folder,report,t.MAX_OBJECT_BYTES):
            raise SentraError('Monthly objects failed integrity verification; retry from a fresh report.')
        return report,{key:(Path(folder)/key).read_bytes() for key in report['objects']}


def build(reader,limits,storage,*,now=None,force=False,employees=10,period_days=30,checkpoint=None):
    now=now or datetime.now(timezone.utc)
    before,old=previous(storage)
    objects={}; rebuilt=[]
    # A compact digest scan stays server-side. Only changed month rows leave PostgreSQL.
    with reader.db.transaction():
        reader.db.execute('set transaction isolation level repeatable read, read only')
        signatures,queries=inventory(reader)
        if checkpoint is not None:
            checkpoint.verify_plan(signatures,before.get('sha256',{}))
        months=sorted({key.split('/',1)[1] for key in signatures})
        prior=before.get('source_partitions',{})
        prior_months={key.split('/',1)[1] for key in prior}
        for month in months:
            changed=force or any(signatures.get(f'{name}/{month}')!=prior.get(f'{name}/{month}') for name in queries)
            prefix=f'months/{month}/'
            if not changed:
                objects.update({key:body for key,body in old.items() if key.startswith(prefix)})
                continue
            rebuilt.append(month)
            for names in SOURCE_GROUPS:
                signature=group_signature(signatures,month,names)
                if not force and month in prior_months and signature==group_signature(prior,month,names):
                    for key,data in old.items():
                        if key.startswith(prefix) and key[len(prefix):].split('/')[0].removesuffix('.parquet') in names:
                            objects[key]=data
                    continue
                # A raw heart-rate checkpoint depends on the hot retention cutoff as well as both inputs.
                stamp=now.isoformat() if 'hr_raw' in names else None
                identity=(VERSION,month,names,signature,stamp)
                part=checkpoint.load(identity) if checkpoint is not None and not force else None
                if part is None:
                    part=rebuild_group(reader,queries,signatures,month,names,now,None if force else checkpoint)
                    if checkpoint is not None:
                        checkpoint.save(identity,part)
                objects.update({prefix+key:data for key,data in part.items()})
    # Hot data expires without rereading historical raw rows; warm archives stay intact.
    pa=t._pa(); cutoff=t.epoch(now-t.timedelta(days=t.HOT_DAYS))
    for key in list(objects):
        if '/hr_raw/' in key:
            table=pa.parquet.read_table(io.BytesIO(objects[key]))
            table=table.filter(pa.compute.greater_equal(table['ts'],cutoff))
            if table.num_rows: objects[key]=t.parquet_bytes(table)
            else: del objects[key]
    if sum(map(len,objects.values()))>MAX_CACHE_BYTES: raise SentraError('Monthly output exceeds the bounded cache size.')
    digests={k:hashlib.sha256(v).hexdigest() for k,v in objects.items()}
    with tempfile.TemporaryDirectory(prefix='sentra-monthly-report-') as folder:
        flat=materialize(objects,folder)
        tables={k:pa.parquet.read_table(io.BytesIO(v)) for k,v in flat.items()}
        days={'hr_raw':sum(t.person_days(v,participant=None) for k,v in tables.items() if k.startswith('hr_raw/')),
              'hr_minute':sum(t.person_days(v,participant=None) for k,v in tables.items() if k.startswith('hr_minute/')),
              'measurements':t.person_days(tables['measurements.parquet'])}
        days['sessions']=days['measurements']
        sizes=t.size_report(flat,days,reader.usage(),employees=employees,period_days=period_days)
    report={**sizes,'layout':VERSION,'built_at':now.isoformat(),'read_bytes':reader.read_bytes,
            'source_partitions':signatures,'objects':{k:len(v) for k,v in objects.items()},'sha256':digests,
            'locations':{k:f'monthly/{v}.parquet' for k,v in digests.items()},'rebuilt_months':rebuilt,
            'unchanged':signatures==prior and digests==before.get('sha256'),
            'total_bytes':sum(map(len,objects.values()))}
    if checkpoint is not None:
        checkpoint.record_prepared(signatures,digests)
    return objects,report


def materialize(objects,folder):
    """Supply the established processor layout without duplicating complete objects in Storage."""
    pa=t._pa(); groups={}
    for key,body in objects.items():
        logical=key.split('/',2)[2] if key.startswith('months/') else key
        groups.setdefault(logical,[]).append(pa.parquet.read_table(io.BytesIO(body)))
    groups.setdefault('measurements.parquet',[t.measurements_table([])])
    groups.setdefault('sessions.parquet',[t.sessions_table([])])
    flat={}
    for directory in ('hr_raw','hr_minute'):
        for old in (Path(folder)/directory).glob('*.parquet'):
            if old.relative_to(folder).as_posix() not in groups: old.unlink()
    for key,tables in groups.items():
        table=pa.concat_tables(tables,promote_options='permissive') if len(tables)>1 else tables[0]
        flat[key]=t.parquet_bytes(table)
        path=Path(folder)/key; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(flat[key])
    return flat


def publish(objects,report,storage,reader,limits,*,extra_bytes=0):
    if any(len(body)>t.MAX_OBJECT_BYTES for body in objects.values()):
        raise SentraError('A monthly partition exceeds the bucket limit; nothing published.')
    body=json.dumps(report,sort_keys=True,separators=(',',':')).encode()
    if len(body)>1_000_000: raise SentraError('Monthly manifest exceeds its bounded size.')
    code,old=storage.request('GET','size_report.json',maximum=1_000_000)
    if code!=200 and not t._missing(code,old): raise SentraError('Publication state unavailable; nothing published.')
    prior=json.loads(old) if code==200 else {}
    known=set(prior.get('sha256',{}).values()) if prior.get('layout')==VERSION else set()
    changed={report['sha256'][key]:data for key,data in objects.items() if report['sha256'][key] not in known}
    limits.check(reader.usage(),object_add=sum(map(len,changed.values()))+len(body)+extra_bytes)
    for digest,data in changed.items():
        code,_=storage.request('POST',f'monthly/{digest}.parquet',data=data,maximum=65_536,upsert=True,content_type=t.PARQUET)
        if code not in (200,201): raise SentraError('Monthly upload failed; the previous complete manifest is retained.')
    code,_=storage.request('POST','size_report.json',data=body,maximum=65_536,upsert=True,content_type='application/json')
    if code not in (200,201): raise SentraError('Monthly manifest publication failed; previous publication retained.')
    return {'uploaded':len(changed)+1,'bucket':t.TIER_BUCKET,'layout':VERSION}
