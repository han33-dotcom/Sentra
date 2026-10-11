-- Repair searchable projections from the preserved normalized JSON. PostgreSQL's
-- implicit float8-to-numeric cast rounds to fewer digits than JSON number text.
-- New inserts use Decimal(str(value)); no response, record or source hash changes.
begin;
with expected as materialized (
  select participant_id,provider,dataset,record_key,metric->>'metric' metric,
         (metric->>'value')::numeric value,
         (case when metric ? 'resolution_seconds' then metric->>'resolution_seconds'
               else r.record->>'resolution_seconds' end)::numeric resolution_seconds
  from audit.records r cross join lateral jsonb_array_elements(r.record->'measurements') metric
)
update audit.measurements m set value=e.value,resolution_seconds=e.resolution_seconds
from expected e
where (m.participant_id,m.provider,m.dataset,m.record_key,m.metric)=
      (e.participant_id,e.provider,e.dataset,e.record_key,e.metric)
  and (m.value,m.resolution_seconds) is distinct from (e.value,e.resolution_seconds);
commit;
