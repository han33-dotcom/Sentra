"""Laptop-independent collector entry point; explicit sanitized output only."""
import argparse,hashlib,json,logging,os,re,tempfile,time
from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
from cryptography.fernet import Fernet
import psycopg,requests
from psycopg.types.json import Jsonb
from .auth import access_token
from .cloud_collect import OUTCOMES,collect_job,failure_outcome,independent_providers
from .cloud_store import CloudStore,clock
from .cloud_tokens import CloudTokenVault,TokenRepository
from .daily_plan import collection_day,day_jobs,request_days,window_status
from .datasets import ON_REQUEST,plan_jobs
from .errors import SentraError
from .shared import CapacityStop,Limits
from .shared_backend import SharedBackend
from .shared_config import validate_credentials
from .transport import ReadClient


def jobs_for(provider,mode,today,states,start=None,end=None,dataset=None,*,scheduled_datasets=None):
    failures=[]
    if mode=='daily':
        jobs=[]
        for template in day_jobs(provider,today-timedelta(days=1)):
            if scheduled_datasets is not None and template.dataset not in scheduled_datasets:
                continue
            try:
                for day in request_days(states.get(template.dataset,[]),today):
                    jobs.append(next(j for j in day_jobs(provider,day) if j.dataset==template.dataset))
            except SentraError as e: failures.append({'dataset':template.dataset,'message':str(e)})
        # Cycle intervals must be available before recovery normalization.
        jobs.sort(key=lambda j:(j.dataset=='recovery',j.start_date))
    else:
        if start is None or end is None or not 0<(end-start).days<=30 or end>today:
            raise SentraError('Manual import/recovery requires 1–30 past calendar days; end is exclusive, at most today in Beirut.')
        # Large on-request datasets only when a manual run names them; daily mode never includes them.
        extra=(dataset,) if dataset in ON_REQUEST and provider=='google_health' else ()
        if mode=='initial': jobs=plan_jobs(provider,start,end,on_request=extra)
        elif mode=='recovery':
            jobs=[]; day=start
            while day<end: jobs.extend(day_jobs(provider,day,extra)); day+=timedelta(days=1)
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
        configured_connections(participants)
        return credentials,Limits(**config['limits']),participants,cipher
    except Exception: raise SentraError('Cloud secrets/configuration missing or invalid; no provider request made.') from None


def configured_connections(participants):
    if not isinstance(participants,dict) or not participants:
        raise SentraError('No participants configured.')
    pairs=[]
    for provider, value in participants.items():
        values=[value] if isinstance(value,str) else value
        if (provider not in ('google_health','whoop') or not isinstance(values,list) or not values
                or any(not isinstance(pid,str) or not re.fullmatch(r'p[0-9]{2,4}',pid) for pid in values)):
            raise SentraError('Invalid participant directory.')
        pairs.extend((pid,provider) for pid in values)
    if len(pairs)>100 or len(set(pairs))!=len(pairs):
        raise SentraError('Participant directory exceeds bounds or contains duplicates.')
    return pairs


def connection_targets(credentials,limits,participants,*,include_enrolled=None):
    pairs=configured_connections(participants)
    if include_enrolled is None:
        include_enrolled=json.loads(os.environ.get('SENTRA_COLLECTOR_CONFIG','{}')).get('include_enrolled')
    if include_enrolled is True:
        backend=SharedBackend(credentials,limits)
        try:
            backend.guard()
            pairs.extend(backend.db.execute('select * from collector_private.enrolled_connections()').fetchall())
        finally: backend.close()
    pairs=list(dict.fromkeys(pairs))
    if len(pairs)>100: raise SentraError('Participant directory exceeds the approved runtime bound.')
    return pairs


def attempt_run_id(execution):
    return execution+'-attempt-'+os.environ.get('GITHUB_RUN_ATTEMPT','1') if os.environ.get('GITHUB_RUN_ID') else execution


