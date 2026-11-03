-- Compact dense series (docs/storage-plan.md phases 1-2). Additive only: nothing here deletes or
-- changes audit.measurements. One row holds every measurement of one metric from one original
-- response; per-reading fields are parallel arrays, shared fields are stored once. The
-- audit.series_rows view re-expands rows column-for-column like audit.measurements, which is how
-- the lossless check compares them. Removing per-field rows is a separate, gated migration.
begin;
create table audit.series (
 series_id bigint generated always as identity primary key,
 participant_id text not null, provider text not null, dataset text not null, metric text not null,
 source_response_id text not null,
 unit text, vendor_unit text, value_kind text not null, availability text not null,
 timestamp_basis text not null, resolution_seconds numeric, resolution_description text not null,
 record_keys text[] not null, vals numeric[] not null, vendor_values jsonb[] not null,
 measured_at timestamptz[] not null, interval_start timestamptz[] not null, interval_end timestamptz[] not null,
 civil_dates jsonb[] not null, vendor_times jsonb[] not null, collected_at timestamptz[] not null,
 source_pointers text[] not null,
 check (cardinality(record_keys) > 0
   and cardinality(vals) = cardinality(record_keys) and cardinality(vendor_values) = cardinality(record_keys)
   and cardinality(measured_at) = cardinality(record_keys) and cardinality(interval_start) = cardinality(record_keys)
   and cardinality(interval_end) = cardinality(record_keys) and cardinality(civil_dates) = cardinality(record_keys)
   and cardinality(vendor_times) = cardinality(record_keys) and cardinality(collected_at) = cardinality(record_keys)
   and cardinality(source_pointers) = cardinality(record_keys)),
 foreign key (source_response_id,participant_id,provider,dataset)
 references audit.raw_response_manifest(response_id,participant_id,provider,dataset)
);
create index series_response on audit.series(participant_id,provider,dataset,source_response_id);

create view audit.series_rows with (security_invoker = true) as
select s.participant_id, s.provider, s.dataset, u.record_key, s.metric, u.value, s.unit, u.vendor_value,
       s.vendor_unit, s.value_kind, s.availability, u.measured_at, u.interval_start, u.interval_end, u.civil_date,
       s.timestamp_basis, u.vendor_time, u.collected_at, s.resolution_seconds, s.resolution_description,
       s.source_response_id, u.source_pointer
from audit.series s
cross join lateral unnest(s.record_keys, s.vals, s.vendor_values, s.measured_at, s.interval_start, s.interval_end,
                          s.civil_dates, s.vendor_times, s.collected_at, s.source_pointers)
  as u(record_key, value, vendor_value, measured_at, interval_start, interval_end, civil_date, vendor_time,
       collected_at, source_pointer);

alter table audit.series enable row level security;
alter table audit.series force row level security;
revoke all on audit.series, audit.series_rows from public, anon, authenticated;
grant select, insert, update, delete on audit.series to sentra_collector;
grant select on audit.series, audit.series_rows to sentra_collector, sentra_viewer;
create policy collector_access on audit.series to sentra_collector using (true) with check (true);
create policy viewer_read on audit.series for select to sentra_viewer using (true);
commit;
