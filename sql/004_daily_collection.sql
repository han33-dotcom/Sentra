-- Stage 4: durable private cursors/control; no existing health data is dropped.
begin;
create table collector_private.daily_jobs (
 participant_id text not null references audit.participants, provider text not null,
 dataset text not null, job_key text not null, progress jsonb not null,
 updated_at timestamptz not null default now(),
 primary key(participant_id,provider,dataset,job_key)
);
create table collector_private.observation_control (
 singleton boolean primary key default true check(singleton), settings jsonb not null,
 updated_at timestamptz not null default now()
);
insert into collector_private.observation_control values(true,'{"enabled":false}'::jsonb,now());
do $$ declare t text; begin
 foreach t in array array['daily_jobs','observation_control'] loop
  execute format('alter table collector_private.%I enable row level security',t);
  execute format('alter table collector_private.%I force row level security',t);
  execute format('revoke all on collector_private.%I from public,anon,authenticated,sentra_viewer',t);
  execute format('grant select,insert,update,delete on collector_private.%I to sentra_collector',t);
  execute format('create policy collector_access on collector_private.%I to sentra_collector using(true) with check(true)',t);
 end loop;
end $$;
-- Compare both legacy expanded and compact records, ignoring fetch provenance
-- while preserving every vendor field, time, unit, resolution and derived value.
create function collector_private.record_semantics(r jsonb) returns jsonb
language sql immutable set search_path='' as $$
 select jsonb_build_object('context',r-'measurements'-'collected_at'-'source_response_id'-'source_pointer'-'associated_cycle_source_response_id',
  'measurements',coalesce((select jsonb_agg(
     ((r-'measurements'-'vendor_fields'-'score_state'-'session_type')||m)
       -'collected_at'-'source_response_id'-'source_pointer'-'associated_cycle_source_response_id'
       order by m->>'metric') from jsonb_array_elements(r->'measurements') m),'[]'::jsonb))
$$;
revoke all on function collector_private.record_semantics(jsonb) from public,anon,authenticated,sentra_viewer;
grant execute on function collector_private.record_semantics(jsonb) to sentra_collector;
commit;
