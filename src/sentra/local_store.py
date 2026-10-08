"""Small local audit workspace: SQLite in RAM, authenticated encrypted snapshots."""
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zlib

from cryptography.fernet import InvalidToken
from filelock import FileLock

from .datasets import canonical
from .errors import SentraError
from .normalize import normalize_record, is_context_field
from .vault import atomic_write


class CapacityStop(SentraError):
    pass


def compact_record(record):
    """Store shared context once; public records/exports restore metric context."""
    context = {k: v for k, v in record.items() if k not in ('measurements', 'vendor_fields', 'score_state', 'session_type')}
    return {**record, 'measurements': [{k: v for k, v in metric.items()
                                      if k not in context or v != context[k]}
                                     for metric in record['measurements'] if not is_context_field(metric['vendor_metric'])]}


def expanded_record(record):
    context = {k: v for k, v in record.items() if k not in ('measurements', 'vendor_fields', 'score_state', 'session_type')}
    return {**record, 'measurements': [{**context, **m} for m in record['measurements']]}


def encode_record(record):
    # Individual compressed rows bound SQLite RAM and checkpoint size even
    # for tens of thousands of original-resolution samples.
    return zlib.compress(canonical(compact_record(record)).encode(), level=3)


def decode_record(value):
    return json.loads(zlib.decompress(value) if isinstance(value, bytes) else value)


