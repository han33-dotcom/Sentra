-- Apply after 013. Owner approved 4.5 GB on November 18, 2026 for backup headroom.
-- Keep every baseline/reservation, purpose restriction, freshness check and call cap.
begin;
create or replace function public.sentra_reserve_viewer_egress(amount bigint,ceiling bigint,purpose text) returns void
language plpgsql security definer set search_path='' as $$
begin
 if session_user <> 'sentra_viewer' then raise exception 'access denied'; end if;
 if amount is null or ceiling is null or amount<0 or amount>100000000 or ceiling>4500000000
 then raise exception 'invalid viewer budget'; end if;
 if purpose is null or purpose not in ('viewer','tiers','processing') then raise exception 'invalid viewer purpose'; end if;
 perform collector_private.reserve_egress(amount,ceiling,purpose);
end $$;
commit;
