"""Laptop-independent collector entry point; explicit sanitized output only."""
import argparse,json,logging,os,re,tempfile,time
from datetime import date,timedelta
from pathlib import Path
from uuid import uuid4
from cryptography.fernet import Fernet
import psycopg,requests
from .auth import access_token
from .cloud_collect import collect_job,independent_providers
from .cloud_store import CloudStore,clock
from .cloud_tokens import CloudTokenVault,TokenRepository
from .daily_plan import collection_day,day_jobs,request_days,window_status
from .datasets import plan_jobs
from .errors import SentraError
from .shared import CapacityStop,Limits
from .shared_backend import SharedBackend
from .shared_config import validate_credentials
from .transport import ReadClient


def jobs_for(provider,mode,today,states,start=None,end=None,dataset=None):
    failures=[]
    if mode=='daily':
        jobs=[]
        for template in day_jobs(provider,today-timedelta(days=1)):
            try:
                for day in request_days(states.get(template.dataset,[]),today):
                    jobs.append(next(j for j in day_jobs(provider,day) if j.dataset==template.dataset))
            except SentraError as e: failures.append({'dataset':template.dataset,'message':str(e)})
        # Cycle intervals must be available before recovery normalization.
        jobs.sort(key=lambda j:(j.dataset=='recovery',j.start_date))
    else:
        if start is None or end is None or not 0<(end-start).days<=30 or end>today:
            raise SentraError('Manual import/recovery requires 1–30 past calendar days; end is exclusive, at most today in Beirut.')
        if mode=='initial': jobs=plan_jobs(provider,start,end)
        elif mode=='recovery':
            jobs=[]; day=start
            while day<end: jobs.extend(day_jobs(provider,day)); day+=timedelta(days=1)
            jobs.sort(key=lambda j:(j.dataset=='recovery',j.start_date))
        else: raise SentraError('Unknown cloud collection mode.')
    if dataset:
        if dataset not in {j.dataset for j in jobs}: raise SentraError('Unknown/unsupported dataset for the chosen request.')
        jobs=[j for j in jobs if j.dataset==dataset]
    return jobs,failures


def runtime_config(folder):
    try:
        config=json.loads(os.environ['SENTRA_COLLECTOR_CONFIG'])
        cipher=Fernet(os.environ['SENTRA_TOKEN_KEY'].encode())
        if config['confirmed_free_plan'] is not True: raise ValueError
        certificate=Path(folder)/'supabase-ca.crt'
        certificate.write_text(config['certificate_pem'],encoding='utf-8'); certificate.chmod(0o600)
        credentials=config['credentials']; credentials['db']['sslrootcert']=str(certificate)
        validate_credentials(credentials,Path(folder))
        if credentials['db']['user'].split('.')[0]!='sentra_collector': raise ValueError
        participants=config['participants']
        if not participants or any(p not in ('google_health','whoop') or not re.fullmatch(r'p[0-9]{2,4}',pid) for p,pid in participants.items()): raise ValueError
        if len(set(participants.values()))!=len(participants): raise ValueError
        return credentials,Limits(**config['limits']),participants,cipher
    except Exception: raise SentraError('Cloud secrets/configuration missing or invalid; no provider request made.') from None


def attempt_run_id(execution):
    return execution+'-attempt-'+os.environ.get('GITHUB_RUN_ATTEMPT','1') if os.environ.get('GITHUB_RUN_ID') else execution


