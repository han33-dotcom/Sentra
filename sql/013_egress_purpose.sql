-- Apply after 005. Add attribution; retain all existing reservations and budget checks.
begin;
create table collector_private.egress_purposes (
 month date not null, purpose text not null,
 reserved_bytes bigint not null check(reserved_bytes >= 0),
 primary key(month,purpose)
);
alter table collector_private.egress_purposes enable row level security;
alter table collector_private.egress_purposes force row level security;
revoke all on collector_private.egress_purposes from public,anon,authenticated,sentra_viewer,sentra_collector;
-- Earlier reservations cannot be attributed retrospectively. The baseline is separate.
insert into collector_private.egress_purposes
 select month,'prior_unattributed',reserved_bytes from collector_private.egress_budget;

create function collector_private.reserve_egress(amount bigint, ceiling bigint, purpose text) returns void
language plpgsql security definer set search_path='' as $$
begin
 if amount is null or ceiling is null or amount < 0 or ceiling <= 0 or ceiling >= 5000000000
 then raise exception 'invalid budget'; end if;
 if purpose is null or purpose not in ('collector','viewer','tiers','backup','verify','processing','enrollment','followups','operations')
 then raise exception 'invalid egress purpose'; end if;
 update collector_private.egress_budget set reserved_bytes=reserved_bytes+amount
 where month=date_trunc('month',now())::date and verified_at > now()-interval '7 days'
 and baseline_bytes+reserved_bytes+amount < ceiling;
 if not found then raise exception 'capacity_stop: egress baseline missing, stale or exhausted'; end if;
 insert into collector_private.egress_purposes values(date_trunc('month',now())::date,purpose,amount)
 on conflict on constraint egress_purposes_pkey do update
 set reserved_bytes=collector_private.egress_purposes.reserved_bytes+excluded.reserved_bytes;
end $$;
revoke all on function collector_private.reserve_egress(bigint,bigint,text) from public,anon,authenticated,sentra_viewer;
grant execute on function collector_private.reserve_egress(bigint,bigint,text) to sentra_collector;

-- Existing clients and SQL enrollment/follow-up functions retain their exact signatures.
create or replace function collector_private.reserve_egress(amount bigint, ceiling bigint) returns void
language sql security definer set search_path='' as $$
 select collector_private.reserve_egress(amount,ceiling,case session_user
  when 'sentra_collector' then 'collector' when 'sentra_viewer' then 'viewer'
  when 'sentra_enrollment' then 'enrollment' when 'sentra_followups' then 'followups'
  else 'operations' end)
$$;
create function public.sentra_reserve_viewer_egress(amount bigint,ceiling bigint,purpose text) returns void
language plpgsql security definer set search_path='' as $$
begin
 if session_user <> 'sentra_viewer' then raise exception 'access denied'; end if;
 if amount is null or ceiling is null or amount<0 or amount>100000000 or ceiling>3500000000
 then raise exception 'invalid viewer budget'; end if;
 if purpose is null or purpose not in ('viewer','tiers','processing') then raise exception 'invalid viewer purpose'; end if;
 perform collector_private.reserve_egress(amount,ceiling,purpose);
end $$;
revoke all on function public.sentra_reserve_viewer_egress(bigint,bigint,text) from public,anon,authenticated,sentra_collector;
grant execute on function public.sentra_reserve_viewer_egress(bigint,bigint,text) to sentra_viewer;
create or replace function public.sentra_reserve_viewer_egress(amount bigint,ceiling bigint) returns void
language sql security definer set search_path='' as $$
 select public.sentra_reserve_viewer_egress(amount,ceiling,'viewer')
$$;

create or replace function collector_private.usage() returns jsonb
language sql security definer set search_path='' as $$
 select jsonb_build_object('database_bytes',pg_database_size(current_database()),
  'object_bytes',coalesce((select sum((metadata->>'size')::bigint) from storage.objects),0),
  'audit_bytes',coalesce((select sum(pg_total_relation_size(format('audit.%I',tablename)::regclass))
    from pg_tables where schemaname='audit'),0),
  'egress_bytes',(select baseline_bytes+reserved_bytes from collector_private.egress_budget
    where month=date_trunc('month',now())::date),
  'egress_reserved_by_purpose',coalesce((select jsonb_object_agg(purpose,reserved_bytes)
    from collector_private.egress_purposes where month=date_trunc('month',now())::date),'{}'::jsonb))
$$;
commit;
