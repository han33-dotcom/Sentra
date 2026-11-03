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
-- Membership episodes: a participant can leave one organization and later join another.
-- At most one open episode per participant; team is optional and only used for k-anonymous group views.
create table org.memberships (
 membership_id bigint generated always as identity primary key,
 participant_id text not null references audit.participants,
 org_id text not null references org.organizations,
 team text check (team ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
 joined_on date not null,
 left_on date check (left_on >= joined_on),
 unique (membership_id,participant_id,org_id)
);
create unique index memberships_one_open on org.memberships(participant_id) where left_on is null;
-- Append-only consent history: a change or withdrawal is a new row in the same episode.
create table org.consents (
 consent_id bigint generated always as identity primary key,
 membership_id bigint not null,
 participant_id text not null,
 org_id text not null,
 consent_version text not null check (consent_version ~ '^[0-9]+\.[0-9]+$'),
 sharing text not null default 'group_only' check (sharing in ('group_only','individual')),
 demonstration boolean not null default false,
 recorded_at timestamptz not null default now(),
 withdrawn boolean not null default false,
 foreign key (membership_id,participant_id,org_id) references org.memberships(membership_id,participant_id,org_id)
);
create index consents_latest on org.consents(participant_id,recorded_at desc,consent_id desc);
-- Guards against ordinary writes (including the admin enrollment path), not deliberate schema changes.
create function org.reject_consent_change() returns trigger
language plpgsql set search_path='' as $$
begin
 raise exception 'org.consents is append-only; record a new consent row instead' using errcode='42501';
end $$;
create trigger consents_append_only before update or delete on org.consents
 for each row execute function org.reject_consent_change();
create trigger consents_no_truncate before truncate on org.consents
 for each statement execute function org.reject_consent_change();
-- An episode may be closed or its team changed; who and where it refers to never changes.
create function org.reject_membership_rewrite() returns trigger
language plpgsql set search_path='' as $$
begin
 if new.participant_id <> old.participant_id or new.org_id <> old.org_id or new.joined_on <> old.joined_on
    or (old.left_on is not null and new.left_on is distinct from old.left_on) then
  raise exception 'membership episodes keep their participant, organization and dates; open a new episode instead'
   using errcode='42501';
 end if;
 return new;
end $$;
create trigger memberships_keep_identity before update on org.memberships
 for each row execute function org.reject_membership_rewrite();
-- The latest consent row per participant is the one in force; its episode must still be open.
create view org.current_consent with (security_invoker=true) as
 select distinct on (c.participant_id) c.participant_id,c.org_id,c.membership_id,c.consent_version,c.sharing,
  c.demonstration,c.recorded_at,c.withdrawn,m.left_on is null as membership_open
 from org.consents c join org.memberships m using (membership_id,participant_id,org_id)
 order by c.participant_id,c.recorded_at desc,c.consent_id desc;
do $$ declare t record; begin
 for t in select tablename from pg_tables where schemaname='org' loop
  execute format('alter table org.%I enable row level security',t.tablename);
  execute format('alter table org.%I force row level security',t.tablename);
  execute format('revoke all on org.%I from public,anon,authenticated,sentra_collector',t.tablename);
  execute format('create policy viewer_read on org.%I for select to sentra_viewer using (true)',t.tablename);
 end loop;
end $$;
revoke all on org.current_consent from public,anon,authenticated,sentra_collector;
revoke all on function org.reject_consent_change(),org.reject_membership_rewrite() from public,anon,authenticated;
grant usage on schema org to sentra_viewer;
grant select on org.organizations,org.org_users,org.memberships,org.consents,org.current_consent to sentra_viewer;
commit;