def scheduled_scope(raw, pairs, day):
    """Validate the entire private schedule before the first account can run."""
    try:
        entries = json.loads(raw)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise ValueError
        targets = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'participant', 'provider', 'datasets'}:
                raise ValueError
            pair = (entry['participant'], entry['provider'])
            datasets = entry['datasets']
            if pair not in pairs or pair in targets or not isinstance(datasets, list) or not datasets:
                raise ValueError
            selectable = {job.dataset for job in day_jobs(pair[1], day)}
            if len(set(datasets)) != len(datasets) or not set(datasets) <= selectable:
                raise ValueError
            targets[pair] = frozenset(datasets)
        return targets
    except (TypeError, ValueError):
        raise SentraError('Missing or invalid scheduled scope. Verify each configured connection and daily dataset.') from None


def preview_schedule(credentials, limits, scope, day):
    backend = SharedBackend(credentials, limits)
    backend.egress_purpose = 'operations'
    try:
        backend.guard()
        failed = False
        for (pid, provider), datasets in scope.items():
            states = CloudStore(backend, pid, provider).states()
            jobs, failures = jobs_for(provider, 'daily', day, states, scheduled_datasets=datasets)
            print(json.dumps({'provider':provider, 'jobs':[(j.dataset,j.start_date) for j in jobs],
                              'planning_failures':failures}), flush=True)
            failed = failed or bool(failures)
        return int(failed)
    finally:
        backend.close()


