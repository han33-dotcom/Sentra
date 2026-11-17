-- Apply after 008 and 009. Deployment alone does not enable compact writes or collection.
-- An operator enables this only during the reviewed storage rollout, with collection paused.
begin;
create table collector_private.compact_control (
 singleton boolean primary key default true check(singleton),
 enabled boolean not null default false
);
insert into collector_private.compact_control values (true,false);
alter table collector_private.compact_control enable row level security;
alter table collector_private.compact_control force row level security;
revoke all on collector_private.compact_control from public,anon,authenticated,sentra_viewer,sentra_enrollment;
grant select on collector_private.compact_control to sentra_collector;
create policy collector_read on collector_private.compact_control for select to sentra_collector using(true);
-- Keep the bounded enrollment metadata summary compatible with compact-only readings.
create or replace function enrollment_private.participation_status(pid text) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object(
  'latest_received_at',(select max(collected_at) from audit.raw_response_manifest where participant_id=pid),
  'latest_measurement_day',(select max(coalesce(
    (coalesce(m.measured_at,m.interval_start) at time zone 'Asia/Beirut')::date::text,
    case when coalesce(m.civil_date->>'year',m.civil_date#>>'{date,year}') ~ '^[0-9]{4}$'
      and coalesce(m.civil_date->>'month',m.civil_date#>>'{date,month}') ~ '^[0-9]{1,2}$'
      and coalesce(m.civil_date->>'day',m.civil_date#>>'{date,day}') ~ '^[0-9]{1,2}$'
    then coalesce(m.civil_date->>'year',m.civil_date#>>'{date,year}') || '-' ||
      lpad(coalesce(m.civil_date->>'month',m.civil_date#>>'{date,month}'),2,'0') || '-' ||
      lpad(coalesce(m.civil_date->>'day',m.civil_date#>>'{date,day}'),2,'0')
    when jsonb_typeof(m.civil_date)='string' and (m.civil_date#>>'{}') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
    then left(m.civil_date#>>'{}',10) end)) from (select * from audit.measurements union all select c.* from audit.series_rows c where not exists (select 1 from audit.measurements m where (m.participant_id,m.provider,m.dataset,
    m.record_key,m.metric)=(c.participant_id,c.provider,c.dataset,c.record_key,c.metric))
    and exists (select 1 from audit.records r where (r.participant_id,r.provider,r.dataset,r.record_key)=
    (c.participant_id,c.provider,c.dataset,c.record_key) and r.source_response_id=c.source_response_id)) m
    where m.participant_id=pid and m.availability='available' and m.value is not null),
  'collection_paused',not coalesce((select (settings->>'enabled')::boolean from collector_private.observation_control where singleton),false),
  'assessment','not_available')
$$;
revoke all on function enrollment_private.participation_status(text) from public,anon,authenticated,sentra_viewer,sentra_collector;
grant execute on function enrollment_private.participation_status(text) to sentra_enrollment;

commit;