class LocalStore:
    def __init__(self, connection, cipher, *, max_bytes=200 * 1024 * 1024):
        self.connection = connection
        self.cipher = cipher
        self.max_bytes = max_bytes
        self.root = connection.private_dir
        self.folder = self.root / 'imports' / connection.provider / connection.participant_id
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'audit.sqlite.gz.enc'
        self.raw_folder = self.folder / 'raw'
        self.lock = FileLock(str(self.path) + '.lock', timeout=10)
        self.private_lock = FileLock(str(self.root / 'collection-io.lock'), timeout=10)
        self.db = None
        self.reload()

    def reload(self):
        if self.db is not None:
            self.db.close()
        self.db = sqlite3.connect(':memory:')
        self.db.execute('PRAGMA temp_store=MEMORY')
        try:
            if self.path.exists():
                self.db.deserialize(gzip.decompress(self.cipher.decrypt(self.path.read_bytes())))
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records (dataset TEXT, key TEXT, data TEXT NOT NULL, PRIMARY KEY(dataset,key));
                CREATE TABLE IF NOT EXISTS manifests (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS store_format (version INTEGER PRIMARY KEY);
            ''')
            if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError
            if not self.db.execute('SELECT 1 FROM store_format WHERE version=4').fetchone():
                # Upgrade snapshots produced during initial local development.
                # Only committed to disk with the next atomic page checkpoint.
                for dataset, key, text in self.db.execute('SELECT dataset,key,data FROM records'):
                    self.db.execute('UPDATE records SET data=? WHERE dataset=? AND key=?',
                                    (encode_record(decode_record(text)), dataset, key))
                self.db.execute('INSERT INTO store_format VALUES (4)')
                self.db.commit()
                self.db.execute('VACUUM')
        except (OSError, ValueError, InvalidToken, sqlite3.DatabaseError, EOFError, zlib.error):
            raise SentraError('Encrypted import store cannot be read; preserve it and check key/backup. No reset performed.') from None

    def usage(self):
        total = 0
        for path in self.root.rglob('*'):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                # Another connection can atomically rename a temporary file
                # while this shared private-directory usage scan is running.
                continue
        return total

    def check_capacity(self, additional=0, *, known_usage=None):
        usage = self.usage() if known_usage is None else known_usage
        if usage + additional >= self.max_bytes:
            raise CapacityStop('Local private storage limit reached; import stopped safely. Review usage/backup and configured limit.')
        if shutil.disk_usage(self.root).free < max(64 * 1024 * 1024, 2 * additional):
            raise CapacityStop('Insufficient free disk headroom; free space before resuming. Existing data retained.')

    def persist(self):
        try:
            self.db.commit()
            # Frequent page checkpoints favor fast compression over smallest
            # size; raw objects stay separately compressed and encrypted.
            encrypted = self.cipher.encrypt(gzip.compress(self.db.serialize(), compresslevel=1, mtime=0))
            self.check_capacity(len(encrypted)) # Atomic replace temporarily needs both copies.
            atomic_write(self.path, encrypted)
        except CapacityStop:
            self.reload()
            raise
        except (OSError, sqlite3.DatabaseError):
            self.reload()
            raise SentraError('Cannot persist import checkpoint; last durable page retained. Resume after fixing local storage.') from None

    def progress(self, job):
        row = self.db.execute('SELECT data FROM jobs WHERE key=?', (job.key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _progress(self, job, value):
        self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job.key, canonical(value)))

    def start_job(self, job, *, recheck=False):
        current = self.progress(job)
        if not current or recheck:
            self._progress(job, {'job': asdict(job), 'status': 'running', 'cursor': '', 'seen': [],
                                 'pages': 0, 'received': 0, 'completed_at': None, 'failure': None})
            self.persist()

    def reset_cursor(self, job):
        self.start_job(job, recheck=True)

    def retire_covered_jobs(self, jobs):
        complete = [j for j in jobs if self.progress(j) and self.progress(j)['status'] == 'complete']
        for key, text in self.db.execute('SELECT key,data FROM jobs'):
            prior = json.loads(text)
            if prior['status'] not in ('running', 'failed'):
                continue
            old = prior['job']
            replacement = next((j for j in complete if j.key != key and j.dataset == old['dataset']
                                and j.datatype == old['datatype'] and j.mode == old['mode']
                                and j.start <= old['start'] and j.end >= old['end']), None)
            if replacement:
                prior.update(status='superseded', superseded_by=replacement.key)
                self.db.execute('UPDATE jobs SET data=? WHERE key=?', (canonical(prior), key))

    def fail_job(self, job, message):
        value = self.progress(job)
        if value:
            value.update(status='failed', failure=message)
            self._progress(job, value)
            self.persist()

    def records(self, dataset=None):
        return list(self.iter_records(dataset))

    def iter_records(self, dataset=None):
        cycles = {key: decode_record(value) for key, value in self.db.execute(
            'SELECT key,data FROM records WHERE dataset=?', ('cycle',))} if self.connection.provider == 'whoop' else {}
        rows = self.db.execute('SELECT data FROM records' + (' WHERE dataset=?' if dataset else '') + ' ORDER BY dataset,key',
                               (dataset,) if dataset else ())
        for row in rows:
            record = decode_record(row[0])
            if record['dataset'] == 'recovery':
                cycle = cycles.get(str(record['vendor_fields'].get('cycle_id')))
                if cycle:
                    vendor = cycle['vendor_fields']
                    record.update(interval_start=vendor.get('start'), interval_end=vendor.get('end'),
                                  vendor_time={k: vendor[k] for k in ('start', 'end', 'timezone_offset') if k in vendor},
                                  timestamp_basis='associated_cycle_interval',
                                  associated_cycle_source_response_id=cycle['source_response_id'])
            yield expanded_record(record)

    def manifests(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM manifests ORDER BY key')]

    def save_page(self, job, cursor, payload, body, next_cursor):
        progress = self.progress(job)
        if job.provider == 'whoop' and job.records_key not in payload:
            raise SentraError('Malformed WHOOP collection; records member missing. Coverage not advanced.')
        records = payload.get(job.records_key, [])
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise SentraError('Malformed records page; last durable progress retained.')
        if next_cursor and (next_cursor == cursor or next_cursor in progress['seen']):
            raise SentraError('Repeated pagination token; stopped without claiming complete coverage.')
        digest = hashlib.sha256(body).hexdigest()
        collected = datetime.now(timezone.utc).isoformat()
        manifest_key = hashlib.sha256((job.key + cursor + digest + collected).encode()).hexdigest()
        normalized = []
        for index, record in enumerate(records):
            cycle = None
            if job.dataset == 'recovery':
                row = self.db.execute('SELECT data FROM records WHERE dataset=? AND key=?', ('cycle', str(record.get('cycle_id')))).fetchone()
                if row:
                    cycle = decode_record(row[0])['vendor_fields']
            value = normalize_record(job, record, cycle=cycle)
            value.update(participant_id=self.connection.participant_id, source_response_id=manifest_key,
                         source_pointer=f'/{job.records_key}/{index}', collected_at=collected)
            for metric in value['measurements']:
                metric.update(participant_id=self.connection.participant_id, source_response_id=manifest_key,
                              source_pointer=value['source_pointer'] + metric['vendor_metric'], collected_at=collected)
            normalized.append(value)
        raw_file = self.raw_folder / (digest + '.json.gz.enc')
        compressed_body = gzip.compress(body, mtime=0)
        encrypted_body = self.cipher.encrypt(compressed_body)
        self.check_capacity(len(encrypted_body) if not raw_file.exists() else 0)
        try:
            if not raw_file.exists():
                atomic_write(raw_file, encrypted_body)
            else:
                self.original_bytes({'body_file': raw_file.name, 'content_sha256': digest})
            manifest = {'response_id': manifest_key, 'provider': job.provider, 'participant_id': self.connection.participant_id,
                        'dataset': job.dataset, 'endpoint': job.request()['url'], 'requested_start': job.start, 'requested_end': job.end,
                        'requested_civil_start': job.start_date, 'requested_civil_end': job.end_date,
                        'request': job.request(cursor), 'resolution': job.resolution, 'collected_at': collected,
                        'http_status': 200, 'record_count': len(records), 'has_more_pages': bool(next_cursor),
                        'body_file': raw_file.name, 'content_sha256': digest, 'compressed_bytes': len(compressed_body),
                        'provenance': 'original_api_response', 'aggregation': job.mode}
            self.db.execute('INSERT OR REPLACE INTO manifests VALUES (?,?)', (manifest_key, canonical(manifest)))
            for value in normalized:
                self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (job.dataset, value['record_key'], encode_record(value)))
            progress.update(cursor=next_cursor, pages=progress['pages'] + 1,
                            received=progress['received'] + len(records), failure=None)
            if cursor:
                progress['seen'].append(cursor)
            progress['status'] = 'running' if next_cursor else 'complete'
            progress['completed_at'] = None if next_cursor else collected
            self._progress(job, progress)
            self.persist()
        except OSError:
            self.reload()
            raise SentraError('Cannot save encrypted response; page progress retained for resume.') from None

    def original_bytes(self, manifest):
        try:
            body = gzip.decompress(self.cipher.decrypt((self.raw_folder / manifest['body_file']).read_bytes()))
            if hashlib.sha256(body).hexdigest() != manifest['content_sha256']:
                raise ValueError
            return body
        except (OSError, ValueError, InvalidToken, EOFError):
            raise SentraError('Original response cannot be verified; preserve files and inspect backup/key.') from None

    def save_run(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)', (key, canonical(value)))
        self.persist()

    def status(self):
        jobs = [json.loads(r[0]) for r in self.db.execute('SELECT data FROM jobs ORDER BY key')]
        counts = {row[0]: row[1] for row in self.db.execute('SELECT dataset,count(*) FROM records GROUP BY dataset')}
        return {'provider': self.connection.provider, 'participant_id': self.connection.participant_id,
                'record_counts': counts, 'jobs_complete': sum(j['status'] == 'complete' for j in jobs),
                'jobs_failed': sum(j['status'] == 'failed' for j in jobs), 'jobs_total': len(jobs),
                'jobs_superseded': sum(j['status'] == 'superseded' for j in jobs),
                'manifests': self.db.execute('SELECT count(*) FROM manifests').fetchone()[0],
                'storage_bytes': self.usage(), 'storage_limit_bytes': self.max_bytes,
                'coverage': [{'dataset': j['job']['dataset'], 'start': j['job']['start'], 'end': j['job']['end'],
                              'status': j['status'], 'pages': j['pages'], 'received': j['received'],
                              'last_success': j['completed_at'], 'failure': j['failure']} for j in jobs]}
