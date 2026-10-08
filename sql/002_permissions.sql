-- Bootstrap sets passwords separately with bound values; never commit passwords.
begin;
create role sentra_collector login nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
create role sentra_viewer login nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
grant usage on schema audit to sentra_collector,sentra_viewer;
grant usage on schema collector_private to sentra_collector;
grant select,insert,update,delete on all tables in schema audit to sentra_collector;
grant select on all tables in schema audit to sentra_viewer;
grant select,insert,update on collector_private.provider_credentials to sentra_collector;
do $$ declare t record; begin
 for t in select tablename from pg_tables where schemaname='audit' loop
  execute format('alter table audit.%I enable row level security',t.tablename);
  execute format('alter table audit.%I force row level security',t.tablename);
  execute format('revoke all on audit.%I from public,anon,authenticated',t.tablename);
  execute format('create policy collector_access on audit.%I to sentra_collector using (true) with check (true)',t.tablename);
  execute format('create policy viewer_read on audit.%I for select to sentra_viewer using (true)',t.tablename);
 end loop;
end $$;
alter table collector_private.provider_credentials enable row level security;
alter table collector_private.provider_credentials force row level security;
create policy credential_collector on collector_private.provider_credentials to sentra_collector using (true) with check (true);
revoke all on all tables in schema collector_private from public,anon,authenticated,sentra_viewer;
create function public.sentra_storage_access(kind text) returns boolean
language sql stable security definer set search_path='' as $$
 select exists(select 1 from collector_private.storage_members m
  where m.user_id=auth.uid() and (m.access_kind='collector' or (kind='read' and m.access_kind='viewer')))
$$;
revoke all on function public.sentra_storage_access(text) from public;
grant execute on function public.sentra_storage_access(text) to authenticated;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('sentra-originals','sentra-originals',false,16777216,array['application/gzip']);
create policy sentra_raw_read on storage.objects for select to authenticated
 using (bucket_id='sentra-originals' and public.sentra_storage_access('read'));
create policy sentra_raw_insert on storage.objects for insert to authenticated
 with check (bucket_id='sentra-originals' and public.sentra_storage_access('write'));
-- No runtime UPDATE/DELETE policies: hash-keyed originals are immutable.
create function collector_private.usage() returns jsonb
language sql security definer set search_path='' as $$
 select jsonb_build_object('database_bytes',pg_database_size(current_database()),
  'object_bytes',coalesce((select sum((metadata->>'size')::bigint) from storage.objects),0),
  'audit_bytes',coalesce((select sum(pg_total_relation_size(format('audit.%I',tablename)::regclass))
    from pg_tables where schemaname='audit'),0),
  'egress_bytes',(select baseline_bytes+reserved_bytes from collector_private.egress_budget
    where month=date_trunc('month',now())::date))
$$;
revoke all on function collector_private.usage() from public,anon,authenticated;
grant execute on function collector_private.usage() to sentra_collector;
create function collector_private.reserve_egress(amount bigint, ceiling bigint) returns void
language plpgsql security definer set search_path='' as $$
begin
 if amount < 0 or ceiling <= 0 or ceiling >= 5000000000 then raise exception 'invalid budget'; end if;
 update collector_private.egress_budget set reserved_bytes=reserved_bytes+amount
 where month=date_trunc('month',now())::date and verified_at > now()-interval '7 days'
 and baseline_bytes+reserved_bytes+amount < ceiling;
 if not found then raise exception 'capacity_stop: egress baseline missing, stale or exhausted'; end if;
end $$;
revoke all on function collector_private.reserve_egress(bigint,bigint) from public,anon,authenticated;
grant execute on function collector_private.reserve_egress(bigint,bigint) to sentra_collector;
-- Viewer may reserve download allowance, but cannot modify health rows or read credentials.
create function public.sentra_reserve_viewer_egress(amount bigint,ceiling bigint) returns void
language plpgsql security definer set search_path='' as $$
begin
 if session_user <> 'sentra_viewer' then raise exception 'access denied'; end if;
 perform collector_private.reserve_egress(amount,ceiling);
end $$;
revoke all on function public.sentra_reserve_viewer_egress(bigint,bigint) from public,anon,authenticated;
grant execute on function public.sentra_reserve_viewer_egress(bigint,bigint) to sentra_viewer;
commit;
