-- Apply after 007, as postgres. Password is set privately by the operator.
-- This service can write enrollment and encrypted credentials, never read health rows.
begin;
create role sentra_enrollment login nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
create schema enrollment_private;
revoke all on schema enrollment_private from public,anon,authenticated,sentra_viewer;
create sequence enrollment_private.participant_number start 100 maxvalue 9999 no cycle;
create table enrollment_private.invites (
 invite_hash text primary key check (invite_hash ~ '^[a-f0-9]{64}$'),
 org_id text not null references org.organizations,
 remaining integer not null check (remaining between 0 and 100),
 expires_at timestamptz not null
);
create table enrollment_private.identities (
 provider text not null check (provider in ('google_health','whoop')),
 identity_hash text not null check (identity_hash ~ '^[a-f0-9]{64}$'),
 participant_id text not null references audit.participants,
 primary key(provider,identity_hash), unique(provider,participant_id)
);
create table enrollment_private.sessions (
 session_hash text primary key check (session_hash ~ '^[a-f0-9]{64}$'),
 encrypted_state bytea not null check (octet_length(encrypted_state) <= 16384),
 expires_at timestamptz not null
);
create index enrollment_sessions_expiry on enrollment_private.sessions(expires_at);
create table enrollment_private.rate_limits (
 bucket_hash text primary key,
 attempts integer not null,
 expires_at timestamptz not null
);
do $$ declare t text; begin
 foreach t in array array['invites','identities','sessions','rate_limits'] loop
  execute format('alter table enrollment_private.%I enable row level security',t);
  execute format('alter table enrollment_private.%I force row level security',t);
  execute format('revoke all on enrollment_private.%I from public,anon,authenticated,sentra_viewer,sentra_collector',t);
  execute format('create policy enrollment_access on enrollment_private.%I to sentra_enrollment using(true) with check(true)',t);
 end loop;
end $$;
grant usage on schema enrollment_private,org,audit,collector_private to sentra_enrollment;
grant usage on sequence enrollment_private.participant_number to sentra_enrollment;
grant select,insert,update,delete on enrollment_private.sessions,enrollment_private.rate_limits to sentra_enrollment;
grant select,insert,update on enrollment_private.invites to sentra_enrollment;
grant select,insert on enrollment_private.identities to sentra_enrollment;
grant select,insert on audit.participants to sentra_enrollment;
create policy enrollment_read_participants on audit.participants for select to sentra_enrollment using(true);
create policy enrollment_add_participants on audit.participants for insert to sentra_enrollment with check(true);
grant select on org.organizations,org.current_consent to sentra_enrollment;
grant select,insert,update on org.memberships to sentra_enrollment;
grant select,insert on org.consents to sentra_enrollment;
grant usage on sequence org.memberships_membership_id_seq,org.consents_consent_id_seq to sentra_enrollment;
create policy enrollment_org_read on org.organizations for select to sentra_enrollment using(true);
create policy enrollment_memberships on org.memberships to sentra_enrollment using(true) with check(true);
create policy enrollment_consent_read on org.consents for select to sentra_enrollment using(true);
create policy enrollment_consent_append on org.consents for insert to sentra_enrollment with check(true);
grant select,insert,update on collector_private.provider_credentials to sentra_enrollment;
create policy enrollment_credentials on collector_private.provider_credentials to sentra_enrollment using(true) with check(true);
grant execute on function collector_private.reserve_egress(bigint,bigint) to sentra_enrollment;

-- A bounded metadata summary. No readings, values, original responses or free text.
create function enrollment_private.participation_status(pid text) returns jsonb
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
    then left(m.civil_date#>>'{}',10) end)) from audit.measurements m
    where m.participant_id=pid and m.availability='available' and m.value is not null),
  'collection_paused',not coalesce((select (settings->>'enabled')::boolean from collector_private.observation_control where singleton),false),
  'assessment','not_available')
$$;
revoke all on function enrollment_private.participation_status(text) from public,anon,authenticated,sentra_viewer,sentra_collector;
grant execute on function enrollment_private.participation_status(text) to sentra_enrollment;

-- Collector discovery returns only self-enrolled, currently consenting connections.
create function collector_private.enrolled_connections() returns table(participant_id text,provider text)
language sql stable security definer set search_path='' as $$
 select distinct i.participant_id,i.provider from enrollment_private.identities i
 join org.current_consent c on c.participant_id=i.participant_id
 join collector_private.provider_credentials p on p.participant_id=i.participant_id and p.provider=i.provider
 where not c.withdrawn and c.membership_open and p.refresh_status <> 'withdrawn'
 order by i.participant_id,i.provider limit 101
$$;
revoke all on function collector_private.enrolled_connections() from public,anon,authenticated,sentra_viewer,sentra_enrollment;
grant execute on function collector_private.enrolled_connections() to sentra_collector;
commit;
