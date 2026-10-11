-- Stage 5: read-only viewer gets only aggregate usage and safe observation fields.
begin;
create function public.sentra_viewer_status() returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 if session_user <> 'sentra_viewer' then raise exception 'access denied'; end if;
 return collector_private.usage() || jsonb_build_object(
  'budget_verified_at',(select verified_at from collector_private.egress_budget
    where month=date_trunc('month',now())::date),
  'observation',(select jsonb_build_object('enabled',settings->'enabled','start',settings->'start','end',settings->'end')
    from collector_private.observation_control where singleton));
end $$;
revoke all on function public.sentra_viewer_status() from public,anon,authenticated,sentra_collector;
grant execute on function public.sentra_viewer_status() to sentra_viewer;
-- The viewer cannot increase the pipeline's existing 3.5 GB safety ceiling.
create or replace function public.sentra_reserve_viewer_egress(amount bigint,ceiling bigint) returns void
language plpgsql security definer set search_path='' as $$
begin
 if session_user <> 'sentra_viewer' then raise exception 'access denied'; end if;
 if amount<0 or amount>100000000 or ceiling>3500000000 then raise exception 'invalid viewer budget'; end if;
 perform collector_private.reserve_egress(amount,ceiling);
end $$;
revoke all on function public.sentra_reserve_viewer_egress(bigint,bigint) from public,anon,authenticated,sentra_collector;
grant execute on function public.sentra_reserve_viewer_egress(bigint,bigint) to sentra_viewer;
commit;
