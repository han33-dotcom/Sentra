"""Bounded read-only audit/Storage access; every entry rechecks team authorization."""
from functools import wraps
import re

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from .errors import SentraError
from .shared import CapacityStop, object_key
from .shared_backend import BUCKET, PrivateStorage, connect_db
from .viewer_data import MAX_BYTES, MAX_ROWS, Selection


def safe_database(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except psycopg.Error:
            raise SentraError('Viewer database request unavailable. Check project pause and viewer configuration; sensitive details omitted.') from None
    return wrapped


# Civil vendor dates remain civil: compare ISO day text, never invent a UTC instant.
CIVIL = """case when coalesce(m.civil_date->>'year',m.civil_date#>>'{date,year}') ~ '^[0-9]{4}$'
 and coalesce(m.civil_date->>'month',m.civil_date#>>'{date,month}') ~ '^[0-9]{1,2}$'
 and coalesce(m.civil_date->>'day',m.civil_date#>>'{date,day}') ~ '^[0-9]{1,2}$'
 then coalesce(m.civil_date->>'year',m.civil_date#>>'{date,year}') || '-' ||
 lpad(coalesce(m.civil_date->>'month',m.civil_date#>>'{date,month}'),2,'0') || '-' ||
 lpad(coalesce(m.civil_date->>'day',m.civil_date#>>'{date,day}'),2,'0')
 when jsonb_typeof(m.civil_date)='string' and (m.civil_date#>>'{}') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
 then left(m.civil_date#>>'{}',10) end"""


def selection_where(selection):
    f = selection
    where = f"""m.participant_id=%s and m.provider=%s and m.dataset=%s and (
      (m.measured_at >= %s and m.measured_at < %s) or
      (m.measured_at is null and m.interval_start < %s and
       (m.interval_end > %s or (m.interval_end is null and m.interval_start >= %s)
         or (m.interval_end=m.interval_start and m.interval_start >= %s))) or
      (m.measured_at is null and m.interval_start is null and ({CIVIL}) >= %s and ({CIVIL}) < %s))"""
    values = [f.participant,f.provider,f.dataset,f.start_utc,f.end_utc,f.end_utc,
              f.start_utc,f.start_utc,f.start_utc,f.start.isoformat(),f.end.isoformat()]
    if f.metric:
        where += ' and m.metric=%s'
        values.append(f.metric)
    if f.search:
        where += " and (m.metric || ' ' || coalesce(m.vendor_value::text,'') || ' ' || coalesce(m.unit,'') || ' ' || m.availability) ilike %s escape E'\\\\'"
        values.append('%'+f.search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    return where,values


def check_result_size(count, size):
    if count>MAX_ROWS or size>MAX_BYTES:
        raise SentraError('Narrow the metric or date filters. Selection exceeds 10,000 rows or 20 MB; no partial result returned.')


class ViewerReader:
    def __init__(self, credentials, limits, principal, *, db=None, budget_db=None):
        self.credentials,self.limits,self.principal = credentials,limits,principal
        if db is None:
            principal()
        self.db = db if db is not None else connect_db(credentials)
        self.budget_db = budget_db
        self.storage = PrivateStorage(credentials,self.reserve)

    def close(self):
        self.db.close()
        if self.budget_db is not None and self.budget_db is not self.db:
            self.budget_db.close()
        self.storage.session.close()

    def reserve(self, amount):
        self.principal()
        try:
            # Persist allowance independently of read snapshots: a failed transfer
            # must not roll back the reservation for bytes already received.
            if self.budget_db is None:
                self.budget_db = connect_db(self.credentials)
            self.budget_db.execute('select public.sentra_reserve_viewer_egress(%s,%s)',(amount,self.limits.monthly_egress_bytes))
        except psycopg.Error:
            raise CapacityStop('Viewer egress allowance is unavailable, stale or exhausted. Ask the operator to verify usage and refresh the baseline.') from None

    def _rows(self, query, values=(), *, allowance=262_144):
        self.principal()
        self.reserve(allowance)
        with self.db.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query,values)
            return cursor.fetchall()

    @safe_database
    def catalog(self):
        return self._rows('''select s.participant_id,s.provider,s.dataset,s.authorization_status,
          s.last_success_at,count(m.metric) measurement_rows,
          max(m.measured_at) latest_point_time,max(m.interval_end) latest_interval_end
          from audit.connection_state s left join audit.measurements m
          using(participant_id,provider,dataset) group by 1,2,3,4,5 order by 1,2,3''')

    @safe_database
    def metrics(self, selection):
        self.principal()
        # Discover metric names for the dataset; at most 2,000 scalar definitions.
        rows=self._rows('''select distinct metric,unit,value_kind from audit.measurements
           where participant_id=%s and provider=%s and dataset=%s order by 1,2,3 limit 2001''',
           (selection.participant,selection.provider,selection.dataset),allowance=2_000_000)
        if len(rows)>2000:
            raise SentraError('Dataset has too many metric definitions; ask the operator to review its field inventory.')
        return rows

    @safe_database
    def usage(self):
        self.principal()
        self.reserve(32_768)
        result=self.db.execute('select public.sentra_viewer_status()').fetchone()[0]
        if any(type(result.get(k)) is not int or result[k]<0 for k in ('database_bytes','object_bytes','egress_bytes')):
            raise CapacityStop('Storage usage unavailable. Ask the operator to verify project/organization usage.')
        return result

    @safe_database
    def measurements(self, selection):
        self.principal()
        where,values=selection_where(selection)
        self.reserve(65_536)
        # A single snapshot ensures the size check and retrieval cover the same rows.
        new_snapshot = self.db.info.transaction_status == TransactionStatus.IDLE
        with self.db.transaction():
            if new_snapshot:
                self.db.execute('set transaction isolation level repeatable read')
            count,size=self.db.execute(f'''select count(*),coalesce(sum(octet_length(to_jsonb(m)::text)+512),0)
                from audit.measurements m where {where}''',values).fetchone()
            size=int(size)
            check_result_size(count,size)
            return self._rows(f'''select m.*, coalesce((r.record->>'provisional')::boolean,true) provisional,
                r.record->>'score_state' score_state from audit.measurements m join audit.records r
                using(participant_id,provider,dataset,record_key) where {where}
                order by coalesce(m.measured_at,m.interval_start),m.civil_date::text,m.record_key,m.metric''',
                values,allowance=size*2+65_536)

    @safe_database
    def sessions(self, selection, rows):
        self.principal()
        keys=sorted({r['record_key'] for r in rows})
        return self._rows('''select * from audit.sessions where participant_id=%s and provider=%s
           and dataset=%s and record_key=any(%s) order by started_at,record_key''',
           (selection.participant,selection.provider,selection.dataset,keys),allowance=len(keys)*2048+65_536)

    @safe_database
    def manifests(self, selection, rows):
        self.principal()
        ids=sorted({r['source_response_id'] for r in rows})
        sources=self._rows('''select response_id,participant_id,provider,dataset,endpoint,requested_range,
          requested_resolution,collected_at,content_sha256,compressed_bytes from audit.raw_response_manifest
          where participant_id=%s and provider=%s and dataset=%s and response_id=any(%s)
          order by collected_at,response_id''',
          (selection.participant,selection.provider,selection.dataset,ids),allowance=len(ids)*4096+65_536)
        return sources

    @safe_database
    def status(self, selection):
        self.principal()
        states=self._rows('''select authorization_status,last_success_at,covered_intervals,updated_at
          from audit.connection_state where participant_id=%s and provider=%s and dataset=%s''',
          (selection.participant,selection.provider,selection.dataset),allowance=1_000_000)
        # Whitelist fields; continuation cursors and provider credential tables never enter UI.
        runs=self._rows('''select run_id,started_at,finished_at,status,
          details->'completed' completed_datasets,details->'skipped' skipped_datasets,
          details->'failures' failures,details->>'pause_reason' pause_reason,
          details->>'github_run_id' github_run_id,details->>'github_run_attempt' github_run_attempt
          from audit.collection_runs where participant_id=%s and provider=%s
          order by started_at desc limit 20''',(selection.participant,selection.provider),allowance=1_000_000)
        return {'connection':states,'runs':runs}

    @safe_database
    def original(self, response_id, selection):
        self.principal()
        if not re.fullmatch('[a-f0-9]{64}',response_id):
            raise SentraError('Invalid original-response identity.')
        # Re-evaluate the active selection; a forged/stale ID cannot escape its scope.
        current=self.measurements(selection)
        if response_id not in {r['source_response_id'] for r in current}:
            raise SentraError('Original response is outside the current filtered selection.')
        rows=self._rows('''select content_sha256,compressed_bytes,object_location from audit.raw_response_manifest
          where response_id=%s and participant_id=%s and provider=%s and dataset=%s''',
          (response_id,selection.participant,selection.provider,selection.dataset),allowance=16_384)
        if len(rows)!=1:
            raise SentraError('Original response unavailable.')
        r=rows[0]
        key=object_key(selection.provider,selection.participant,r['content_sha256'])
        if r['object_location']!=BUCKET+'/'+key or not 0<r['compressed_bytes']<=16_777_216:
            raise SentraError('Original-response location/size invalid; no download prepared.')
        self.principal()
        return self.storage.get(key,r['content_sha256'],maximum=max(r['compressed_bytes']*2,65_536))
