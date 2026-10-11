"""Least-privilege PostgreSQL and private Storage clients; sanitized errors only."""
import gzip
import hashlib
import json
import time
from decimal import Decimal
from urllib.parse import quote

import psycopg
from psycopg.types.json import Jsonb
import requests

from .datasets import canonical
from .errors import SentraError
from .shared import CapacityStop, object_key, signature,database_estimate
from .local_store import compact_record,expanded_record

BUCKET = 'sentra-originals'


def connect_db(credentials):
    try:
        db = dict(credentials['db'])
        db.update(sslmode='verify-full', connect_timeout=15, application_name='sentra-audit',
                  options='-c statement_timeout=60000 -c lock_timeout=10000')
        return psycopg.connect(**db, autocommit=True)
    except Exception:
        raise SentraError('Hosted database unavailable. Check Free-project pause, credentials and certificate; details omitted.') from None


class PrivateStorage:
    def __init__(self, credentials, reserve, *, session=None, bucket=BUCKET):
        self.credentials = credentials
        self.reserve = reserve
        self.session = session or requests.Session()
        self.headers = None
        self.bucket = bucket

    def login(self):
        self.reserve(32_768)
        try:
            r = self.session.post(self.credentials['url'] + '/auth/v1/token?grant_type=password',
                headers={'apikey': self.credentials['publishable_key']},
                json={'email': self.credentials['storage_email'], 'password': self.credentials['storage_password']},
                timeout=(10,30), allow_redirects=False)
            if r.status_code != 200:
                raise ValueError
            token = r.json()['access_token']
            self.headers = {'apikey': self.credentials['publishable_key'], 'Authorization': 'Bearer ' + token}
        except (requests.RequestException, ValueError, KeyError):
            raise SentraError('Private Storage authorization failed; check the restricted service account.') from None

    def request(self, method, key, *, data=None, maximum=16_777_216, content_type='application/gzip', upsert=False):
        if self.headers is None:
            self.login()
        # Only derived tier objects are ever replaced; originals use plain immutable inserts.
        extra = {'x-upsert': 'true'} if upsert and self.bucket != BUCKET else {}
        for attempt in range(3):
            self.reserve(maximum + 32_768 if method == 'GET' else 32_768)
            url = self.credentials['url'] + '/storage/v1/object/'
            if method == 'GET':
                url += 'authenticated/'
            url += self.bucket + '/' + quote(key, safe='/')
            try:
                with self.session.request(method, url, headers={**self.headers, 'Content-Type': content_type, **extra},
                        data=data, timeout=(10,45), allow_redirects=False, stream=True) as r:
                    if r.status_code == 401 and attempt == 0:
                        self.login()
                        continue
                    if r.status_code in (429,500,502,503,504) and attempt < 2:
                        time.sleep(attempt + 1)
                        continue
                    body = bytearray()
                    for chunk in r.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > maximum:
                            raise SentraError('Private Storage response exceeds the bounded size.')
                    return r.status_code, bytes(body)
            except requests.RequestException:
                if attempt == 2:
                    raise SentraError('Private Storage request failed; retry the shared operation to resume.') from None
                time.sleep(attempt + 1)
        raise SentraError('Private Storage retry limit reached.')

    def get(self, key, expected_hash, maximum=16_777_216):
        code, body = self.request('GET', key, maximum=maximum)
        try:
            if code != 200 or hashlib.sha256(gzip.decompress(body)).hexdigest() != expected_hash:
                raise ValueError
        except (ValueError, OSError, EOFError):
            raise SentraError('Private original response missing or hash mismatch; existing objects preserved.') from None
        return body

    def put(self, key, compressed, digest):
        code, _ = self.request('POST', key, data=compressed, maximum=65_536)
        if code not in (200,201,400,409):
            raise SentraError('Private original upload failed; shared progress not advanced.')
        # An ambiguous retry/collision must verify the existing content, never overwrite it.
        if code in (400,409):
            self.get(key, digest, maximum=max(len(compressed) * 2, 65_536))


