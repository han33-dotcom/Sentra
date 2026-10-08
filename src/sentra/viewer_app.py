"""Small private audit workspace. No provider access, models or health-risk claims."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import tempfile

import pandas as pd
import streamlit as st

from .errors import SentraError
from .viewer_config import emails, runtime_settings
from .viewer_data import BEIRUT, Selection, authorize, inline_download, measurement_csv, sampling_summary, civil_day, latest_timing
from .viewer_reader import ViewerReader


def principal():
    try:
        allowed=emails(list(st.secrets['viewer']['allowed_emails']))
        claims=st.user.to_dict()
    except Exception:
        raise SentraError('Viewer sign-in configuration is incomplete. Ask the operator to finish setup.') from None
    return authorize(claims,allowed)


def clear_private_state():
    for key in list(st.session_state):
        if key.startswith('audit_'): del st.session_state[key]


@contextmanager
def open_reader():
    principal()
    with tempfile.TemporaryDirectory(prefix='sentra-viewer-') as folder:
        credentials,limits,_=runtime_settings(st.secrets,folder)
        reader=ViewerReader(credentials,limits,principal)
        try: yield reader
        finally: reader.close()


def display_table(rows):
    # Exact numeric text remains visible and survives CSV; charts explicitly use floats.
    def text(value):
        if isinstance(value,datetime): return value.astimezone(BEIRUT).isoformat()
        if isinstance(value,(dict,list)): return str(value)
        return str(value) if value is not None else None
    return pd.DataFrame([{k:text(v) for k,v in row.items()} for row in rows])


def private_download(payload,filename,mime):
    principal()
    st.iframe(inline_download(payload,filename,mime),height=70,alt='Private extract download')


def plot_selected(rows):
    groups={(r['metric'],r.get('unit'),r.get('resolution_seconds')) for r in rows if r.get('value') is not None}
    if len(groups)!=1:
        st.caption('Select one numeric metric and resolution to show a chart with consistent units.')
        return
    values=[]
    for r in rows:
        if r.get('value') is None: continue
        stamp=r.get('measured_at') or r.get('interval_start')
        if stamp:
            stamp=stamp.astimezone(BEIRUT).isoformat()
        else:
            stamp=civil_day(r.get('civil_date'))
            if not stamp: continue
        values.append({'time':stamp,'value':float(r['value'])})
    if values:
        st.caption('Returned values only; chart conversion may round. Civil-date summaries remain calendar days. No interpolation or gap filling.')
        st.scatter_chart(pd.DataFrame(values),x='time',y='value',height=260)


def audit_view(selection,result):
    rows=result['rows']
    a=sampling_summary(rows)
    first,second,third,fourth=st.columns(4)
    first.metric('Returned fields',a['returned_rows'])
    second.metric('Explicitly missing',a['explicit_missing'])
    third.metric('Unscored fields',a['unscored_rows'])
    fourth.metric('Provisional fields',a['provisional_rows'])
    st.caption('A returned field is not necessarily a sensor measurement. Units and value kind distinguish measurements, vendor summaries, calculations, scores and unknown fields.')
    st.caption('All displayed timestamps use Asia/Beirut; CSV preserves timestamp offsets. A successful fetch does not establish complete wearable coverage.')
    tabs=st.tabs(['Measurements','Sessions','Coverage and runs','Original responses','Storage'])
    with tabs[0]:
        if rows:
            timing=latest_timing(rows)
            for field,label in (('latest_point_time','Latest selected measurement point'),
                                ('latest_interval_end','Latest selected interval end'),
                                ('latest_civil_day','Latest selected vendor civil day')):
                value=timing[field]
                if isinstance(value,datetime): value=value.astimezone(BEIRUT).isoformat()
                st.write(label+': '+(str(value) if value is not None else 'Not supplied in this selection.'))
            plot_selected(rows)
            st.dataframe(display_table(rows),hide_index=True,width='stretch')
            if st.button('Prepare filtered CSV'):
                principal()
                st.session_state['audit_csv']=measurement_csv(rows)
            if st.session_state.get('audit_csv') is not None:
                private_download(st.session_state['audit_csv'],
                    f'{selection.participant}-{selection.provider}-{selection.dataset}-{selection.start}-{selection.end}.csv','text/csv')
        else:
            st.info('No returned fields match these filters. This alone cannot distinguish unavailable, unsupported or delayed data.')
    with tabs[1]:
        st.caption('Sessions whose records contain fields matching the same filters. Overlapping intervals are included; metric/text filtering also limits sessions.')
        st.dataframe(display_table(result['sessions']),hide_index=True,width='stretch')
    with tabs[2]:
        st.write('Observed sampling intervals (seconds): '+str(a['observed_intervals_seconds'][:50]))
        st.write('Gap candidates exceeding 1.5 × stated aggregation interval: '+str(a['gap_candidates']))
        st.caption('These intervals come from returned timestamps within each metric/unit/resolution. Gaps are candidates, not proof of lost sensor readings. A missing numeric mapping is different from an explicit null vendor value.')
        st.write('Rows without a mapped numeric value: '+str(a['no_numeric_value']))
        st.write('Dataset connection and last successful collection')
        st.dataframe(display_table(result['status']['connection']),hide_index=True,width='stretch')
        st.caption('Covered intervals mean requested pages were stored. Runs below are provider-wide; inspect dataset-specific failures. Recent data stays provisional because late syncs/corrections remain possible.')
        st.write('Latest provider runs and actual execution times')
        st.dataframe(display_table(result['status']['runs']),hide_index=True,width='stretch')
    with tabs[3]:
        sources=result['manifests']
        st.caption('Unchanged API responses, gzip-compressed. Requested resolution appears below. Aggregated responses and vendor summaries are not raw physical sensor signals. Each download contains the whole source page, which can include other fields/dates for this participant; CSV follows the exact filters.')
        st.dataframe(display_table(sources),hide_index=True,width='stretch')
        if sources:
            choices={r['response_id']:r for r in sources}
            selected=st.selectbox('Original response',list(choices),format_func=lambda key:
                choices[key]['requested_resolution']+' · '+str(choices[key]['collected_at'])+' · '+key[:12])
            if st.session_state.get('audit_original_id')!=selected:
                st.session_state.pop('audit_original',None)
                st.session_state['audit_original_id']=selected
            if st.button('Prepare original response'):
                principal()
                with open_reader() as reader:
                    st.session_state['audit_original']=reader.original(selected,selection)
            if st.session_state.get('audit_original') is not None:
                private_download(st.session_state['audit_original'],
                    f'{selection.participant}-{selection.provider}-{selection.dataset}-{choices[selected]["content_sha256"]}.json.gz','application/gzip')
    with tabs[4]:
        usage=result['usage']
        st.caption('Project usage and conservative monthly egress reservation, captured when you loaded this selection. The Supabase organization dashboard remains the billing authority.')
        limits=result['limits']
        for key,label,ceiling in (('database_bytes','Database',limits.database_bytes-limits.reserve_bytes),
                                  ('object_bytes','Original files',limits.object_bytes-limits.reserve_bytes),
                                  ('egress_bytes','Monthly reserved egress',limits.monthly_egress_bytes)):
            actual=usage[key]
            st.write(f'{label}: {actual/1_000_000:.2f} MB / safety threshold {ceiling/1_000_000:.0f} MB')
            st.progress(min(1.0,actual/ceiling))
            if actual>=ceiling*.8: st.warning(label+' is approaching its safety threshold. Collection/downloads stop before configured limits.')
        st.write('Egress baseline last verified: '+str(usage.get('budget_verified_at')))
        st.write('Observation control: '+str(usage.get('observation')))


def main():
    st.set_page_config(page_title='Sentra · Wearable audit',page_icon='🔎',layout='wide')
    st.title('Sentra wearable audit')
    st.caption('Private research workspace · institutional health and safety')
    try:
        logged_in=st.user.is_logged_in
        if not logged_in:
            clear_private_state()
            st.info('Sign in with an authorized team Google account to inspect data and prepare downloads.')
            if st.button('Sign in with Google'):
                try: st.login()
                except Exception: st.error('Sign-in setup is incomplete. Ask the operator to check the identity client and callback.')
            st.stop()
        if st.sidebar.button('Sign out'):
            clear_private_state()
            st.logout()
            st.stop()
        identity=principal()
        if st.session_state.get('audit_owner')!=identity:
            clear_private_state()
            st.session_state['audit_owner']=identity
        if st.sidebar.button('Refresh catalog and clear results'):
            clear_private_state()
            st.session_state['audit_owner']=identity
        if 'audit_catalog' not in st.session_state:
            with open_reader() as reader:
                st.session_state['audit_catalog']=reader.catalog()
        catalog=st.session_state['audit_catalog']
        if not catalog:
            st.info('No collected datasets are available yet.')
            st.stop()
        participant=st.sidebar.selectbox('Participant ID',sorted({r['participant_id'] for r in catalog}))
        provider=st.sidebar.selectbox('Provider',sorted({r['provider'] for r in catalog if r['participant_id']==participant}))
        datasets=sorted({r['dataset'] for r in catalog if r['participant_id']==participant and r['provider']==provider})
        dataset=st.sidebar.selectbox('Dataset',datasets)
        scope=(participant,provider,dataset)
        today=datetime.now(timezone.utc).astimezone(BEIRUT).date()
        if st.session_state.get('audit_metric_scope')!=scope:
            with open_reader() as reader:
                st.session_state['audit_metrics']=reader.metrics(Selection(*scope,today-timedelta(days=7),today+timedelta(days=1)))
            st.session_state['audit_metric_scope']=scope
            st.session_state.pop('metric_filter',None)
        definitions=st.session_state['audit_metrics']
        names=sorted({r['metric'] for r in definitions},key=lambda name:
                     (all(r['value_kind']=='unknown' for r in definitions if r['metric']==name),name))
        metric=st.sidebar.selectbox('Metric',names+['All returned fields'],key='metric_filter')
        dates=st.sidebar.date_input('Dates in Asia/Beirut',value=(today-timedelta(days=7),today))
        search=st.sidebar.text_input('Search returned fields',max_chars=100)
        if not isinstance(dates,tuple) or len(dates)!=2:
            for key in ('audit_result','audit_csv','audit_original','audit_original_id','audit_selection'):
                st.session_state.pop(key,None)
            st.info('Choose both dates to load a selection.')
            st.stop()
        selection=Selection(*scope,dates[0],dates[1]+timedelta(days=1),
                            '' if metric=='All returned fields' else metric,search)
        if st.session_state.get('audit_selection')!=selection:
            for key in ('audit_result','audit_csv','audit_original','audit_original_id'):
                st.session_state.pop(key,None)
            st.session_state['audit_selection']=selection
        st.write(f'{participant} · {provider} · {dataset}')
        st.caption('Choose filters, then load. Changing filters clears results and prepared downloads. The end date shown in the filters is included.')
        if st.button('Load selected data',type='primary'):
            for key in ('audit_csv','audit_original','audit_original_id'):
                st.session_state.pop(key,None)
            with open_reader() as reader:
                rows=reader.measurements(selection)
                st.session_state['audit_result']={
                    'rows':rows,'sessions':reader.sessions(selection,rows),
                    'manifests':reader.manifests(selection,rows),'status':reader.status(selection),
                    'usage':reader.usage(),'limits':reader.limits}
        result=st.session_state.get('audit_result')
        if result is not None:
            principal()
            audit_view(selection,result)
    except SentraError as error:
        clear_private_state()
        st.error(str(error))
    except Exception:
        clear_private_state()
        st.error('Viewer request stopped. No partial download prepared; ask the operator to check configuration and capacity.')
