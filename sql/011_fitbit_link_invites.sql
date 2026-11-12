-- Keep these links separate so an older enrollment deploy cannot treat them as signup invitations.
begin;
create table enrollment_private.fitbit_link_invites (
 invite_hash text primary key check (invite_hash ~ '^[a-f0-9]{64}$'),
 org_id text not null references org.organizations,
 participant_id text not null references audit.participants,
 email_hash text not null check (email_hash ~ '^[a-f0-9]{64}$'),
 expires_at timestamptz not null
);
alter table enrollment_private.fitbit_link_invites enable row level security;
alter table enrollment_private.fitbit_link_invites force row level security;
revoke all on enrollment_private.fitbit_link_invites
 from public,anon,authenticated,sentra_viewer,sentra_collector;
grant select,insert,delete on enrollment_private.fitbit_link_invites to sentra_enrollment;
create policy enrollment_access on enrollment_private.fitbit_link_invites
 to sentra_enrollment using (true) with check (true);
commit;
