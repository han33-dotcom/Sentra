"""Computed readable views: source records stay unchanged, gaps stay empty."""
import csv
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import re

from .errors import SentraError
from .exports import csv_value
from .datasets import canonical
from .metric_dictionary import METRICS, ASLEEP, ELAPSED, definition, period_metric
from .normalize import leaves
from .viewer_data import BEIRUT, MAX_BYTES, MAX_ROWS, civil_day


def stamp(value):
    if isinstance(value,str):
        try: value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:return None
    return value.astimezone(BEIRUT) if isinstance(value,datetime) and value.tzinfo else None


def number(value,metric):
    if value is None or isinstance(value,bool):return None
    text=str(value)
    if metric.unit=='s':
        if not re.fullmatch(r'\d+(?:\.\d{1,9})?s?',text):return None
        text=text.removesuffix('s')
    try:
        n=Decimal(text)
        if not n.is_finite() or (metric.duration and n<0):return None
        return n
    except InvalidOperation:return None


def formatted(value,metric):
    if metric.duration:
        minutes=value/({'ms':Decimal(60000),'min':Decimal(1),'s':Decimal(60)}[metric.unit])
        rounded=int(minutes.quantize(Decimal(1),rounding=ROUND_HALF_UP))
        return f'{rounded//60} h {rounded%60:02d} min'
    n=value/Decimal(metric.divisor)
    return f'{n:,.{metric.precision}f} {metric.display_unit or metric.unit}'


def record_day(row):
    context=row['record']
    civil=civil_day(context.get('civil_date'))
    if civil:return civil
    point=stamp(context.get('measured_at'))
    # Sleep belongs to the local wake day; cycles/workouts to their local start.
    interval=stamp(context.get('interval_end') if row['dataset']=='sleep' else context.get('interval_start'))
    return (point or interval).date().isoformat() if point or interval else None


def view_for(dataset):
    return 'Sleep' if dataset=='sleep' else ('Workouts' if dataset in ('workout','exercise') else 'Daily activity')


