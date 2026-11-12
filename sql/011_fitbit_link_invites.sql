-- Keep these links separate so an older enrollment deploy cannot treat them as signup invitations.
begin;

-- Tag a hosted login for a legacy Fitbit without changing the backup row shape.
-- The same Google subject can appear only once, regardless of the tag.
alter table enrollment_private.identities drop constraint identities_identity_hash_check,
 add constraint identities_identity_hash_check check (
  identity_hash ~ '^[a-f0-9]{64}$'
  or (provider = 'google_health' and identity_hash ~ '^fitbit-link:[a-f0-9]{64}$')
 );
create unique index identities_google_subject on enrollment_private.identities (right(identity_hash,64))
 where provider = 'google_health';

-- Protect the credential even if enrollment rolls back to code that predates this flag.
-- Withdrawal updates status without touching the bundle. The operator and collector can
-- still perform their authorized reconnect and refresh operations.
create function enrollment_private.guard_operator_managed_credential() returns trigger
language plpgsql set search_path='' as $$
begin
 if current_user <> 'sentra_enrollment' or new.provider <> 'google_health' then
  return new;
 end if;
 if exists (
  select 1 from enrollment_private.identities i
  where i.participant_id = new.participant_id and i.provider = new.provider
    and starts_with(i.identity_hash, 'fitbit-link:')
 ) then
  raise exception 'This Fitbit credential is managed by the operator.' using errcode = '42501';
 end if;
 return new;
end
$$;
revoke all on function enrollment_private.guard_operator_managed_credential()
 from public,anon,authenticated,sentra_viewer,sentra_collector;
create trigger guard_operator_managed_credential
 before insert or update of encrypted_token_bundle on collector_private.provider_credentials
 for each row execute function enrollment_private.guard_operator_managed_credential();

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