def run_provider(credentials,limits,pid,provider,cipher,args,execution):
    backend=SharedBackend(credentials,limits); locked=False
    run_id=attempt_run_id(execution)
    details={'run_id':run_id,'execution_id':execution,'started_at':clock(),'status':'running','mode':args.mode,
             'completed':0,'skipped':0,'changed':0,'unchanged':0,'failures':[],
             'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),
             'coverage_meaning':'requested pages stored; not proof of complete measurements'}
    store=CloudStore(backend,pid,provider)
    try:
        backend.lock(); locked=True
        store.run_status(run_id,details)
        backend.guard()
        today=collection_day()
        if args.mode=='daily':
            backend.reserve(32768)
            settings=backend.db.execute('select settings from collector_private.observation_control where singleton').fetchone()[0]
            state=window_status(settings,today)
            if state!='active':
                details.update(status='paused',pause_reason=state); return details
        jobs,failures=jobs_for(provider,args.mode,today,store.states(),args.start,args.end,args.dataset)
        details['failures'].extend(failures)
        vault=CloudTokenVault(TokenRepository(backend.db),pid,provider,cipher)
        c=vault.connection()
        client=ReadClient(lambda refresh=False:access_token(c,vault,force_refresh=refresh))
        deadline=time.monotonic()+15*60
        for job in jobs:
            try:
                backend.guard() # No provider fetch once shared capacity is exhausted.
                result=collect_job(store,job,client.fetch,execution,deadline=deadline)
                details['skipped' if result['status']=='skipped' else 'completed']+=1
                details['changed']+=result['changed']; details['unchanged']+=result['unchanged']
                print(f'{provider} {job.dataset} {job.start_date}: {result["status"]}',flush=True)
            except (SentraError,psycopg.Error,requests.RequestException) as e:
                message=str(e) if isinstance(e,SentraError) else 'Shared operation failed; sensitive details omitted. Repeat to resume.'
                details['failures'].append({'dataset':job.dataset,'start':job.start_date,'message':message})
                if isinstance(e,CapacityStop) or time.monotonic()>=deadline:
                    details['status']='capacity_stop' if isinstance(e,CapacityStop) else 'partial'; break
        if details['status']=='running': details['status']='partial' if details['failures'] else 'succeeded'
    except Exception as e:
        details['status']='capacity_stop' if isinstance(e,CapacityStop) else 'failed'
        details['failures'].append({'message':str(e) if isinstance(e,SentraError) else 'Shared operation failed; sensitive details omitted.'})
    finally:
        details['finished_at']=clock()
        if locked:
            try:
                details['storage_usage']=backend.usage()
                store.run_status(run_id,details)
            except (SentraError,psycopg.Error):
                details['status']='failed'; details['status_persistence']='unavailable; inspect last durable state and capacity'
            finally:
                try: backend.unlock()
                except psycopg.Error:
                    details['status']='failed'; details['lock_release']='connection closed to release lock'
        backend.close()
    return details


def main(argv=None):
    logging.disable(logging.CRITICAL)
    parser=argparse.ArgumentParser(description='Private hosted wearable collection')
    parser.add_argument('--mode',choices=('daily','initial','recovery'),default='daily')
    parser.add_argument('--provider',choices=('all','google_health','whoop'),default='all')
    parser.add_argument('--start',type=date.fromisoformat); parser.add_argument('--end',type=date.fromisoformat)
    parser.add_argument('--dataset')
    args=parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix='sentra-cloud-') as folder:
            credentials,limits,participants,cipher=runtime_config(folder)
            providers=list(participants) if args.provider=='all' else [args.provider]
            if any(p not in participants for p in providers): raise SentraError('Requested participant is not configured.')
            execution='github-'+os.environ['GITHUB_RUN_ID'] if os.environ.get('GITHUB_RUN_ID') else str(uuid4())
            # The same run ID skips already-complete jobs on retries; another run rechecks content.
            results=independent_providers(providers,lambda p:run_provider(credentials,limits,participants[p],p,cipher,args,execution))
            print(json.dumps(results),flush=True)
            return int(any(r['status'] not in ('succeeded','paused') for r in results))
    except Exception as e:
        print(str(e) if isinstance(e,SentraError) else 'Cloud operation failed; credentials and health details omitted.',flush=True)
        return 1


if __name__=='__main__': raise SystemExit(main())
