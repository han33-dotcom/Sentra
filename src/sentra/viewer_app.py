"""Small private audit workspace. No provider access, models or health-risk claims."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import tempfile
import time

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from .access import resolve
from .errors import SentraError
from .viewer_config import emails, runtime_settings
from .viewer_data import BEIRUT, Selection, verified_email, inline_download, measurement_csv, sampling_summary, civil_day, latest_timing, latest_available_day
from .viewer_reader import ViewerReader
from .curated import curate, curated_csv, record_day, stamp
from .metric_dictionary import METRICS
from .viewer_data import MAX_BYTES, MAX_ROWS, fetch_status
from .datasets import canonical
from .viewer_style import BRAND, STYLE


ACCESS_TTL_SECONDS=60  # consent/withdrawal changes apply within a minute


def load_organization_rows(email):
    """Read org users and current consent with a reader bound to the verified identity only."""
    with tempfile.TemporaryDirectory(prefix='sentra-viewer-') as folder:
        credentials,limits,_=runtime_settings(st.secrets,folder)
        reader=ViewerReader(credentials,limits,lambda:email)
        try: return reader.organization_rows()
        finally: reader.close()


def current_access():
    """Team allowlist first (no database read); otherwise organization membership and consent."""
    try:
        allowed=emails(list(st.secrets['viewer']['allowed_emails']))
        claims=st.user.to_dict()
    except Exception:
        raise SentraError('Viewer sign-in configuration is incomplete. Ask the operator to finish setup.') from None
    email=verified_email(claims)
    if email in allowed:
        return resolve(email,team_emails=allowed)
    cached=st.session_state.get('audit_access')
    if cached and cached[0]==email and time.monotonic()-cached[1]<ACCESS_TTL_SECONDS:
        return cached[2]
    users,consents=load_organization_rows(email)
    decision=resolve(email,team_emails=allowed,org_users=users,consents=consents)
    st.session_state['audit_access']=(email,time.monotonic(),decision)
    return decision


def principal():
    return current_access().email


def access_scope(decision):
    """What a cached catalog/board was fetched for: the team, or a specific permitted set."""
    return 'team' if decision.is_team else tuple(sorted(decision.individuals))


def clear_private_state():
    for key in list(st.session_state):
        if key.startswith('audit_'): del st.session_state[key]


def clear_selection_state():
    for key in list(st.session_state):
        if key in ('audit_result','audit_overview','audit_readable_csv','audit_csv','audit_original','audit_original_id','audit_selection') or key.startswith(('audit_chart_choice_','audit_plot_')):
            del st.session_state[key]


def choose_dates(dates):
    st.session_state['audit_date_range']=dates
    st.session_state['audit_dates']=dates
    clear_selection_state()


def remember_dates():
    # Widget state is removed by Streamlit while the board page hides the filters.
    st.session_state['audit_date_range']=st.session_state['audit_dates']
    clear_selection_state()


def measurement_freshness(latest, *, today=None):
    today=today or datetime.now(timezone.utc).astimezone(BEIRUT).date()
    st.caption('Latest measurement day: '+(latest.isoformat() if latest else 'Not supplied'))
    if latest and latest<today:
        st.info(f'The latest available measurements are {(today-latest).days} calendar days old. '
                "These are historical records; today's coverage is not established.")
    elif latest and latest>today:
        st.warning('The latest measurement date is in the future. Ask the operator to check the source dates.')
    elif latest is None:
        st.info('Measurement dates are unavailable. A successful collection or recent publication does not establish recent measurements.')


@contextmanager
def open_reader():
    principal()
    with tempfile.TemporaryDirectory(prefix='sentra-viewer-') as folder:
        credentials,limits,_=runtime_settings(st.secrets,folder)
        # Consult the current decision at every read, so a refresh during an open reader applies.
        reader=ViewerReader(credentials,limits,principal,
                            can_view=lambda participant:current_access().can_view_individual(participant),
                            can_count=lambda participant:bool(current_access().group_contributors([participant])))
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


def readable_chart(points,selection,label,unit,height):
    days=[(selection.start+timedelta(days=i)).isoformat() for i in range((selection.end-selection.start).days)]
    values=pd.DataFrame([{'Date':p['Date'],'Value':p['Value']} for p in points])
    return (alt.Chart(values).mark_circle(size=65,color='#716187',opacity=1).encode(
        x=alt.X('Date:N',scale=alt.Scale(domain=days),axis=alt.Axis(title='Date · Asia/Beirut',
            labelAngle=0,labelExpr='slice(datum.label, 5)',labelOverlap=True)),
        y=alt.Y('Value:Q',title=f'{label} ({unit})'),
        tooltip=[alt.Tooltip('Date:N',title='Date in Beirut'),alt.Tooltip('Value:Q',title=f'{label} ({unit})')])
        .properties(height=height).configure_view(stroke=None)
        .configure_axis(gridColor='#efedf2',domain=False,ticks=False,labelColor='#686471',titleColor='#686471'))


def wellness_board():
    """Embedded wellness board (pseudonymous, internal) from the latest daily refresh."""
    from .processing.board import render
    principal()
    with st.container(key='page-heading'):
        st.caption('PRIVATE WORKSPACE')
        st.title('Wellness board')
    reload=st.sidebar.button('Reload board',icon=':material/refresh:')
    decision=current_access()
    # Refetch when the permitted set changes; filtering a cached copy cannot add newly shared people.
    if reload or 'audit_board' not in st.session_state or st.session_state.get('audit_board_scope')!=access_scope(decision):
        with open_reader() as reader:
            st.session_state['audit_board']=reader.board()
        st.session_state['audit_board_scope']=access_scope(decision)
    # Re-filter the cached board so a withdrawal applies without a manual reload.
    board={**st.session_state['audit_board'],'people':[p for p in st.session_state['audit_board']['people']
                                                         if decision.can_view_individual(p.get('id'))]}
    st.caption("Wellness indicators against each person's own recent pattern; not a medical assessment. "
               f'Thresholds: {board.get("thresholds_status") or "v0 — pending medical expert sign-off"}.')
    latest=civil_day(board.get('data_through'))
    measurement_freshness(date.fromisoformat(latest) if latest else None)
    published=stamp(board.get('built_at'))
    st.caption('Board published: '+(published.isoformat()+' · Asia/Beirut' if published else 'Not supplied')+
               '. Publication time is separate from measurement dates. Reloading checks the published board.')
    components.html(render(board),height=2300,scrolling=True)


def readable_view(selection,result,name):
    curated=result['curated']
    if name!='Data availability':
        rows=curated[name]
        if not rows or (name=='Daily activity' and not any(r.get('Metric') for r in curated['export'] if r['View']==name)):
            st.info('No mapped values returned for these dates. Check Data availability or Audit details.')
        else:
            points=[p for p in curated['points'] if p['View']==name]
            metrics=sorted({p['Metric'] for p in points})
            if metrics:
                preferred_metric={'Daily activity':['Steps','WHOOP strain'],'Sleep':['Asleep'],
                                  'Workouts':['Active duration','WHOOP strain']}[name]
                default=next((m for m in preferred_metric if m in metrics),metrics[0])
                remembered=st.session_state.get('audit_chart_choice_'+name)
                if remembered in metrics:default=remembered
                with st.container(key='metric-panels'):
                    chart,summary=st.columns([2.15,1],gap='medium')
                    with chart,st.container(border=True,key='overview-chart'):
                        st.subheader('Over the selected days')
                        chosen=st.selectbox('Explore a metric',metrics,index=metrics.index(default),key='audit_plot_'+name)
                        st.session_state['audit_chart_choice_'+name]=chosen
                        selected=[p for p in points if p['Metric']==chosen]
                        unit=selected[0]['Unit']
                        last=max(selected,key=lambda p:p['Date'])
                        info=next((r for r in curated['export'] if r['View']==name and r['Metric']==chosen and r['Date']==last['Date']),None)
                        days=len({p['Date'] for p in selected});total=(selection.end-selection.start).days
                        values=[p['Value'] for p in selected]
                        st.altair_chart(readable_chart(selected,selection,chosen,unit,220),width='stretch',theme=None,
                            alt=f'{chosen}: returned points across the selected calendar days. Missing days are empty.')
                        st.caption('Returned points only · gaps stay empty · multiple values on one day are omitted.')
                    with summary,st.container(key='overview-summary'):
                        st.metric(chosen,info['Display'] if info else f'{last["Value"]:,.2f} {unit}',
                            help='Latest unambiguous returned value in this selection; display precision is rounded.')
                        st.caption('Latest returned · '+last['Date'])
                        st.divider()
                        st.metric('Days with a value',f'{days} / {total}')
                        st.caption('One unambiguous numeric value per day')
                        st.divider()
                        st.metric('Returned range',f'{min(values):,.2f}–{max(values):,.2f}')
                        st.caption(unit+' · including provisional values')
                if name=='Sleep' and chosen!='WHOOP recovery':
                    recovery=[p for p in points if p['Metric']=='WHOOP recovery']
                    if recovery:
                        with st.container(border=True,key='recovery-chart'):
                            st.subheader('Associated recovery')
                            st.altair_chart(readable_chart(recovery,selection,'WHOOP recovery','%',140),width='stretch',theme=None,
                                alt='WHOOP recovery associated with selected sleep sessions by sleep ID.')
                            st.caption(f'{len({p["Date"] for p in recovery})}/{total} days · linked by returned sleep ID · WHOOP vendor score')
                with st.expander('About this metric'):
                    if info:st.write(info['Explanation']+' · '+info['Classification'].replace('_',' '))
                    st.caption('Summary values describe the available sample, including provisional values. They are not health or causal interpretations. Charts may round; CSV retains source values.')
            preferred={'Daily activity':['Date','Steps','Distance','Total energy','WHOOP strain','WHOOP recovery'],
                'Sleep':['Date','Asleep','WHOOP recovery','WHOOP sleep performance','Type','Start','End','Status'],
                'Workouts':['Date','Type','Active duration','Session duration','Distance','WHOOP strain','Start','End','Status']}[name]
            columns=list(dict.fromkeys(preferred+[k for r in rows for k in r]))
            shown=[{k:(r[k].strftime('%d %b %H:%M %z') if k in ('Start','End') and isinstance(r[k],datetime) else r[k])
                    for k in columns if k in r} for r in rows]
            with st.container(border=True,key='record-table'):
                st.subheader({'Daily activity':'Daily records','Sleep':'Sleep sessions','Workouts':'Workout sessions'}[name])
                st.caption(f'{len(rows)} rows · times in Asia/Beirut · scroll for all returned fields')
                st.dataframe(display_table(shown),hide_index=True,width='stretch')
                if name=='Sleep':st.caption('Sleep uses its wake date. Naps remain separate; recovery links by sleep ID.')
    else:
        st.subheader('Collection evidence')
        evidence=[]
        for item in result['connections']:
            evidence.append({'Dataset':item['dataset'].replace('_',' ').replace('-',' '),'Authorization':item.get('authorization_status'),
                'Last successful collection':item.get('last_success_at'),
                'Latest measurement point':item.get('latest_point_time'),
                'Latest interval end':item.get('latest_interval_end'),
                'Latest vendor civil day':item.get('latest_civil_day'),
                'Returned fields':item.get('measurement_rows')})
        st.dataframe(display_table(evidence),hide_index=True,width='stretch')
        st.caption('Successful collection means requested pages were stored, not complete wearable measurements. Not returned, explicit null, unscored, provisional and fetch failure are separate states. No rows alone proves neither unsupported nor zero activity.')
        st.dataframe(display_table(result['availability']),hide_index=True,width='stretch')
        with st.expander(f'Fields awaiting a readable definition · {len(curated["unmapped"])}'):
            st.caption('These source fields remain available in full records and original responses.')
            st.dataframe(display_table(curated['unmapped']),hide_index=True,width='stretch')
        with st.expander('Metric definitions and units'):
            definitions=[{'Provider':p,'Dataset':d,'Source field':path,'Metric':m.label,
                'Original unit':m.unit,'Display unit':m.display_unit or ('hours/minutes' if m.duration else m.unit),
                'Classification':m.kind,'Explanation':m.explanation,'Definition':m.reference}
                for (p,d,path),m in METRICS.items() if p==selection.provider]
            st.dataframe(pd.DataFrame(definitions),hide_index=True,width='stretch')
    with st.expander('Timing and source notes'):
        collected=[r.get('last_success_at') for r in result['connections'] if r.get('last_success_at')]
        st.caption('Last successful collection: '+(max(collected,key=lambda v:v.timestamp()).astimezone(BEIRUT).isoformat() if collected else 'Not supplied'))
        latest=max((stamp(r['record'].get('measured_at')) or stamp(r['record'].get('interval_end'))
                    for r in result['records'] if stamp(r['record'].get('measured_at')) or stamp(r['record'].get('interval_end'))),key=lambda v:v.timestamp(),default=None)
        st.caption('Latest selected measurement/interval end: '+(latest.isoformat() if latest else 'No physical time supplied'))
        civil=max((record_day(r) for r in result['records'] if r['record'].get('civil_date') and record_day(r)),default=None)
        if civil:st.caption('Latest selected vendor civil day: '+civil)
        st.caption('Dates and physical timestamps use Asia/Beirut. Sleep uses its wake date; workouts use their start date. Vendor civil dates remain calendar dates. Scores from different providers have different definitions.')
        st.caption('Readable CSV includes exact source values, units, state and references for the selected participant and dates. Detailed field CSV and unchanged original responses are in Audit details.')
    if not current_access().is_team:
        return  # Organization sharing and downloads belong to permitted reports (#42).
    if st.button('Prepare readable CSV',icon=':material/download:'):
        principal();st.session_state['audit_readable_csv']=curated_csv(curated['export'])
    if st.session_state.get('audit_readable_csv') is not None:
        private_download(st.session_state['audit_readable_csv'],f'{selection.participant}-{selection.provider}-{selection.start}-{selection.end}-readable.csv','text/csv')


def group_scope(decision):
    """What cached group data was fetched for: the team, or a specific contributor set."""
    return 'team' if decision.is_team else tuple(sorted(decision.contributors))


def team_consents():
    """Current consent rows for the team view, refreshed like organization decisions."""
    cached=st.session_state.get('audit_team_consents')
    if cached and time.monotonic()-cached[0]<ACCESS_TTL_SECONDS:
        return cached[1]
    _,consents=load_organization_rows(current_access().email)
    st.session_state['audit_team_consents']=(time.monotonic(),consents)
    return consents


def organization_overview():
    """Group summaries and participation for the signed-in user's scope (#39)."""
    from .access import K_ANONYMITY
    from .organization import group_summary, latest_group_day, participation, shown_count, team_scope
    principal()
    with st.container(key='page-heading'):
        st.caption('ORGANIZATION')
        st.title('Organization overview')
    decision=current_access()
    reload=st.sidebar.button('Reload overview',icon=':material/refresh:')
    if reload or st.session_state.get('audit_org_scope')!=group_scope(decision):
        with open_reader() as reader:
            if decision.is_team:
                # The team catalog is the explore pages' catalog; reuse it instead of repeating the query.
                if reload or st.session_state.get('audit_catalog_scope')!='team':
                    st.session_state['audit_catalog']=reader.catalog()
                    st.session_state['audit_catalog_scope']='team'
                catalog=st.session_state['audit_catalog']
            else:
                catalog=reader.group_catalog()
            st.session_state['audit_org']={'catalog':catalog,'board':reader.group_board()}
        st.session_state['audit_org_scope']=group_scope(decision)
    data=st.session_state['audit_org']
    if decision.is_team:
        # Withdrawn or closed consent leaves the team view too; pilot participants have no consent record.
        enrolled,scope=team_scope({r['participant_id'] for r in data['catalog']}
                                  |{p.get('id') for p in data['board']['people']},team_consents())
    else:
        enrolled=scope=set(decision.contributors)
    people=[p for p in data['board']['people'] if p.get('id') in scope and decision.group_contributors([p.get('id')])]
    catalog=[r for r in data['catalog'] if r['participant_id'] in scope and decision.group_contributors([r['participant_id']])]
    today=datetime.now(timezone.utc).astimezone(BEIRUT).date()
    st.caption("Wellness information for health-and-safety conversations, compared with each person's own pattern; "
               'not a medical assessment or diagnosis.')
    counts=participation(scope,catalog,people,today=today,
                         assessment_version=data['board'].get('assessment_version'))
    counts['enrolled']=len(enrolled)
    st.subheader('Participation')
    columns=st.columns(4)
    for column,(label,key,help_text) in zip(columns,(
            ('Enrolled','enrolled','Current consent in an open membership.'),
            ('Connected','connected','At least one wearable connection authorized.'),
            ('Recently contributing','recently_contributing',f"Measurements within the last {counts['recent_days']} days."),
            ('Assessable','assessable',f"A complete assessment on the latest published day within the last {counts['recent_days']} days."))):
        # Organization users see small activity counts only as '<k'; they could single out group-only people.
        value=counts[key] if decision.is_team or key=='enrolled' else shown_count(counts[key])
        column.metric(label,value,help=help_text)
    st.caption('Each state is counted separately; being connected does not mean recent data arrived.')
    if decision.is_team and (pilot:=len(scope-enrolled)):
        st.caption(f'Team view: also includes {pilot} pilot participant(s) with data but no recorded consent. '
                   'Withdrawn participants are excluded.')
    st.subheader('Group summary')
    end=latest_group_day(people)
    if not end:
        st.info('No processed days are published yet.')
        return
    through=end.isoformat()
    period=st.radio('Period',('Latest day','Last 7 days'),horizontal=True,key='audit_org_period')
    rows=group_summary(people,scope,end=end,days=1 if period=='Latest day' else 7)
    st.dataframe([{'Measure':r['label'],
                   'Device':r['device'] or '',
                   'Group median':f"{r['value']:g} {r['unit']}" if r['status']=='available' else 'Not shown',
                   'Contributors':shown_count(r['contributors']),
                   'Note':r['reason'] or ''} for r in rows],hide_index=True,width='stretch')
    st.caption(f'Published days through {through}. Each device is summarized separately, and each statistic needs at '
               f'least {K_ANONYMITY} eligible contributors of its own; smaller groups are never shown. '
               'Assessable counts use complete, recent assessments from the current board contract.')


