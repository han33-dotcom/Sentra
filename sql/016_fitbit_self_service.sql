-- Apply after 011. Preserve the legacy credential guard until the participant
-- explicitly reconnects with the same verified Google subject in the web service.
begin;
create function enrollment_private.enable_fitbit_self_service(pid text, subject_hash text)
returns void language plpgsql security definer set search_path='' as $$
begin
 if subject_hash is null or subject_hash !~ '^[a-f0-9]{64}$' then
  raise exception 'Invalid linked identity.' using errcode='42501';
 end if;
 perform 1 from enrollment_private.identities i
  where i.participant_id=pid and i.provider='google_health'
    and i.identity_hash='fitbit-link:' || subject_hash for update;
 if not found then
  raise exception 'Linked identity changed.' using errcode='42501';
 end if;
 if not exists (select 1 from org.current_consent c where c.participant_id=pid
                and c.membership_open and not c.withdrawn)
    or not exists (select 1 from collector_private.provider_credentials c
                   where c.participant_id=pid and c.provider='google_health') then
  raise exception 'Participation is unavailable.' using errcode='42501';
 end if;
 update enrollment_private.identities set identity_hash=subject_hash
  where participant_id=pid and provider='google_health'
    and identity_hash='fitbit-link:' || subject_hash;
end
$$;
revoke all on function enrollment_private.enable_fitbit_self_service(text,text)
 from public,anon,authenticated,sentra_viewer,sentra_collector;
grant execute on function enrollment_private.enable_fitbit_self_service(text,text) to sentra_enrollment;
commit;