class SharedBackend:
    def __init__(self, credentials, limits):
        self.credentials, self.limits = credentials, limits
        self.db = connect_db(credentials)
        self.storage = PrivateStorage(credentials, self.reserve)
        self._object_cache = {}

    def close(self):
        self.db.close()

    def reserve_external(self, amount):
        connection = connect_db(self.credentials)
        try:
            connection.execute('select collector_private.reserve_egress(%s,%s)',(amount,self.limits.monthly_egress_bytes))
        except psycopg.Error:
            raise CapacityStop('Backup egress allowance exhausted or baseline stale; no further data read.') from None
        finally:
            connection.close()

    def reserve(self, amount):
        try:
            self.db.execute('select collector_private.reserve_egress(%s,%s)',
                            (amount, self.limits.monthly_egress_bytes))
        except psycopg.Error:
            raise CapacityStop('Egress budget missing, stale or exhausted. Verify organization usage and refresh its baseline; no upload continued.') from None

    def usage(self):
        self.reserve(32_768)
        return self.db.execute('select collector_private.usage()').fetchone()[0]

    def guard(self, **additions):
        usage = self.usage()
        self.limits.check(usage, **additions)
        return usage

    def lock(self):
        if not self.db.execute('select pg_try_advisory_lock(735003)').fetchone()[0]:
            raise SentraError('Another shared writer is active; retry after it finishes.')

    def unlock(self):
        self.db.execute('select pg_advisory_unlock(735003)')

    def has_manifest(self, response_id):
        self.reserve(16_384)
        return bool(self.db.execute('select 1 from audit.raw_response_manifest where response_id=%s', (response_id,)).fetchone())

    def manifest_ids(self, provider,participant):
        self.reserve(32_768)
        count = self.db.execute('select count(*) from audit.raw_response_manifest where provider=%s and participant_id=%s',(provider,participant)).fetchone()[0]
        self.reserve(count*256+32_768)
        return {r[0] for r in self.db.execute('select response_id from audit.raw_response_manifest where provider=%s and participant_id=%s',(provider,participant))}

    def has_object(self, provider, participant, digest):
        identity = (provider,participant)
        if identity not in self._object_cache:
            self.reserve(32_768)
            count = self.db.execute('select count(*) from audit.raw_response_manifest where provider=%s and participant_id=%s',identity).fetchone()[0]
            self.reserve(count*256+32_768)
            self._object_cache[identity] = {r[0] for r in self.db.execute('select distinct content_sha256 from audit.raw_response_manifest where provider=%s and participant_id=%s',identity)}
        return digest in self._object_cache[identity]

    def put_manifest(self, m, compressed):
        key = object_key(m['provider'],m['participant_id'],m['content_sha256'])
        exists = self.has_object(m['provider'],m['participant_id'],m['content_sha256'])
        self.guard(database_add=len(canonical(m).encode()) * 10 + 16_384,
                   object_add=0 if exists else len(compressed))
        if not exists:
            self.storage.put(key, compressed, m['content_sha256'])
        cloud = {k:v for k,v in m.items() if k != 'body_file'}
        cloud.update(object_location=BUCKET + '/' + key, compressed_bytes=len(compressed))
        with self.db.transaction():
            self.db.execute('insert into audit.participants(participant_id) values (%s) on conflict do nothing', (m['participant_id'],))
            self.db.execute('''insert into audit.raw_response_manifest values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (response_id) do nothing''', (m['response_id'],m['participant_id'],m['provider'],m['dataset'],m['endpoint'],
                    Jsonb({k:m.get(k) for k in ('requested_start','requested_end','requested_civil_start','requested_civil_end')}),
                    m['resolution'],m['collected_at'],BUCKET+'/'+key,m['content_sha256'],len(compressed),Jsonb(cloud)))
        self._object_cache[(m['provider'],m['participant_id'])].add(m['content_sha256'])

    def record_hashes(self, participant, provider, dataset):
        self.reserve(32_768)
        size = self.db.execute('select coalesce(sum(octet_length(record_key)+octet_length(content_sha256)+128),0) from audit.records where participant_id=%s and provider=%s and dataset=%s',
                             (participant,provider,dataset)).fetchone()[0]
        self.reserve(size * 2 + 32_768)
        return dict(self.db.execute('select record_key,content_sha256 from audit.records where participant_id=%s and provider=%s and dataset=%s',
                                   (participant,provider,dataset)).fetchall())

    def verify_content(self, participant, provider):
        self.reserve(32_768)
        size = self.db.execute('select coalesce(sum(octet_length(record::text)+128),0) from audit.records where participant_id=%s and provider=%s',
                             (participant,provider)).fetchone()[0]
        self.reserve(size * 2 + 65_536)
        count = 0
        with self.db.transaction():
            with self.db.cursor(name='verify_records') as cursor:
                cursor.execute('select record,content_sha256 from audit.records where participant_id=%s and provider=%s',(participant,provider))
                for record,digest in cursor:
                    if signature(expanded_record(record)) != digest:
                        raise SentraError('Shared record content hash mismatch; no matching-data claim made.')
                    count += 1
        return count

    def verify_projections(self, participant, provider):
        self.reserve(65_536)
        # Compare every expected scalar against the searchable projection, including NULL/time semantics.
        # Materialize context once per record and scalar once per metric. Inlining this
        # expression causes repeated JSON decompression and a quadratic join for wide sessions.
        mismatches = self.db.execute('''with record_context as materialized (
          select participant_id,provider,dataset,record_key,record->'measurements' metrics,
                 record-'measurements'-'vendor_fields'-'score_state'-'session_type' context
          from audit.records where participant_id=%s and provider=%s), expected as materialized (
          select participant_id,provider,dataset,record_key,context || raw_metric as e
          from record_context cross join lateral jsonb_array_elements(metrics) raw_metric)
          select count(*) from expected r
          left join audit.measurements m on (m.participant_id,m.provider,m.dataset,m.record_key,m.metric)=
            (r.participant_id,r.provider,r.dataset,r.record_key,e->>'metric')
          where (m.metric is null or
          (m.value,m.unit,m.vendor_value,m.vendor_unit,m.value_kind,m.availability,m.measured_at,m.interval_start,m.interval_end,
           m.civil_date,m.timestamp_basis,m.vendor_time,m.collected_at,m.resolution_seconds,m.resolution_description,m.source_response_id,m.source_pointer)
          is distinct from
          ((e->>'value')::numeric,e->>'unit',e->'vendor_value',e->>'vendor_unit',e->>'value_kind',e->>'availability',
           (e->>'measured_at')::timestamptz,(e->>'interval_start')::timestamptz,(e->>'interval_end')::timestamptz,
           e->'civil_date',e->>'timestamp_basis',e->'vendor_time',(e->>'collected_at')::timestamptz,
           (e->>'resolution_seconds')::numeric,e->>'resolution_description',e->>'source_response_id',e->>'source_pointer'))''',
          (participant,provider)).fetchone()[0]
        sessions = self.db.execute('''select count(*) from audit.records r left join audit.sessions s
          on (s.participant_id,s.provider,s.dataset,s.record_key)=(r.participant_id,r.provider,r.dataset,r.record_key)
          where r.participant_id=%s and r.provider=%s and r.record->>'session_type' is not null and
          (s.session_type is null or (s.session_type,s.started_at,s.ended_at,s.score_state,s.provisional) is distinct from
          (r.record->>'session_type',(r.record->>'interval_start')::timestamptz,(r.record->>'interval_end')::timestamptz,
           r.record->>'score_state',(r.record->>'provisional')::boolean))''',(participant,provider)).fetchone()[0]
        if mismatches or sessions:
            raise SentraError('Searchable measurement/session projections differ from verified record context.')
        return {'measurement_mismatches':mismatches,'session_mismatches':sessions}

    def put_records(self, records):
        if not records:
            return
        self.guard(database_add=sum(database_estimate(r) for r in records))
        self.reserve(65_536)
        with self.db.pipeline(), self.db.transaction():
            for r in records:
                identity = (r['participant_id'],r['provider'],r['dataset'],r['record_key'])
                self.db.execute('''insert into audit.records values (%s,%s,%s,%s,%s,%s,%s,%s)
                  on conflict (participant_id,provider,dataset,record_key) do update set content_sha256=excluded.content_sha256,
                  record=excluded.record,source_response_id=excluded.source_response_id,collected_at=excluded.collected_at''',
                  (*identity,signature(r),Jsonb(compact_record(r)),r['source_response_id'],r['collected_at']))
                self.db.execute('delete from audit.measurements where participant_id=%s and provider=%s and dataset=%s and record_key=%s',identity)
                self.db.execute('delete from audit.sessions where participant_id=%s and provider=%s and dataset=%s and record_key=%s',identity)
                for m in r['measurements']:
                    self.db.execute('insert into audit.measurements values (' + ','.join(['%s']*22) + ')',
                        (*identity,m['metric'],Decimal(str(m['value'])) if m['value'] is not None else None,m['unit'],Jsonb(m['vendor_value']),m['vendor_unit'],m['value_kind'],m['availability'],
                         m['measured_at'],m['interval_start'],m['interval_end'],Jsonb(m['civil_date']),m['timestamp_basis'],Jsonb(m['vendor_time']),
                         m['collected_at'],Decimal(str(m['resolution_seconds'])) if m['resolution_seconds'] is not None else None,m['resolution_description'],m['source_response_id'],m['source_pointer']))
                if r['session_type']:
                    self.db.execute('insert into audit.sessions values (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (*identity,r['session_type'],r['interval_start'],r['interval_end'],r['score_state'],r['provisional']))

    def save_state(self, participant, provider, jobs, runs):
        self.guard(database_add=len(canonical(jobs + runs).encode()) * 10 + 16_384)
        grouped = {}
        for job in jobs:
            grouped.setdefault(job['job']['dataset'], []).append(job)
        with self.db.transaction():
            for dataset, items in grouped.items():
                completed = [j for j in items if j['status'] == 'complete']
                covered = [{'start':j['job']['start'],'end':j['job']['end'],'requested_civil_start':j['job']['start_date'],
                            'requested_civil_end':j['job']['end_date']} for j in completed]
                last = max((j['completed_at'] for j in completed), default=None)
                self.db.execute('''insert into audit.connection_state(participant_id,provider,dataset,authorization_status,last_success_at,covered_intervals,continuation_state)
                    values (%s,%s,%s,%s,%s,%s,%s) on conflict (participant_id,provider,dataset) do update
                    set last_success_at=excluded.last_success_at,covered_intervals=excluded.covered_intervals,
                    continuation_state=excluded.continuation_state,updated_at=now()''',
                    (participant,provider,dataset,'authorized',last,Jsonb(covered),Jsonb({'jobs':items})))
            for r in runs:
                self.db.execute('insert into audit.collection_runs values (%s,%s,%s,%s,%s,%s,%s) on conflict do nothing',
                    (r['run_id'],participant,provider,r['started_at'],r['finished_at'],r['status'],Jsonb(r)))

    def counts(self, participant, provider):
        self.reserve(32_768)
        output = {}
        for table in ('records','measurements','sessions','raw_response_manifest'):
            output[table] = self.db.execute(f'select count(*) from audit.{table} where participant_id=%s and provider=%s', (participant,provider)).fetchone()[0]
        return output

    def growth_report(self):
        self.reserve(131_072)
        rows=self.db.execute('''with records as (
            select participant_id,provider,dataset,count(*) records,sum(pg_column_size(record)) record_bytes
            from audit.records group by 1,2,3), metrics as (
            select participant_id,provider,dataset,count(*) measurements,sum(pg_column_size(m)) measurement_bytes
            from audit.measurements m group by 1,2,3), coverage as (
            select participant_id,provider,dataset,
              max((requested_range->>'requested_civil_end')::date)-min((requested_range->>'requested_civil_start')::date) requested_days
            from audit.raw_response_manifest group by 1,2,3)
            select c.participant_id,c.provider,c.dataset,c.requested_days,coalesce(r.records,0),coalesce(m.measurements,0),
                   coalesce(r.record_bytes,0),coalesce(m.measurement_bytes,0)
            from coverage c left join records r using(participant_id,provider,dataset)
            left join metrics m using(participant_id,provider,dataset) order by 1,2,3''').fetchall()
        usage=self.usage()
        logical=sum(int(r[6])+int(r[7]) for r in rows)
        factor=usage['audit_bytes']/logical if logical else 0
        result=[]
        for pid,provider,dataset,days,records,metrics,record_bytes,metric_bytes in rows:
            payload=int(record_bytes)+int(metric_bytes)
            result.append({'participant_id':pid,'provider':provider,'dataset':dataset,'requested_days':days,
                'records':records,'measurements':metrics,'stored_payload_bytes':payload,
                'initial_mean_payload_bytes_per_requested_day':round(payload/days) if days else None,
                'approximate_database_bytes_per_requested_day':round(payload*factor/days) if days else None})
        raw=self.db.execute('''select participant_id,provider,sum(bytes) from
            (select participant_id,provider,content_sha256,max(compressed_bytes) bytes
             from audit.raw_response_manifest group by 1,2,3) objects group by 1,2 order by 1,2''').fetchall()
        return {'usage':usage,'datasets':result,'unique_original_bytes':[{'participant_id':p,'provider':v,'bytes':int(b)} for p,v,b in raw],
            'meaning':'Initial-import averages. Database allocation uses a project-wide table/index overhead ratio; future corrections, bloat and delivery vary. Original-resolution heart rate covers one representative day, minutes seven days, other datasets 30. These are not observed daily growth forecasts.'}