def profiles_page():
    """Individual profiles for participants who chose individual sharing (#39)."""
    from .organization import profile
    principal()
    with st.container(key='page-heading'):
        st.caption('ORGANIZATION')
        st.title('Profiles')
    decision=current_access()
    reload=st.sidebar.button('Reload profiles',icon=':material/refresh:')
    if reload or 'audit_board' not in st.session_state or st.session_state.get('audit_board_scope')!=access_scope(decision):
        with open_reader() as reader:
            st.session_state['audit_board']=reader.board()
        st.session_state['audit_board_scope']=access_scope(decision)
    people=[p for p in st.session_state['audit_board']['people'] if decision.can_view_individual(p.get('id'))]
    if not people:
        st.info('No participant with published days has shared individual details with you.')
        return
    person=next(p for p in people if p['id']==st.selectbox('Participant ID',sorted(p['id'] for p in people)))
    today=datetime.now(timezone.utc).astimezone(BEIRUT).date()
    summary=profile(person,today=today)
    through=summary['data_through']
    st.caption(f"Device: {summary['device'] or 'Not supplied'} · Latest published day: "
               +(f"{through.isoformat()} ({summary['days_old']} days ago)" if through else 'none')
               +f" · Days with data in the last 7: {summary['days_with_data_last_7']}")
    st.dataframe([{'Measure':m['label'],
                   'Latest':'' if m['value'] is None else f"{m['value']:g} {m['unit']}",
                   'Usual (own baseline)':'' if m['baseline'] is None else f"{m['baseline']:g} {m['unit']}",
                   'Difference':'' if m['difference'] is None else f"{m['difference']:+g} {m['unit']}",
                   'Note':m['note'] or ''} for m in summary['metrics']],hide_index=True,width='stretch')
    st.caption("Compared with this person's own recent pattern; not a medical assessment. Missing values stay missing.")
    observations_section(person,today=today,assessment_version=st.session_state['audit_board'].get('assessment_version'))


