"""Calendar-day recovery and explicit ongoing/bounded collection; no provider calls."""
from datetime import date,datetime,timedelta,timezone

from .datasets import BEIRUT,Job,plan_jobs,utc_day
from .errors import SentraError


def collection_day(now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise SentraError('Collection clock must include a timezone.')
    return now.astimezone(BEIRUT).date()


def day_jobs(provider,day):
    return [j for j in plan_jobs(provider,day,day+timedelta(days=1)) if j.dataset!='original_heart-rate']


def request_days(covered,end):
    spans=[]
    try:
        for r in covered:
            a=date.fromisoformat(r['requested_civil_start']); b=date.fromisoformat(r['requested_civil_end'])
            if a>=b: raise ValueError
            spans.append((a,b))
    except (KeyError,TypeError,ValueError):
        raise SentraError('Coverage dates invalid; inspect state before recovery.') from None
    if not spans: raise SentraError('No initial coverage; use a bounded manual initial import.')
    first=min(a for a,b in spans)
    # Old successful history is fine; only an old *missing* day requires operator recovery.
    missing=[]
    day=first
    while day<end:
        if not any(a<=day<b for a,b in spans): missing.append(day)
        day+=timedelta(days=1)
    if missing and (end-missing[0]).days>30:
        raise SentraError('Recovery gap exceeds 30 days; use a bounded manual recovery range.')
    return sorted(set(missing)|{end-timedelta(days=i) for i in (1,2,3) if end-timedelta(days=i)>=first})


def window_status(window,day):
    if window.get('enabled') is not True: return 'paused'
    try:
        start=date.fromisoformat(window['start'])
        mode=window.get('mode','bounded')
        if mode=='ongoing':
            if 'end' in window: raise ValueError
            return 'not_started' if day<start else 'active'
        if mode!='bounded': raise ValueError
        end=date.fromisoformat(window['end'])
        if (end-start).days!=3: raise ValueError
    except (KeyError,TypeError,ValueError):
        raise SentraError('Collection control requires an explicit ongoing start or a bounded three-day window.') from None
    return 'not_started' if day<start else ('ended' if day>=end else 'active')


def collection_control(*,start=None,pause=False,approved=False,ongoing=False):
    if pause:
        if start is not None or ongoing: raise SentraError('Pause cannot also specify a start or ongoing collection.')
        return {'enabled':False}
    if not approved or type(start) is not date:
        raise SentraError('Explicit human collection approval and start date are required.')
    if ongoing: return {'enabled':True,'mode':'ongoing','start':start.isoformat()}
    return {'enabled':True,'start':start.isoformat(),'end':(start+timedelta(days=3)).isoformat()}


def merge_coverage(covered,job):
    spans=[(date.fromisoformat(r['requested_civil_start']),date.fromisoformat(r['requested_civil_end'])) for r in covered]
    spans.append((date.fromisoformat(job.start_date),date.fromisoformat(job.end_date)))
    merged=[]
    for a,b in sorted(spans):
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    return [{'start':utc_day(a),'end':utc_day(b),'requested_civil_start':a.isoformat(),
             'requested_civil_end':b.isoformat()} for a,b in merged]