def scope_digest(pid, provider, datasets):
    encoded = json.dumps([pid,provider,sorted(datasets)],separators=(',',':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def update_window(backend, previous, updated):
    result = backend.db.execute('''update collector_private.observation_control set settings=%s,updated_at=now()
        where singleton and settings=%s''',(Jsonb(updated),Jsonb(previous)))
    if result.rowcount != 1:
        raise SentraError('Collection window changed. Inspect the current operator decision.')


def claim_pilot_day(backend, settings, today, pid, provider, datasets):
    pilot = settings['pilot']
    if not datasets or scope_digest(pid,provider,datasets) != pilot['scope']:
        raise SentraError('The approved pilot scope does not match this run.')
    if pilot['next_day'] != today.isoformat():
        raise SentraError('This pilot day was already claimed or the previous day did not succeed.')
    if datetime.now(timezone.utc).strftime('%Y-%m') != pilot['ledger_month']:
        raise CapacityStop('The approved pilot budget belongs to another accounting month.')
    ceiling = pilot['stop_bytes']
    if type(ceiling) is not int or not 0 < ceiling <= backend.limits.monthly_egress_bytes:
        raise CapacityStop('Invalid pilot egress ceiling.')
    backend.limits = replace(backend.limits, monthly_egress_bytes=ceiling)
    backend.guard()
    claimed = {**settings,'pilot':{**pilot,'next_day':None}}
    update_window(backend, settings, claimed)
    return claimed


def finish_pilot_day(backend, claimed, today, succeeded):
    tomorrow = (today+timedelta(days=1)).isoformat()
    if succeeded and tomorrow < claimed['end']:
        updated = {**claimed,'pilot':{**claimed['pilot'],'next_day':tomorrow}}
    else:
        updated = {'enabled':False}
    update_window(backend, claimed, updated)


def run_provider(credentials,limits,pid,provider,cipher,args,execution,*,scheduled_datasets=None):
    backend=SharedBackend(credentials,limits); locked=False
    claimed = None
    run_id=attempt_run_id(execution)
    details={'run_id':run_id,'execution_id':execution,'started_at':clock(),'status':'running','mode':args.mode,
             'completed':0,'skipped':0,'changed':0,'unchanged':0,'failures':[],'outcomes':dict.fromkeys(OUTCOMES,0),
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
            if 'pilot' in settings:
                claimed = claim_pilot_day(backend,settings,today,pid,provider,scheduled_datasets)
        jobs,failures=jobs_for(provider,args.mode,today,store.states(),args.start,args.end,args.dataset,
                               scheduled_datasets=scheduled_datasets)
        details['failures'].extend({**f,'outcome':'failed'} for f in failures)
        details['outcomes']['failed']+=len(failures)
        if claimed and (failures or not jobs):
            raise SentraError('Pilot planning did not produce a complete daily plan.')
        vault=CloudTokenVault(TokenRepository(backend.db),pid,provider,cipher)
        c=vault.connection()
        client=ReadClient(lambda refresh=False:access_token(c,vault,force_refresh=refresh),guard=vault.ensure_active)
        deadline=time.monotonic()+15*60
        for job in jobs:
            try:
                backend.guard() # No provider fetch once shared capacity is exhausted.
                result=collect_job(store,job,client.fetch,execution,deadline=deadline)
                details['skipped' if result['status']=='skipped' else 'completed']+=1
                details['changed']+=result['changed']; details['unchanged']+=result['unchanged']
                details['outcomes'][result['outcome']]+=1
                print(f'{provider} {job.dataset} {job.start_date}: {result["status"]} ({result["outcome"]})',flush=True)
            except (SentraError,psycopg.Error,requests.RequestException) as e:
                message=str(e) if isinstance(e,SentraError) else 'Shared operation failed; sensitive details omitted. Repeat to resume.'
                outcome=failure_outcome(e)
                details['failures'].append({'dataset':job.dataset,'start':job.start_date,'message':message,'outcome':outcome})
                details['outcomes'][outcome]+=1
                print(f'{provider} {job.dataset} {job.start_date}: {outcome}',flush=True)
                if claimed or isinstance(e,CapacityStop) or time.monotonic()>=deadline:
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
                if claimed:
                    finish_pilot_day(backend,claimed,today,details['status']=='succeeded')
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
    parser.add_argument('--participant',help='Limit collection to one pseudonymous participant')
    parser.add_argument('--start',type=date.fromisoformat); parser.add_argument('--end',type=date.fromisoformat)
    parser.add_argument('--dataset')
    parser.add_argument('--preview-schedule',type=date.fromisoformat,metavar='BEIRUT_DATE',
                        help='Read stored coverage and print the scoped daily plan without dispatching it')
    args=parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix='sentra-cloud-') as folder:
            credentials,limits,participants,cipher=runtime_config(folder)
            pairs=connection_targets(credentials,limits,participants)
            schedule = None
            if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' or args.preview_schedule:
                if args.mode != 'daily' or args.provider != 'all' or any((args.participant,args.dataset,args.start,args.end)):
                    raise SentraError('Scheduled collection accepts only the approved daily scope.')
                day = args.preview_schedule or collection_day()
                schedule = scheduled_scope(os.environ.get('SENTRA_SCHEDULE_SCOPE',''), pairs, day)
                if args.preview_schedule:
                    return preview_schedule(credentials, limits, schedule, day)
                pairs = list(schedule)
            if args.provider!='all': pairs=[(pid,p) for pid,p in pairs if p==args.provider]
            if args.participant:
                if not re.fullmatch(r'p[0-9]{2,4}',args.participant): raise SentraError('Invalid participant.')
                pairs=[(pid,p) for pid,p in pairs if pid==args.participant]
            if not pairs: raise SentraError('Requested participant/provider is not configured.')
            if args.mode!='daily' and len(pairs)>2 and not args.participant:
                raise SentraError('Select one participant for a manual import when the pilot has grown.')
            execution='github-'+os.environ['GITHUB_RUN_ID'] if os.environ.get('GITHUB_RUN_ID') else str(uuid4())
            # The same run ID skips already-complete jobs on retries; another run rechecks content.
            results=[]
            for pid,provider in pairs:
                options = {'scheduled_datasets': schedule[pid,provider]} if schedule is not None else {}
                for result in independent_providers([provider],lambda p:run_provider(credentials,limits,pid,p,cipher,args,execution,**options)):
                    results.append(result if schedule is not None else {'participant_id':pid,**result})
            print(json.dumps(results),flush=True)
            return int(any(r['status'] not in ('succeeded','paused') for r in results))
    except Exception as e:
        print(str(e) if isinstance(e,SentraError) else 'Cloud operation failed; credentials and health details omitted.',flush=True)
        return 1


if __name__=='__main__': raise SystemExit(main())
