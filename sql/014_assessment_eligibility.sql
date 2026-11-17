-- Apply after 008. Only bounded eligibility metadata, never readings or assessment values.
begin;
create table collector_private.assessment_publication (
 singleton boolean primary key default true check(singleton),
 published_at timestamptz not null, version text not null, digest text not null
);
create table collector_private.assessment_eligibility (
 participant_id text primary key references audit.participants,
 day date, assessable boolean
);
alter table collector_private.assessment_publication enable row level security;
alter table collector_private.assessment_publication force row level security;
alter table collector_private.assessment_eligibility enable row level security;
alter table collector_private.assessment_eligibility force row level security;
revoke all on collector_private.assessment_publication,collector_private.assessment_eligibility
 from public,anon,authenticated,sentra_viewer,sentra_collector,sentra_enrollment;

create function collector_private.publish_assessment_eligibility(
 published timestamptz, publication_version text, publication_digest text, publication_rows jsonb) returns void
language plpgsql security definer set search_path='' as $$
begin
 if published is null or published > now()+interval '5 minutes' or publication_version is null
   or length(publication_version) not between 1 and 100 or publication_digest is null or publication_digest !~ '^[a-f0-9]{64}$'
   or jsonb_typeof(publication_rows) is distinct from 'array' or jsonb_array_length(publication_rows)>100
 then raise exception 'invalid eligibility publication'; end if;
 perform pg_advisory_xact_lock(735014);
 if exists(select 1 from collector_private.assessment_publication p where p.published_at>published
   or (p.published_at=published and p.digest<>publication_digest))
 then raise exception 'eligibility publication is older or conflicts'; end if;
 -- Replace the entire bounded snapshot so omitted participants cannot retain stale eligibility.
 delete from collector_private.assessment_eligibility;
 insert into collector_private.assessment_eligibility
 select participant_id,day,assessable from jsonb_to_recordset(publication_rows)
 as x(participant_id text,day date,assessable boolean);
 insert into collector_private.assessment_publication values(true,published,publication_version,publication_digest)
 on conflict(singleton) do update set published_at=excluded.published_at,
 version=excluded.version,digest=excluded.digest;
end $$;
revoke all on function collector_private.publish_assessment_eligibility(timestamptz,text,text,jsonb)
 from public,anon,authenticated,sentra_viewer,sentra_enrollment;
grant execute on function collector_private.publish_assessment_eligibility(timestamptz,text,text,jsonb)
 to sentra_collector;

create function enrollment_private.assessment_eligibility(pid text,expected_version text) returns jsonb
language sql stable security definer set search_path='' as $$
 select coalesce((select jsonb_build_object(
  'assessment',case when p.version<>expected_version or p.published_at<now()-interval '3 days'
    or p.published_at>now()+interval '5 minutes' or e.day is null
    or e.day>(now() at time zone 'Asia/Beirut')::date
    or e.day<(now() at time zone 'Asia/Beirut')::date-3 or e.assessable is null
    then 'not_available' when e.assessable then 'available' else 'insufficient' end,
  'assessable',case when p.version=expected_version and p.published_at>=now()-interval '3 days'
    and p.published_at<=now()+interval '5 minutes'
    and e.day between (now() at time zone 'Asia/Beirut')::date-3 and (now() at time zone 'Asia/Beirut')::date
    then e.assessable else null end,
  'assessment_day',e.day,'assessment_published_at',p.published_at)
  from collector_private.assessment_publication p
  join collector_private.assessment_eligibility e on e.participant_id=pid where p.singleton),
  '{"assessment":"not_available","assessable":null}'::jsonb)
$$;
revoke all on function enrollment_private.assessment_eligibility(text,text)
 from public,anon,authenticated,sentra_viewer,sentra_collector;
grant execute on function enrollment_private.assessment_eligibility(text,text) to sentra_enrollment;
commit;
