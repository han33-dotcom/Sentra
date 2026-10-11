"""Chunked authenticated encrypted health-only backups; no OAuth credentials."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from cryptography.fernet import InvalidToken
from filelock import FileLock
from psycopg import sql
from psycopg.types.json import Jsonb

from .datasets import canonical
from .errors import SentraError
from .shared import CapacityStop
from .vault import atomic_write

TABLES = ('participants','raw_response_manifest','records','measurements','sessions','collection_runs','connection_state')
SAFE_NAME = re.compile(r'[a-z0-9_-]{1,100}')


def row_fingerprint(rows):
    """Order-independent SHA-256 multiset fingerprint, with counts checked separately."""
    return f"{sum(int(hashlib.sha256(canonical(r).encode()).hexdigest(),16) for r in rows) % (1 << 256):064x}"


class BackupWriter:
    def __init__(self, root, cipher, *, max_bytes=200_000_000, private_root=None):
        self.folder = Path(root) / str(uuid4())
        self.folder.mkdir(parents=True,exist_ok=False)
        self.cipher, self.max_bytes, self.written, self.files = cipher,max_bytes,0,{}
        self.private_root = Path(private_root or root)

    def capacity(self, addition):
        used = sum(p.stat().st_size for p in self.private_root.rglob('*') if p.is_file())
        if used + addition >= self.max_bytes:
            raise CapacityStop('Private backup storage ceiling reached; existing files retained.')
        if shutil.disk_usage(self.folder).free < max(64_000_000,2*addition):
            raise CapacityStop('Insufficient local disk headroom for an encrypted backup.')

    def write(self, name, body, *, rows=0):
        if not SAFE_NAME.fullmatch(name) or name in self.files:
            raise SentraError('Invalid/duplicate backup member name.')
        value = self.cipher.encrypt(gzip.compress(body,mtime=0))
        if self.written + len(value) >= self.max_bytes:
            raise CapacityStop('Private backup size threshold reached; incomplete backup retained for inspection.')
        self.capacity(len(value))
        atomic_write(self.folder / (name + '.enc'),value)
        self.files[name] = {'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'rows':rows,'encrypted_bytes':len(value)}
        self.written += len(value)

    def finish(self, info):
        info = {**info,'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'files':self.files}
        value = self.cipher.encrypt(canonical(info).encode())
        if self.written + len(value) >= self.max_bytes:
            raise CapacityStop('Backup manifest would exceed the configured size threshold.')
        self.capacity(len(value))
        target = self.folder / 'manifest.enc'
        atomic_write(target,value)
        return target


class BackupReader:
    def __init__(self, path, cipher):
        self.path, self.cipher = Path(path).resolve(),cipher
        try:
            self.info = json.loads(cipher.decrypt(self.path.read_bytes()))
            if self.path.name != 'manifest.enc' or self.info['format'] != 1 or not isinstance(self.info['files'],dict):
                raise ValueError
            for name, item in self.info['files'].items():
                if not SAFE_NAME.fullmatch(name) or type(item['bytes']) is not int or not 0 <= item['bytes'] <= 32_000_000:
                    raise ValueError
        except (OSError,ValueError,KeyError,TypeError,InvalidToken):
            raise SentraError('Backup manifest invalid or encryption key unavailable; no restoration attempted.') from None

    def read(self, name):
        try:
            if name not in self.info['files'] or not SAFE_NAME.fullmatch(name):
                raise ValueError
            item = self.info['files'][name]
            encrypted = self.path.parent / (name + '.enc')
            if encrypted.stat().st_size != item['encrypted_bytes']:
                raise ValueError
            # Bounded gzip decompression prevents a damaged/untrusted archive allocating arbitrarily.
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(self.cipher.decrypt(encrypted.read_bytes()))) as stream:
                body = stream.read(item['bytes'] + 1)
            if len(body) != item['bytes'] or hashlib.sha256(body).hexdigest() != item['sha256']:
                raise ValueError
            return body
        except (OSError,ValueError,EOFError,InvalidToken):
            raise SentraError('Backup member corrupt, missing or unauthenticated; restoration stopped.') from None


def make_backup(backend, root, cipher, *, participant=None, provider=None, dataset=None, max_bytes=200_000_000):
    # Serialize local quota writers with collection and exports, as well as cloud writers.
    with FileLock(Path(root).parent / 'collection-io.lock',timeout=10):
        return _make_backup(backend,root,cipher,participant=participant,provider=provider,dataset=dataset,max_bytes=max_bytes)


def _make_backup(backend, root, cipher, *, participant=None, provider=None, dataset=None, max_bytes=200_000_000):
    writer = BackupWriter(root,cipher,max_bytes=max_bytes,private_root=Path(root).parent)
    totals, objects, fingerprints = {}, {}, {}
    backend.lock()
    try:
        backend.guard()
        # A repeatable-read transaction gives all tables one coherent version.
        with backend.db.transaction():
            backend.db.execute('set transaction isolation level repeatable read read only')
            for table in TABLES:
                filters, params = [], []
                if participant:
                    filters.append(sql.SQL('participant_id=%s')); params.append(participant)
                if provider and table != 'participants':
                    filters.append(sql.SQL('provider=%s')); params.append(provider)
                if dataset and table not in ('participants','collection_runs'):
                    filters.append(sql.SQL('dataset=%s')); params.append(dataset)
                query = sql.SQL('select to_jsonb(t) from audit.{} t').format(sql.Identifier(table))
                if filters:
                    query += sql.SQL(' where ') + sql.SQL(' and ').join(filters)
                # Estimate reads from actual table storage, reserve before fetching health rows.
                size_query = sql.SQL('select coalesce(sum(octet_length(to_jsonb(t)::text)+128),0) from audit.{} t').format(sql.Identifier(table))
                if filters: size_query += sql.SQL(' where ') + sql.SQL(' and ').join(filters)
                size = backend.db.execute(size_query,params).fetchone()[0]
                # Budget updates use a separate transaction/connection outside read-only snapshot.
                backend.reserve_external(size * 2 + 65_536)
                total, part, fingerprint, buffer = 0,0,0,bytearray()
                with backend.db.cursor(name='backup_' + table) as cursor:
                    cursor.execute(query,params)
                    for row in cursor:
                        encoded = (canonical(row[0])+'\n').encode()
                        if len(encoded) > 16_777_216:
                            raise SentraError('Backup row exceeds supported size; no truncation performed.')
                        if buffer and len(buffer)+len(encoded) > 1_000_000:
                            writer.write(f'{table}-{part:05d}',bytes(buffer),rows=buffer.count(b'\n'))
                            part += 1; buffer.clear()
                        buffer.extend(encoded); total += 1
                        fingerprint = (fingerprint + int(hashlib.sha256(canonical(row[0]).encode()).hexdigest(),16)) % (1 << 256)
                        if table == 'raw_response_manifest':
                            objects[row[0]['object_location']] = (row[0]['content_sha256'],row[0]['compressed_bytes'])
                if buffer:
                    writer.write(f'{table}-{part:05d}',bytes(buffer),rows=buffer.count(b'\n'))
                totals[table] = total
                fingerprints[table] = f'{fingerprint:064x}'
        for location,(digest,size) in objects.items():
            key = location.split('/',1)[1]
            content = backend.storage.get(key,digest,maximum=max(size*2,65_536))
            writer.write('raw-' + hashlib.sha256(location.encode()).hexdigest(),content)
        return writer.finish({'tables':totals,'table_fingerprints':fingerprints,'objects':objects,'project_url':backend.credentials['url'],
                              'selection':{'participant':participant,'provider':provider,'dataset':dataset},
                              'excludes':'provider credentials, storage accounts, database passwords and OAuth keys'})
    finally:
        backend.unlock()


def restore_backup(reader, backend, admin_db, *, empty_audit=False):
    # Validate every member before any cloud change. Only a new isolated schema may be created.
    for name in reader.info['files']:
        reader.read(name)
    if set(reader.info.get('tables',{})) != set(TABLES) or set(reader.info.get('table_fingerprints',{})) != set(TABLES):
        raise SentraError('Backup table inventory incomplete; no restoration attempted.')
    required = sum(i['bytes'] * 8 for name,i in reader.info['files'].items() if not name.startswith('raw-'))
    name = 'audit' if empty_audit else 'sentra_restore_' + uuid4().hex[:12]
    backend.lock()
    try:
        backend.guard(database_add=required)
        backend.reserve(sum(i['bytes']*2 for name,i in reader.info['files'].items() if not name.startswith('raw-')) + 65_536)
        with admin_db.transaction():
            if empty_audit:
                if any(admin_db.execute(sql.SQL('select exists(select 1 from audit.{})').format(sql.Identifier(t))).fetchone()[0] for t in TABLES):
                    raise SentraError('All audit tables must be empty for operational restoration; existing data preserved.')
            else:
                admin_db.execute(sql.SQL('create schema {}').format(sql.Identifier(name)))
                admin_db.execute(sql.SQL('revoke all on schema {} from public,anon,authenticated,sentra_viewer').format(sql.Identifier(name)))
            for table in TABLES:
                if not empty_audit:
                    admin_db.execute(sql.SQL('create table {}.{} (like audit.{} including all)').format(
                        sql.Identifier(name),sql.Identifier(table),sql.Identifier(table)))
                    admin_db.execute(sql.SQL('revoke all on {}.{} from public,anon,authenticated,sentra_viewer').format(sql.Identifier(name),sql.Identifier(table)))
                inserted = 0
                for member in sorted(reader.info['files']):
                    if not member.startswith(table+'-'):
                        continue
                    for line in reader.read(member).splitlines():
                        row = json.loads(line)
                        admin_db.execute(sql.SQL('insert into {}.{} select * from jsonb_populate_record(null::{}.{},%s)').format(
                            sql.Identifier(name),sql.Identifier(table),sql.Identifier(name),sql.Identifier(table)), (Jsonb(row),))
                        inserted += 1
                        if inserted % 100 == 0:
                            backend.guard(database_add=2_000_000)
                count = admin_db.execute(sql.SQL('select count(*) from {}.{}').format(sql.Identifier(name),sql.Identifier(table))).fetchone()[0]
                if count != reader.info['tables'][table]:
                    raise SentraError('Restored backup count differs; isolated transaction rolled back.')
                with admin_db.cursor(name='restore_verify_'+table) as cursor:
                    cursor.execute(sql.SQL('select to_jsonb(t) from {}.{} t').format(sql.Identifier(name),sql.Identifier(table)))
                    fingerprint = row_fingerprint(row[0] for row in cursor)
                if fingerprint != reader.info['table_fingerprints'][table]:
                    raise SentraError('Restored row content differs; isolated transaction rolled back.')
            for location,(digest,size) in reader.info['objects'].items():
                compressed = reader.read('raw-' + hashlib.sha256(location.encode()).hexdigest())
                if hashlib.sha256(gzip.decompress(compressed)).hexdigest() != digest:
                    raise SentraError('Backup original response hash mismatch.')
                # Restore into the same immutable hash namespace; a missing object is uploaded safely.
                backend.guard(object_add=len(compressed))
                backend.storage.put(location.split('/',1)[1],compressed,digest)
        return {'schema':name,'counts':reader.info['tables'],'status':'restored_and_verified'}
    finally:
        backend.unlock()
