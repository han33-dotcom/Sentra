-- SEN-165. An operator registers only the hosted deployment's proof digest.
-- Installing the schema alone grants no additional budget.
begin;
create table collector_private.november_viewer_grant (
 singleton boolean primary key default true check (singleton),
 proof_digest bytea not null check (octet_length(proof_digest) = 32),
 spent_bytes bigint not null default 0 check (spent_bytes between 0 and 50000000)
);
alter table collector_private.november_viewer_grant enable row level security;
alter table collector_private.november_viewer_grant force row level security;
revoke all on collector_private.november_viewer_grant from public, anon, authenticated, sentra_collector, sentra_viewer;

create function public.sentra_reserve_november_hosted_viewer(amount bigint, ceiling bigint, proof text)
returns void language plpgsql security definer set search_path='' set timezone='UTC' as $$
begin
 if session_user <> 'sentra_viewer' or ceiling is distinct from 4500000000
    or amount is null or amount not between 0 and 50000000 then
   raise exception 'invalid hosted viewer reservation';
 end if;
 -- Lock the grant before checking time. Every subsequent check and both ledger
 -- writes share this transaction; an unsuccessful reservation spends nothing.
 perform 1 from collector_private.november_viewer_grant
 where singleton and proof_digest=sha256(convert_to(proof,'UTF8')) for update;
 if not found or clock_timestamp() < timestamptz '2026-11-01 00:00:00+00'
              or clock_timestamp() >= timestamptz '2026-12-01 00:00:00+00' then
   raise exception 'hosted viewer grant unavailable';
 end if;
 update collector_private.november_viewer_grant set spent_bytes=spent_bytes+amount
 where singleton and spent_bytes+amount <= 50000000;
 if not found then raise exception 'hosted viewer grant exhausted'; end if;
 perform collector_private.reserve_egress(amount,4550000000,'viewer');
 -- The monthly ledger may have been locked by another reservation.
 if clock_timestamp() >= timestamptz '2026-12-01 00:00:00+00' then
   raise exception 'hosted viewer grant expired';
 end if;
end $$;
revoke all on function public.sentra_reserve_november_hosted_viewer(bigint,bigint,text) from public,anon,authenticated,sentra_collector;
grant execute on function public.sentra_reserve_november_hosted_viewer(bigint,bigint,text) to sentra_viewer;
commit;
