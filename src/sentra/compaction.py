"""Lossless compaction of dense measurement rows into audit.series (docs/storage-plan.md phases 1-2).

Never deletes audit.measurements. Each run compacts a bounded batch of original responses inside one
transaction, re-expands them through audit.series_rows and compares row counts and an exact
per-row fingerprint (JSON text, so numeric scale, jsonb and timestamps must match) with the source
rows. Any difference rolls the batch back. audit.series is derived data and can be rebuilt.
"""
from .errors import SentraError

DENSE_PREFIXES = ('minute_',)
DENSE = ('original_heart-rate', 'activity-level')
SHARED = ('unit', 'vendor_unit', 'value_kind', 'availability', 'timestamp_basis', 'resolution_description')
PER_READING = ('record_key', 'value', 'vendor_value', 'measured_at', 'interval_start', 'interval_end',
               'civil_date', 'vendor_time', 'collected_at', 'source_pointer')
ARRAYS = ('record_keys', 'vals', 'vendor_values', 'measured_at', 'interval_start', 'interval_end',
          'civil_dates', 'vendor_times', 'collected_at', 'source_pointers')
SCOPE = 'participant_id=%s and provider=%s and dataset=%s'
# Sum of 64-bit row hashes; text rendering keeps numeric scale, so 60 and 60.0 differ.
FINGERPRINT = "sum(('x'||left(md5(row_to_json(t)::text),16))::bit(64)::bigint::numeric)"


def is_dense(dataset):
    return dataset in DENSE or dataset.startswith(DENSE_PREFIXES)


def _scope(participant, provider, dataset):
    if not is_dense(dataset):
        raise SentraError('Only dense series datasets are compacted; sparse data stays as it is.')
    return participant, provider, dataset


def pending(db, participant, provider, dataset, *, limit):
    """Original responses with measurement rows but no series yet, oldest first."""
    return [r[0] for r in db.execute(f'''select m.source_response_id from audit.measurements m
        where m.{SCOPE.replace(' and ', ' and m.')} and not exists (select 1 from audit.series s
          where s.participant_id=m.participant_id and s.provider=m.provider and s.dataset=m.dataset
            and s.source_response_id=m.source_response_id)
        group by m.source_response_id order by min(m.collected_at), m.source_response_id limit %s''',
        (*_scope(participant, provider, dataset), limit)).fetchall()]


def build(db, participant, provider, dataset, responses):
    """(Re)build the series of the given responses from their current measurement rows."""
    scope = _scope(participant, provider, dataset)
    db.execute(f'delete from audit.series where {SCOPE} and source_response_id = any(%s)', (*scope, responses))
    order = 'order by record_key'
    aggregates = ', '.join(f'array_agg({c} {order})' for c in PER_READING)
    # Group on the text of resolution_seconds so 60 and 60.0 stay distinct; every member shares it.
    db.execute(f'''insert into audit.series (participant_id, provider, dataset, metric, source_response_id,
          {', '.join(SHARED)}, resolution_seconds, {', '.join(ARRAYS)})
        select participant_id, provider, dataset, metric, source_response_id, {', '.join(SHARED)},
          (array_agg(resolution_seconds))[1], {aggregates}
        from audit.measurements where {SCOPE} and source_response_id = any(%s)
        group by participant_id, provider, dataset, metric, source_response_id, {', '.join(SHARED)},
          resolution_seconds::text''', (*scope, responses))


def verify(db, participant, provider, dataset, responses=None):
    """Compare every compacted response (or the given ones) with its measurement rows."""
    scope = _scope(participant, provider, dataset)
    only = ' and source_response_id = any(%s)' if responses is not None else ''
    params = (*scope, responses) if responses is not None else scope
    rows = db.execute(f'''with m as (select source_response_id, count(*) n, {FINGERPRINT} h
            from audit.measurements t where {SCOPE}{only} group by 1),
          s as (select source_response_id, count(*) n, {FINGERPRINT} h
            from audit.series_rows t where {SCOPE}{only} group by 1)
        select count(*) filter (where s.n is not null and m.n = s.n and m.h = s.h),
               count(*) filter (where s.n is not null and (m.n is distinct from s.n or m.h is distinct from s.h)),
               count(*) filter (where s.n is null),
               coalesce(sum(s.n) filter (where m.n = s.n and m.h = s.h), 0)
        from m full join s using (source_response_id)''', (*params, *params)).fetchone()
    return {'verified_responses': rows[0], 'mismatched_responses': rows[1], 'pending_responses': rows[2],
            'verified_rows': int(rows[3])}


def sizes(db, participant, provider, dataset):
    """Measured bytes: compacted series rows versus the measurement rows they cover (heap only)."""
    scope = _scope(participant, provider, dataset)
    original = db.execute(f'''select count(*), coalesce(sum(pg_column_size(m.*)), 0) from audit.measurements m
        where {SCOPE.replace('participant_id', 'm.participant_id')} and exists (select 1 from audit.series s
          where s.participant_id=m.participant_id and s.provider=m.provider and s.dataset=m.dataset
            and s.source_response_id=m.source_response_id)''', scope).fetchone()
    compact = db.execute(f'select count(*), coalesce(sum(pg_column_size(s.*)), 0) from audit.series s where {SCOPE}',
                         scope).fetchone()
    return {'measurement_rows': original[0], 'measurement_row_bytes': int(original[1]),
            'series_rows': compact[0], 'series_row_bytes': int(compact[1]),
            'ratio': round(original[1] / compact[1], 1) if compact[1] else None,
            'meaning': 'pg_column_size of row data only; indexes and tuple headers excluded on both sides'}


def compact(db, guard, participant, provider, dataset, *, limit=200):
    """Compact up to `limit` pending responses in one transaction; rolled back unless every one verifies."""
    with db.transaction():
        responses = pending(db, participant, provider, dataset, limit=limit)
        if not responses:
            return {'compacted_responses': 0, **verify(db, participant, provider, dataset)}
        bytes_in = db.execute(f'''select coalesce(sum(pg_column_size(m.*)), 0) from audit.measurements m
            where {SCOPE} and source_response_id = any(%s)''', (participant, provider, dataset, responses)).fetchone()[0]
        guard(database_add=int(bytes_in) + 1_000_000)  # worst case: no saving at all
        build(db, participant, provider, dataset, responses)
        result = verify(db, participant, provider, dataset, responses)
        if result['mismatched_responses'] or result['verified_responses'] != len(responses):
            raise SentraError('Compacted series differ from measurement rows; batch rolled back, nothing kept.')
    overall = verify(db, participant, provider, dataset)
    return {'compacted_responses': len(responses), 'batch_verified_rows': result['verified_rows'], **overall}