OBSERVATION_KINDS={'wellness':'Wellness observation','assessment':'Assessment limits','collection':'Data collection'}


def observations_section(person,*,today,assessment_version):
    """Explained observations for one permitted person's latest published day (#41)."""
    from .observations import observations
    st.subheader('Observations')
    items=observations(person,today=today,assessment_version=assessment_version)
    if not items:
        st.info('No observation for the latest published day.')
    for item in items:
        with st.container(border=True):
            when=f" · {item['day'].isoformat()}" if item['day'] else ''
            st.caption(OBSERVATION_KINDS[item['kind']].upper()+when)
            st.markdown(f"**{item['title']}**  \n{item['detail']}")
            if item['readings']:
                st.dataframe([{'Reading':k,'Value':v} for k,v in item['readings']],hide_index=True,width='stretch')
            for note in item['limitations']:
                st.caption(note)


def main():
    st.set_page_config(page_title='Sentra · Wearable explorer',page_icon='🔎',layout='wide')
    st.html(STYLE)
    st.sidebar.html(BRAND)
    try:
        logged_in=st.user.is_logged_in
        if not logged_in:
            clear_private_state()
            st.title('Your wearable data, together.')
            st.caption('Sentra · private team workspace')
            st.info('Sign in with an authorized team Google account to inspect data and prepare downloads.')
            if st.button('Sign in with Google',type='primary'):
                try: st.login()
                except Exception: st.error('Sign-in setup is incomplete. Ask the operator to check the identity client and callback.')
            st.stop()
        if st.sidebar.button('Sign out'):
            clear_private_state()
            st.logout()
            st.stop()
        identity=principal()
        if st.session_state.get('audit_owner')!=identity:
            # Keep only the access decision just made for this same identity.
            decision=st.session_state.get('audit_access')
            clear_private_state()
            if decision and decision[0]==identity:
                st.session_state['audit_access']=decision
            st.session_state['audit_owner']=identity
        page=st.sidebar.radio('Explore',('Daily activity','Sleep','Workouts','Data availability','Wellness board',
            'Organization overview','Profiles'),key='explore',label_visibility='collapsed',width='stretch')
        st.sidebar.divider()
        if page=='Wellness board':
            wellness_board()
            return
        if page=='Organization overview':
            organization_overview()
            return
        if page=='Profiles':
            profiles_page()
            return
        decision=current_access()
        # Refetch when the permitted set changes; filtering a cached copy cannot add newly shared people.
        if 'audit_catalog' not in st.session_state or st.session_state.get('audit_catalog_scope')!=access_scope(decision):
            with open_reader() as reader:
                st.session_state['audit_catalog']=reader.catalog()
            st.session_state['audit_catalog_scope']=access_scope(decision)
        # Re-filter cached rows so consent changes apply without a manual refresh.
        catalog=[r for r in st.session_state['audit_catalog'] if decision.can_view_individual(r['participant_id'])]
        if st.session_state.get('audit_participant') and not decision.can_view_individual(st.session_state['audit_participant']):
            clear_selection_state()
        if not catalog:
            st.info('No collected datasets are available yet.' if current_access().is_team else
                    'No participant has shared individual details with your organization yet.')
            if st.sidebar.button('Check again',icon=':material/refresh:'):
                clear_private_state()
                st.rerun()
            st.stop()
        participants=sorted({r['participant_id'] for r in catalog})
        remembered=st.session_state.get('audit_participant')
        participant=st.sidebar.selectbox('Participant ID',participants,
            index=participants.index(remembered) if remembered in participants else 0)
        st.session_state['audit_participant']=participant
        providers=sorted({r['provider'] for r in catalog if r['participant_id']==participant})
        remembered=st.session_state.get('audit_provider')
        provider=st.sidebar.selectbox('Provider',providers,
            index=providers.index(remembered) if remembered in providers else 0,
            format_func=lambda p:{'google_health':'Google Health / Fitbit','whoop':'WHOOP'}.get(p,p))
        st.session_state['audit_provider']=provider
        datasets=sorted({r['dataset'] for r in catalog if r['participant_id']==participant and r['provider']==provider})
        today=datetime.now(timezone.utc).astimezone(BEIRUT).date()
        latest=latest_available_day(catalog,participant,provider)
        end=min(latest,today) if latest else today
        latest_week=(end-timedelta(days=6),end)
        if st.session_state.get('audit_date_scope')!=(participant,provider):
            st.session_state['audit_date_scope']=(participant,provider)
            st.session_state['audit_date_range']=latest_week
            st.session_state.pop('audit_dates',None)
        if 'audit_dates' not in st.session_state:
            st.session_state['audit_dates']=st.session_state['audit_date_range']
        st.sidebar.button('Latest available week',disabled=latest is None,
            on_click=choose_dates,args=(latest_week,))
        st.sidebar.button('Last 7 calendar days',on_click=choose_dates,
            args=((today-timedelta(days=6),today),))
        dates=st.sidebar.date_input('Dates in Asia/Beirut',key='audit_dates',on_change=remember_dates)
        st.sidebar.caption('Up to 31 days · final date included')
        if st.sidebar.button('Refresh catalog and clear results',icon=':material/refresh:'):
            clear_private_state()
            st.session_state['audit_owner']=identity
            st.rerun()
        with st.sidebar.expander('Audit filters'):
            dataset=st.selectbox('Dataset',datasets)
            scope=(participant,provider,dataset)
            if st.session_state.get('audit_metric_scope')!=scope:
                with open_reader() as reader:
                    st.session_state['audit_metrics']=reader.metrics(Selection(*scope,today-timedelta(days=7),today+timedelta(days=1)))
                st.session_state['audit_metric_scope']=scope
                st.session_state.pop('metric_filter',None)
            definitions=st.session_state['audit_metrics']
            names=sorted({r['metric'] for r in definitions},key=lambda name:
                         (all(r['value_kind']=='unknown' for r in definitions if r['metric']==name),name))
            metric=st.selectbox('Metric',['All returned fields']+names,key='metric_filter')
            search=st.text_input('Search returned fields',max_chars=100)
        if not isinstance(dates,tuple) or len(dates)!=2:
            clear_selection_state()
            st.info('Choose both dates to load a selection.')
            st.stop()
        selection=Selection(*scope,dates[0],dates[1]+timedelta(days=1),
                            '' if metric=='All returned fields' else metric,search)
        if st.session_state.get('audit_selection')!=selection:
            clear_selection_state()
            st.session_state['audit_selection']=selection
        with st.container(key='page-heading'):
            heading,action=st.columns([3,1],vertical_alignment='center')
            with heading:
                st.caption('PRIVATE WORKSPACE')
                st.title(page)
                st.caption(f'{participant} · '+{'google_health':'Google Health / Fitbit','whoop':'WHOOP'}.get(provider,provider)+
                    f' · {dates[0]:%d %b} – {dates[1]:%d %b %Y}')
            with action:
                load=st.button('Load selected data',type='primary',width='stretch',icon=':material/refresh:')
        if load:
            for key in ('audit_result','audit_csv','audit_original','audit_original_id','audit_readable_csv','audit_overview'):
                st.session_state.pop(key,None)
            records=[];availability=[]
            with open_reader() as reader:
                for name in datasets:
                    if name.startswith('minute_') or name=='original_heart-rate':continue
                    selected=Selection(participant,provider,name,selection.start,selection.end)
                    records.extend(reader.records(selected))
                    if len(records)>MAX_ROWS or sum(len(canonical(r['record']).encode()) for r in records)>MAX_BYTES:
                        raise SentraError('Overview too large. Narrow the dates; no partial result returned.')
                    state=reader.status(selected)
                    fetch,last_success=fetch_status(state,name)
                    availability.append({'Dataset':name.replace('_',' ').replace('-',' '),'Fetch state':fetch,
                                         'Last successful collection':last_success})
                recovered=reader.recoveries(selection,records)
                known={(r['provider'],r['dataset'],r['record_key']) for r in records}
                records.extend(r for r in recovered if (r['provider'],r['dataset'],r['record_key']) not in known)
                if len(records)>MAX_ROWS or sum(len(canonical(r['record']).encode()) for r in records)>MAX_BYTES:
                    raise SentraError('Overview too large. Narrow the dates; no partial result returned.')
                catalog=reader.catalog()
                st.session_state['audit_catalog']=catalog
                st.session_state['audit_overview']={'curated':curate(records,selection.start,selection.end),
                    'records':records,'availability':availability,'connections':[r for r in catalog if
                    r['participant_id']==participant and r['provider']==provider]}
        measurement_freshness(latest_available_day(st.session_state['audit_catalog'],participant,provider),today=today)
        st.caption('Dates reflect the available catalog, refreshed when data is loaded or the catalog is refreshed. '
                   'Collection success does not establish complete measurement coverage.')
        overview=st.session_state.get('audit_overview')
        if overview is not None:
            principal();readable_view(selection,overview,page)
        else:
            with st.container(border=True):
                st.subheader('Start with your selected days')
                st.caption('Choose a participant, provider and dates, then load their returned data. Changing filters clears results and prepared downloads.')
        if not current_access().is_team:
            st.stop()  # Source fields and original responses stay with Sentra operators.
        with st.expander('Audit details · source fields, exact values and original responses'):
            st.caption('These details use the sidebar audit dataset, metric and text filters. Full record context remains available for the overview dates.')
            if overview is not None:
                if st.checkbox('Show full returned record context'):
                    principal();st.json(overview['records'],expanded=False)
            if st.button('Load audit details'):
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
                principal();audit_view(selection,result)
    except SentraError as error:
        clear_private_state()
        st.error(str(error))
    except Exception:
        clear_private_state()
        st.error('Viewer request stopped. No partial download prepared; ask the operator to check configuration and capacity.')
