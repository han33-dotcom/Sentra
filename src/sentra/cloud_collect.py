"""Bounded pagination; checkpoint only after the complete page is durable."""
import time
from .errors import SentraError
from .transport import FetchError


def collect_job(store,job,fetch,execution_id,*,deadline=None):
    old=store.progress(job)
    if old and old['status']=='complete' and old['execution_id']==execution_id:
        return {'status':'skipped','changed':0,'unchanged':0}
    p={**store.start(job,execution_id),'execution_id':execution_id}; changed=unchanged=0; restarted=False
    try:
        while True:
            if deadline is not None and time.monotonic()>=deadline:
                raise SentraError('Provider time budget reached; repeat the run to resume.')
            if p['pages']>=1000: raise SentraError('Pagination safety limit reached; inspect provider response.')
            cursor=p['cursor']
            try: payload,body=fetch(job,cursor)
            except FetchError as e:
                if e.status==400 and cursor and not restarted:
                    p=store.reset(job,execution_id); restarted=True; continue
                raise
            if not isinstance(payload,dict) or not isinstance(payload.get(job.records_key,[]),list):
                raise SentraError('Invalid record list; page not checkpointed.')
            nxt=payload.get('next_token' if job.provider=='whoop' else 'nextPageToken')
            nxt='' if nxt is None else nxt
            if not isinstance(nxt,str) or len(nxt)>16384:
                raise SentraError('Invalid pagination token; page not checkpointed.')
            if nxt and (nxt==cursor or nxt in p.get('seen',[])):
                raise SentraError('Repeated pagination token; page not checkpointed.')
            counts=store.page(job,cursor,payload,body,nxt,p)
            changed+=counts['changed']; unchanged+=counts['unchanged']
            p=store.progress(job)
            if not nxt: return {'status':'complete','changed':changed,'unchanged':unchanged}
    except Exception as e:
        safe=e if isinstance(e,SentraError) else SentraError('Page operation failed; sensitive details omitted. Repeat to resume.')
        try: store.failed(job,str(safe))
        except Exception: pass # A lost connection/budget cannot erase the last durable cursor.
        raise safe from None


def independent_providers(providers,run):
    results=[]
    for provider in providers:
        try: results.append({'provider':provider,**run(provider)})
        except Exception as e:
            results.append({'provider':provider,'status':'failed','message':str(e) if isinstance(e,SentraError)
                            else 'Provider operation failed; sensitive details omitted.'})
    return results
