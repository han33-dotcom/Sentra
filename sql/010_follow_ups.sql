-- Follow-up tracking (#31): brief wellness observations, an assigned reviewer and open/ongoing/resolved
-- history. Apply after 007, as postgres. The password of the new role is set privately by the operator.
-- Writes go only through the two functions below, run by a separate role; sentra_viewer stays read-only.
-- No diagnoses, contact details or readings belong in notes; the viewer shows wellness guidance.
begin;
create role sentra_followups login nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
-- One follow-up is about one organization, and optionally one participant who shares individual details.
create table org.follow_ups (
 follow_up_id bigint generated always as identity primary key,
 org_id text not null references org.organizations,
 participant_id text references audit.participants,
 opened_by text not null check (opened_by = lower(opened_by) and opened_by ~ '^[^@\s]+@[^@\s]+$'),
 opened_at timestamptz not null default now()
);
-- Append-only history: every status change, reassignment or note is a new event.
create table org.follow_up_events (
 event_id bigint generated always as identity primary key,
 follow_up_id bigint not null references org.follow_ups,
 recorded_at timestamptz not null default now(),
 actor text not null check (actor = lower(actor) and actor ~ '^[^@\s]+@[^@\s]+$'),
 status text not null check (status in ('open','ongoing','resolved')),
 assignee text not null check (assignee = lower(assignee) and assignee ~ '^[^@\s]+@[^@\s]+$'),
 note text not null check (length(btrim(note)) between 1 and 500)
);
create index follow_up_events_latest on org.follow_up_events(follow_up_id,recorded_at desc,event_id desc);
create function org.reject_follow_up_change() returns trigger
language plpgsql set search_path='' as $$
begin
 raise exception 'follow-up history is append-only; record a new event instead' using errcode='42501';
end $$;
create trigger follow_ups_append_only before update or delete on org.follow_ups
 for each row execute function org.reject_follow_up_change();
create trigger follow_ups_no_truncate before truncate on org.follow_ups
 for each statement execute function org.reject_follow_up_change();
create trigger follow_up_events_append_only before update or delete on org.follow_up_events
 for each row execute function org.reject_follow_up_change();
create trigger follow_up_events_no_truncate before truncate on org.follow_up_events
 for each statement execute function org.reject_follow_up_change();

-- Checks shared by both writes. The signed-in e-mail is verified by the viewer's Google sign-in and
-- passed in; the database re-checks every organization and consent rule from its own rows.
create function org.check_follow_up(actor text, org text, pid text, assignee text, note text) returns void
language plpgsql stable security definer set search_path='' as $$
begin
 if not exists (select 1 from org.org_users u where u.org_id=org and u.email=actor and u.active and u.role='officer') then
  raise exception 'Only an active officer of this organization can record follow-ups.' using errcode='42501';
 end if;
 if not exists (select 1 from org.org_users u where u.org_id=org and u.email=assignee and u.active) then
  raise exception 'The assignee must be an active officer or reviewer of this organization.' using errcode='42501';
 end if;
 if pid is not null and not exists (select 1 from org.current_consent c where c.participant_id=pid and c.org_id=org
     and not c.withdrawn and c.membership_open and c.sharing='individual') then
  raise exception 'This participant does not currently share individual details with this organization.'
   using errcode='42501';
 end if;
 if note is null or length(btrim(note)) not between 1 and 500 then
  raise exception 'A note of 1 to 500 characters is required.' using errcode='22023';
 end if;
end $$;

create function org.open_follow_up(actor text, org text, pid text, assignee text, note text) returns bigint
language plpgsql security definer set search_path='' as $$
declare fid bigint;
begin
 perform org.check_follow_up(actor, org, pid, assignee, note);
 insert into org.follow_ups(org_id, participant_id, opened_by) values (org, pid, actor) returning follow_up_id into fid;
 insert into org.follow_up_events(follow_up_id, actor, status, assignee, note) values (fid, actor, 'open', assignee, btrim(note));
 return fid;
end $$;

create function org.update_follow_up(actor text, fid bigint, new_status text, assignee text, note text) returns void
language plpgsql security definer set search_path='' as $$
declare f org.follow_ups;
begin
 select * into f from org.follow_ups where follow_up_id=fid for share;
 if not found then
  raise exception 'Follow-up not found.' using errcode='42501';
 end if;
 -- A withdrawn or downgraded consent also stops further notes about that person.
 perform org.check_follow_up(actor, f.org_id, f.participant_id, assignee, note);
 if new_status not in ('open','ongoing','resolved') then
  raise exception 'Status must be open, ongoing or resolved.' using errcode='22023';
 end if;
 insert into org.follow_up_events(follow_up_id, actor, status, assignee, note) values (fid, actor, new_status, assignee, btrim(note));
end $$;

do $$ declare t text; begin
 foreach t in array array['follow_ups','follow_up_events'] loop
  execute format('alter table org.%I enable row level security',t);
  execute format('alter table org.%I force row level security',t);
  execute format('revoke all on org.%I from public,anon,authenticated,sentra_collector,sentra_followups',t);
  execute format('create policy viewer_read on org.%I for select to sentra_viewer using (true)',t);
 end loop;
end $$;
revoke all on function org.reject_follow_up_change(),org.check_follow_up(text,text,text,text,text),
 org.open_follow_up(text,text,text,text,text),org.update_follow_up(text,bigint,text,text,text)
 from public,anon,authenticated,sentra_viewer,sentra_collector;
grant select on org.follow_ups,org.follow_up_events to sentra_viewer;
grant usage on schema org to sentra_followups;
grant execute on function org.open_follow_up(text,text,text,text,text),
 org.update_follow_up(text,bigint,text,text,text) to sentra_followups;
commit;