def curate(records,start,end):
    result={name:[] for name in ('Daily activity','Sleep','Workouts','export','points','unmapped')}
    daily={}; sessions={}; candidates={}; labels=set(); periods={}
    recoveries={}
    for r in records:
        if r['provider']=='whoop' and r['dataset']=='recovery':
            sid=r['record'].get('vendor_fields',{}).get('sleep_id')
            if sid:recoveries.setdefault(str(sid),[]).append(r)

    def emit(row,path,value,metric,table,view,day):
        context=row['record']; n=number(value,metric)
        state=('Missing (explicit null)' if value is None else
               'Unscored' if context.get('score_state') in ('UNSCORED','UNSCORABLE','PENDING_SCORE') else
               'Invalid returned value' if n is None else 'Available')
        text=formatted(n,metric) if state=='Available' else state
        table.setdefault(metric.label,[]).append(text)
        if view=='Daily activity':labels.add(metric.label)
        if state=='Available':
            plot=n/({'ms':Decimal(3_600_000),'min':Decimal(60),'s':Decimal(3600)}[metric.unit]) if metric.duration else n/Decimal(metric.divisor)
            unit='hours' if metric.duration else metric.display_unit or metric.unit
            candidates.setdefault((view,day,metric.label,unit),[]).append(plot)
        result['export'].append({'Participant':row['participant_id'],'Provider':row['provider'],
            'View':view,'Date':day,'Session/source record':row['record_key'],'Metric':metric.label,
            'Display':text,'Exact value':str(value) if value is not None else None,'Original unit':metric.unit,
            'Classification':metric.kind,'Availability':state,'Provisional':context.get('provisional',True),
            'Score state':context.get('score_state'),'Timestamp basis':context.get('timestamp_basis'),
            'Start':context.get('interval_start'),'End':context.get('interval_end'),
            'Civil date':context.get('civil_date'),'Requested resolution':context.get('resolution_description'),
            'Source field':path,'Response ID':row['source_response_id'],'Collected at':row['collected_at'],
            'Explanation':metric.explanation,'Definition':metric.reference})

    for row in records:
        dataset=row['dataset'];day=record_day(row)
        if not day or not start.isoformat()<=day<end.isoformat():continue
        view=view_for(dataset);context=row['record'];fields=context.get('vendor_fields',{})
        if view=='Daily activity':table=daily.setdefault(day,{'Date':day})
        else:
            table={'Date':day,
                   'Start':stamp(context.get('interval_start')),'End':stamp(context.get('interval_end')),
                   'Status':'Provisional' if context.get('provisional',True) else 'Returned'}
            if context.get('score_state') not in (None,'SCORED'):table['Status']=context['score_state']
            if dataset=='sleep':table['Type']='Nap' if fields.get('nap') is True else fields.get('sleep',{}).get('type','Sleep')
            elif dataset=='exercise':table['Type']=fields.get('exercise',{}).get('exerciseType','Not supplied')
            else:table['Type']=fields.get('sport_name','Sport ID '+str(fields.get('sport_id','not supplied')))
            sessions[(view,row['provider'],row['record_key'])]=table
        for path,value in leaves(fields):
            metric=definition(row['provider'],dataset,path)
            if metric:emit(row,path,value,metric,table,view,day)
            else:result['unmapped'].append({'Provider':row['provider'],'Dataset':dataset,'Source field':path})
        if row['provider']=='whoop' and dataset=='sleep':
            paths=['/score/stage_summary/'+f for f in ('total_light_sleep_time_milli','total_slow_wave_sleep_time_milli','total_rem_sleep_time_milli')]
            values=dict(leaves(fields)); ns=[number(values.get(p),ASLEEP) for p in paths]
            if all(n is not None for n in ns):emit(row,' + '.join(paths),sum(ns),ASLEEP,table,view,day)
            associated=recoveries.get(row['record_key'],[])
            for recovery in associated:
                for path,value in leaves(recovery['record'].get('vendor_fields',{})):
                    metric=definition('whoop','recovery',path)
                    if metric:emit(recovery,path,value,metric,table,view,day)
        if view=='Workouts':
            a=stamp(context.get('interval_start'));b=stamp(context.get('interval_end'))
            if a and b and b.timestamp()>=a.timestamp():
                # Subtract UTC instants, not wall time across a DST transition.
                seconds=Decimal(str(b.timestamp()))-Decimal(str(a.timestamp()))
                emit(row,'interval_end - interval_start',seconds,ELAPSED,table,view,day)
        metric=period_metric(dataset,fields) if row['provider']=='google_health' else None
        if metric:
            periods.setdefault((day,metric,canonical(fields.get('dataSource',{}))),[]).append(row)

    for (day,metric,_source),rows in periods.items():
        # One total per day and source; overlapping/invalid intervals are reported, never summed.
        table=daily.setdefault(day,{'Date':day}); spans=[]
        for row in rows:
            a=stamp(row['record'].get('interval_start'));b=stamp(row['record'].get('interval_end'))
            spans.append((a.timestamp(),b.timestamp()) if a and b and b.timestamp()>=a.timestamp() else None)
        ordered=sorted(s for s in spans if s)
        if None in spans or any(later[0]<earlier[1] for earlier,later in zip(ordered,ordered[1:])):
            table.setdefault(metric.label,[]).append('Not summed: invalid or overlapping intervals');labels.add(metric.label)
            continue
        seconds=sum(Decimal(str(b))-Decimal(str(a)) for a,b in ordered)
        first=rows[0]
        aggregate={'participant_id':first['participant_id'],'provider':first['provider'],
            'record_key':f'{len(rows)} returned periods','collected_at':max(r['collected_at'] for r in rows),
            'source_response_id':'; '.join(sorted({r['source_response_id'] for r in rows})),
            'record':{'provisional':any(r['record'].get('provisional',True) for r in rows),'timestamp_basis':'vendor_physical_time',
                      'interval_start':min(r['record']['interval_start'] for r in rows),
                      'interval_end':max(r['record']['interval_end'] for r in rows),
                      'resolution_description':first['record'].get('resolution_description')}}
        emit(aggregate,'sum(interval_end - interval_start)',seconds,metric,table,'Daily activity',day)

    def finish(table):
        for k,v in list(table.items()):
            if isinstance(v,list):table[k]=v[0] if len(v)==1 else 'Multiple returned values: '+'; '.join(v)
        return table
    day=start
    while day<end:
        table=daily.get(day.isoformat(),{'Date':day.isoformat()})
        for label in sorted(labels):table.setdefault(label,'Not returned')
        result['Daily activity'].append(finish(table));day+=timedelta(days=1)
    for (view,provider,key),table in sessions.items():result[view].append(finish(table))
    for (view,day,label,unit),values in candidates.items():
        # Ambiguous multiple sources/sessions are not silently summed or averaged.
        if len(values)==1:result['points'].append({'View':view,'Date':day,'Metric':label,'Unit':unit,'Value':float(values[0])})
    result['unmapped']=[dict(zip(('Provider','Dataset','Source field'),key)) for key in sorted({tuple(r.values()) for r in result['unmapped']})]
    return result


def curated_csv(rows):
    if len(rows)>MAX_ROWS:raise SentraError('Readable extract too large; narrow the dates.')
    stream=io.StringIO(newline='')
    columns=list(dict.fromkeys(k for row in rows for k in row))
    writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
    for row in rows:
        writer.writerow({k:csv_value(v.isoformat() if isinstance(v,datetime) else v) for k,v in row.items()})
        if stream.tell()>MAX_BYTES:raise SentraError('Readable extract too large; narrow the dates.')
    payload=stream.getvalue().encode('utf-8-sig')
    if len(payload)>MAX_BYTES:raise SentraError('Readable extract too large; narrow the dates.')
    return payload
