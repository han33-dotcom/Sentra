"""Hosted page persistence, lossless correction comparison and durable coverage."""
from dataclasses import asdict
from datetime import datetime,timezone
import gzip,hashlib
from psycopg.types.json import Jsonb
from .datasets import canonical
from .daily_plan import merge_coverage
from .errors import SentraError
from .normalize import normalize_record
from .local_store import compact_record
from .shared import CapacityStop


def clock(): return datetime.now(timezone.utc).isoformat()


class CloudStore:
    def __init__(self,backend,pid,provider):
        self.backend,self.pid,self.provider=backend,pid,provider

    def metadata_guard(self):
        # Imports leave a 20 MB reserve; bounded status/cursors may use that reserve.
        u=self.backend.usage()
        if u['database_bytes']+65536>=self.backend.limits.database_bytes:
            raise CapacityStop('Metadata capacity exhausted; stop and inspect storage. Existing progress retained.')

    def progress(self,job):
        self.backend.reserve(300_000)
        row=self.backend.db.execute('select progress from collector_private.daily_jobs where participant_id=%s and provider=%s and dataset=%s and job_key=%s',
            (self.pid,self.provider,job.dataset,job.key)).fetchone()
        return row[0] if row else None

    def save_progress(self,job,p,*,complete=False):
        if len(canonical(p).encode())>262144: raise SentraError('Pagination state too large; inspect provider before resuming.')
        self.metadata_guard()
        db=self.backend.db
        with db.transaction():
            db.execute('''insert into collector_private.daily_jobs values (%s,%s,%s,%s,%s,now())
              on conflict(participant_id,provider,dataset,job_key) do update set progress=excluded.progress,updated_at=now()''',
              (self.pid,self.provider,job.dataset,job.key,Jsonb(p)))
            if complete:
                self.backend.reserve(65536)
                row=db.execute('select covered_intervals from audit.connection_state where participant_id=%s and provider=%s and dataset=%s for update',
                    (self.pid,self.provider,job.dataset)).fetchone()
                covered=merge_coverage(row[0] if row else [],job)
                db.execute('''insert into audit.connection_state values (%s,%s,%s,'authorized',%s,%s,%s,now())
                  on conflict(participant_id,provider,dataset) do update set last_success_at=excluded.last_success_at,
                  covered_intervals=excluded.covered_intervals,authorization_status='authorized',
                  continuation_state=audit.connection_state.continuation_state||excluded.continuation_state,updated_at=now()''',
                  (self.pid,self.provider,job.dataset,p['completed_at'],Jsonb(covered),Jsonb({'last_cloud_job':job.key,'last_cloud_status':'complete'})))

    def reset(self,job,execution):
        p={'job':asdict(job),'execution_id':execution,'status':'running','cursor':'','seen':[],
           'pages':0,'received':0,'started_at':clock(),'completed_at':None,'failure':None}
        self.save_progress(job,p); return p

    def start(self,job,execution):
        p=self.progress(job)
        if not p or p['status']=='complete': return self.reset(job,execution)
        p={**p,'execution_id':execution,'status':'running','failure':None}
        self.save_progress(job,p); return p

    def failed(self,job,message,outcome='failed'):
        p=self.progress(job)
        if p:
            self.save_progress(job,{**p,'status':'failed','outcome':outcome,'failure':message,'failed_at':clock()})

    def states(self):
        self.backend.reserve(262144)
        return dict(self.backend.db.execute('select dataset,covered_intervals from audit.connection_state where participant_id=%s and provider=%s',
            (self.pid,self.provider)).fetchall())

    def cycles(self,records):
        keys=list({str(r.get('cycle_id')) for r in records if r.get('cycle_id') is not None})
        if not keys: return {}
        self.backend.reserve(len(keys)*32768+32768)
        rows=self.backend.db.execute("select record_key,record from audit.records where participant_id=%s and provider=%s and dataset='cycle' and record_key=any(%s)",
            (self.pid,self.provider,keys)).fetchall()
        return dict(rows)

    def changed(self,records):
        # Evaluate comparisons in PostgreSQL; never download old health records to compare.
        self.backend.reserve(len(records)*512+32768)
        incoming=[{'key':r['record_key'],'record':compact_record(r)} for r in records]
        rows=self.backend.db.execute('''with incoming as (
          select item->>'key' key,item->'record' record from jsonb_array_elements(%s::jsonb) item)
          select incoming.key from incoming left join audit.records old
          on old.participant_id=%s and old.provider=%s and old.dataset=%s and old.record_key=incoming.key
          where old.record_key is null or collector_private.record_semantics(old.record)
            is distinct from collector_private.record_semantics(incoming.record)''',
          (Jsonb(incoming),self.pid,self.provider,records[0]['dataset'])).fetchall()
        changed={r[0] for r in rows}
        return [r for r in records if r['record_key'] in changed]

    def page(self,job,cursor,payload,body,next_cursor,p):
        if job.provider=='whoop' and job.records_key not in payload:
            raise SentraError('WHOOP records member missing; coverage not advanced.')
        records=payload.get(job.records_key,[])
        if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):
            raise SentraError('Invalid records page; progress retained.')
        collected=clock(); digest=hashlib.sha256(body).hexdigest()
        response_id=hashlib.sha256((job.key+cursor+digest+collected).encode()).hexdigest()
        manifest={'response_id':response_id,'provider':job.provider,'participant_id':self.pid,'dataset':job.dataset,
          'endpoint':job.request()['url'],'requested_start':job.start,'requested_end':job.end,
          'requested_civil_start':job.start_date,'requested_civil_end':job.end_date,'request':job.request(cursor),
          'resolution':job.resolution,'collected_at':collected,'http_status':200,'record_count':len(records),
          'has_more_pages':bool(next_cursor),'content_sha256':digest,'provenance':'original_api_response','aggregation':job.mode}
        nextp={**p,'cursor':next_cursor,'pages':p['pages']+1,'received':p['received']+len(records),
          'seen':p['seen']+([cursor] if cursor else []),'status':'running' if next_cursor else 'complete',
          'completed_at':None if next_cursor else collected,'failure':None}
        if not next_cursor: nextp['outcome']='records' if nextp['received'] else 'no_records'
        if len(canonical(nextp).encode())>262144: raise SentraError('Pagination state too large; page not checkpointed.')
        self.backend.put_manifest(manifest,gzip.compress(body,mtime=0))
        changed_count=unchanged_count=0
        for offset in range(0,len(records),100):
            batch=records[offset:offset+100]; cycles=self.cycles(batch) if job.dataset=='recovery' else {}
            values=[]
            for i,raw in enumerate(batch,offset):
                cycle=cycles.get(str(raw.get('cycle_id')))
                r=normalize_record(job,raw,cycle=cycle['vendor_fields'] if cycle else None)
                r.update(participant_id=self.pid,source_response_id=response_id,
                         source_pointer=f'/{job.records_key}/{i}',collected_at=collected)
                if cycle: r['associated_cycle_source_response_id']=cycle['source_response_id']
                for m in r['measurements']:
                    m.update(participant_id=self.pid,source_response_id=response_id,
                             source_pointer=r['source_pointer']+m['vendor_metric'],collected_at=collected)
                values.append(r)
            changed=self.changed(values)
            if changed: self.backend.put_records(changed)
            changed_count+=len(changed); unchanged_count+=len(values)-len(changed)
        # Records may span transactions; cursor/coverage move only after all batches succeed.
        self.save_progress(job,nextp,complete=not next_cursor)
        return {'changed':changed_count,'unchanged':unchanged_count}

    def run_status(self,run_id,details):
        self.metadata_guard()
        self.backend.db.execute('''insert into audit.collection_runs values (%s,%s,%s,%s,%s,%s,%s)
          on conflict(run_id,participant_id,provider) do update set finished_at=excluded.finished_at,status=excluded.status,details=excluded.details''',
          (run_id,self.pid,self.provider,details['started_at'],details.get('finished_at'),details['status'],Jsonb(details)))
