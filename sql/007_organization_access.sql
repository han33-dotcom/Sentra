-- Organization access: who may see which participants, and what each participant agreed to.
-- Implements docs/participation-permissions.md. Read-only for the viewer; writes are admin-only for now.
-- No location, routes, names or contact details of participants are stored here.
begin;
create schema org;
revoke all on schema org from public,anon,authenticated;
create table org.organizations (
 org_id text primary key check (org_id ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
 display_name text not null check (length(display_name) between 1 and 100),
 created_at timestamptz not null default now()
);
-- Organization users sign in with Google; their e-mail is matched case-insensitively.
create table org.org_users (
 org_id text not null references org.organizations,
 email text not null check (email = lower(email) and email ~ '^[^@\s]+@[^@\s]+$'),
 role text not null check (role in ('officer','reviewer')),
 active boolean not null default true,
 created_at timestamptz not null default now(),
 primary key (org_id,email)
);
-- One organization per participant; team is optional and only used for k-anonymous group views.
create table org.memberships (
 participant_id text primary key references audit.participants,
 org_id text not null references org.organizations,
 team text check (team ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
 joined_on date not null,
 unique (participant_id,org_id)
);
-- Append-only consent history: a change or withdrawal is a new row, never an update.
create table org.consents (
 consent_id bigint generated always as identity primary key,
 participant_id text not null,
 org_id text not null,
 consent_version text not null check (consent_version ~ '^[0-9]+\.[0-9]+$'),
 sharing text not null default 'group_only' check (sharing in ('group_only','individual')),
 demonstration boolean not null default false,
 recorded_at timestamptz not null default now(),
 withdrawn boolean not null default false,
 foreign key (participant_id,org_id) references org.memberships(participant_id,org_id)
);
create index consents_latest on org.consents(participant_id,recorded_at desc,consent_id desc);
-- The latest row per participant is the one in force.
create view org.current_consent with (security_invoker=true) as
 select distinct on (participant_id) participant_id,org_id,consent_version,sharing,demonstration,recorded_at,withdrawn
 from org.consents order by participant_id,recorded_at desc,consent_id desc;
do $$ declare t record; begin
 for t in select tablename from pg_tables where schemaname='org' loop
  execute format('alter table org.%I enable row level security',t.tablename);
  execute format('alter table org.%I force row level security',t.tablename);
  execute format('revoke all on org.%I from public,anon,authenticated,sentra_collector',t.tablename);
  execute format('create policy viewer_read on org.%I for select to sentra_viewer using (true)',t.tablename);
 end loop;
end $$;
revoke all on org.current_consent from public,anon,authenticated,sentra_collector;
grant usage on schema org to sentra_viewer;
grant select on org.organizations,org.org_users,org.memberships,org.consents,org.current_consent to sentra_viewer;
commit;
