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
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .datasets import canonical
from .errors import SentraError
from .shared import CapacityStop
from .vault import atomic_write

TABLES = ('participants','raw_response_manifest','records','measurements','sessions','collection_runs','connection_state')
# Consent history, organization roles and enrollment identities (sql/007, sql/008), in restore order.
# Browser sessions and rate limits are short-lived and excluded; so are credentials, as before.
PRIVATE_TABLES = ('org.organizations','org.org_users','org.memberships','org.consents',
                  'enrollment_private.invites','enrollment_private.identities')
IDENTITY_TABLES = {'org.memberships':'membership_id','org.consents':'consent_id'}
# Restored storage relative to the source's measured table size (heap, TOAST and indexes). Freshly
# inserted rows carry none of the source's dead-row bloat, so a small margin suffices; the running
# guard during insertion still stops the restore before any limit is crossed.
RESTORE_FACTOR = 1.05


def member(table):
    """Backup member prefix: audit tables keep their bare names, others are schema__table."""
    return table.replace('.','__')


def relation(table, schema='audit'):
    owner, _, name = table.rpartition('.')
    return sql.Identifier(owner or schema, name)
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


def make_backup(backend, root, cipher, *, participant=None, provider=None, dataset=None, max_bytes=200_000_000, admin_db=None):
    """admin_db (optional) adds the organization and enrollment tables to full backups."""
    # Serialize local quota writers with collection and exports, as well as cloud writers.
    with FileLock(Path(root).parent / 'collection-io.lock',timeout=10):
        return _make_backup(backend,root,cipher,participant=participant,provider=provider,dataset=dataset,
                            max_bytes=max_bytes,admin_db=admin_db)


def _export(db, backend, writer, table, filters, params, objects):
    """Write one table as bounded encrypted chunks; return its row count and fingerprint."""
    query = sql.SQL('select to_jsonb(t) from {} t').format(relation(table))
    size_query = sql.SQL('select coalesce(sum(octet_length(to_jsonb(t)::text)+128),0) from {} t').format(relation(table))
    if filters:
        query += sql.SQL(' where ') + sql.SQL(' and ').join(filters)
        size_query += sql.SQL(' where ') + sql.SQL(' and ').join(filters)
    # Estimate reads from actual table storage, reserve before fetching rows.
    size = db.execute(size_query,params).fetchone()[0]
    # Budget updates use a separate transaction/connection outside read-only snapshot.
    backend.reserve_external(size * 2 + 65_536)
    total, part, fingerprint, buffer, prefix = 0,0,0,bytearray(),member(table)
    with db.cursor(name='backup_' + prefix) as cursor:
        cursor.execute(query,params)
        for row in cursor:
            encoded = (canonical(row[0])+'\n').encode()
            if len(encoded) > 16_777_216:
                raise SentraError('Backup row exceeds supported size; no truncation performed.')
            if buffer and len(buffer)+len(encoded) > 1_000_000:
                writer.write(f'{prefix}-{part:05d}',bytes(buffer),rows=buffer.count(b'\n'))
                part += 1; buffer.clear()
            buffer.extend(encoded); total += 1
            fingerprint = (fingerprint + int(hashlib.sha256(canonical(row[0]).encode()).hexdigest(),16)) % (1 << 256)
            if table == 'raw_response_manifest':
                objects[row[0]['object_location']] = (row[0]['content_sha256'],row[0]['compressed_bytes'])
    if buffer:
        writer.write(f'{prefix}-{part:05d}',bytes(buffer),rows=buffer.count(b'\n'))
    return total, f'{fingerprint:064x}'


def _make_backup(backend, root, cipher, *, participant=None, provider=None, dataset=None, max_bytes=200_000_000, admin_db=None):
    writer = BackupWriter(root,cipher,max_bytes=max_bytes,private_root=Path(root).parent)
    totals, objects, fingerprints, sizes, private, private_fingerprints, absent = {}, {}, {}, {}, {}, {}, []
    selection = {'participant':participant,'provider':provider,'dataset':dataset} if participant or provider or dataset else None
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
                totals[table], fingerprints[table] = _export(backend.db, backend, writer, table, filters, params, objects)
                sizes[table] = backend.db.execute('select pg_total_relation_size(%s::regclass)', ('audit.'+table,)).fetchone()[0]
            if admin_db is not None and selection is None:
                # The same snapshot, read by the admin role: the collector cannot read these schemas.
                snapshot = backend.db.execute('select pg_export_snapshot()').fetchone()[0]
                with admin_db.transaction():
                    admin_db.execute('set transaction isolation level repeatable read read only')
                    admin_db.execute(sql.SQL('set transaction snapshot {}').format(sql.Literal(snapshot)))
                    # These tables FORCE row-level security. Without bypass rights the reads would silently
                    # return no rows; with row_security off they fail instead, so the backup stops.
                    admin_db.execute('set local row_security = off')
                    for table in PRIVATE_TABLES:
                        if admin_db.execute('select to_regclass(%s)', (table,)).fetchone()[0] is None:
                            absent.append(table)
                            continue
                        try:
                            private[table], private_fingerprints[table] = _export(admin_db, backend, writer, table, [], [], objects)
                        except psycopg.errors.InsufficientPrivilege:
                            raise SentraError('The admin connection cannot read every organization and enrollment row '
                                              '(row-level security applies to it); backup stopped. Use the project admin role.') from None
                        sizes[table] = admin_db.execute('select pg_total_relation_size(%s::regclass)', (table,)).fetchone()[0]
        for location,(digest,size) in objects.items():
            key = location.split('/',1)[1]
            content = backend.storage.get(key,digest,maximum=max(size*2,65_536))
            writer.write('raw-' + hashlib.sha256(location.encode()).hexdigest(),content)
        return writer.finish({'tables':totals,'table_fingerprints':fingerprints,'objects':objects,'project_url':backend.credentials['url'],
                              'private_tables':private,'private_fingerprints':private_fingerprints,'private_absent':absent,
                              'table_bytes':{k:int(v) for k,v in sizes.items()},
                              'selection':{'participant':participant,'provider':provider,'dataset':dataset},
                              'excludes':'provider credentials, storage accounts, database passwords, OAuth keys, '
                                         'enrollment browser sessions and rate limits'
                                         + ('' if private or absent else '; organization and enrollment tables '
                                                                         '(no admin connection, or a partial selection)')})
    finally:
        backend.unlock()


def inventory(info):
    """[(table, rows, fingerprint)] for every table the manifest declares, audit tables first."""
    if set(info.get('tables',{})) != set(TABLES) or set(info.get('table_fingerprints',{})) != set(TABLES):
        raise SentraError('Backup table inventory incomplete.')
    private, fingerprints = info.get('private_tables',{}), info.get('private_fingerprints',{})
    if set(private) != set(fingerprints) or not set(private) <= set(PRIVATE_TABLES):
        raise SentraError('Backup organization/enrollment inventory incomplete.')
    return ([(t, info['tables'][t], info['table_fingerprints'][t]) for t in TABLES]
            + [(t, private[t], fingerprints[t]) for t in PRIVATE_TABLES if t in private])


def chunks(info, table):
    return sorted(name for name in info['files'] if name.startswith(member(table)+'-'))


def verify_backup(reader):
    """Offline check before any destructive step: every member decrypts and matches its hash, every
    table has its manifest row count and fingerprint, and every original response matches its digest.
    Reads only the local encrypted files; no database or storage access."""
    info = reader.info
    tables = inventory(info)
    objects = {location:(digest,size) for location,(digest,size) in info.get('objects',{}).items()}
    raw = {'raw-' + hashlib.sha256(location.encode()).hexdigest():location for location in objects}
    # Every declared member must be a table chunk or the original of a listed object, and every listed
    # original must be declared; nothing is skipped, so "members" below were all read and authenticated.
    chunk = re.compile('(' + '|'.join(member(t) for t,_,_ in tables) + r')-\d{5}')
    if any(not chunk.fullmatch(name) and name not in raw for name in info['files']) or not set(raw) <= set(info['files']):
        raise SentraError('Backup member inventory differs from its tables and originals.')
    counts, referenced = {}, {}
    for table,rows,expected in tables:
        total, fingerprint = 0, 0
        # One chunk is decoded at a time, so memory stays bounded by the chunk size, not the table.
        for name in chunks(info, table):
            for line in reader.read(name).splitlines():
                row = json.loads(line)
                total += 1
                fingerprint = (fingerprint + int(hashlib.sha256(canonical(row).encode()).hexdigest(),16)) % (1 << 256)
                if table == 'raw_response_manifest':
                    referenced[row['object_location']] = (row['content_sha256'],row['compressed_bytes'])
        if total != rows:
            raise SentraError(f'Backup row count differs for {table}.')
        if f'{fingerprint:064x}' != expected:
            raise SentraError(f'Backup row content differs for {table}.')
        counts[table] = total
    if referenced != objects:
        raise SentraError('Backup originals differ from the response manifest rows they belong to.')
    for name,location in raw.items():
        if hashlib.sha256(gzip.decompress(reader.read(name))).hexdigest() != objects[location][0]:
            raise SentraError('Backup original response hash mismatch.')
    return {'status':'verified','created_at':info.get('created_at'),'selection':info.get('selection'),
            'project_url':info.get('project_url'),'tables':counts,'originals':len(objects),'members':len(info['files']),
            'not_covered':info.get('private_absent',[]) if info.get('private_tables') or info.get('private_absent')
                          else list(PRIVATE_TABLES),
            'restore_estimate_bytes':restore_estimate(info)}


def restore_estimate(info):
    """Database bytes a restore may add: measured source table sizes when recorded, else the
    serialized size. Older backups without sizes stay conservative; the running guard still applies."""
    sizes = info.get('table_bytes')
    if isinstance(sizes,dict) and set(TABLES) <= set(sizes) and all(type(v) is int and v >= 0 for v in sizes.values()):
        return int(sum(sizes.values()) * RESTORE_FACTOR) + 16_000_000
    return sum(i['bytes'] for name,i in info['files'].items() if not name.startswith('raw-')) + 16_000_000


def advance_participant_numbers(db):
    """Move enrollment's participant-number allocator past every restored pNNN id, never backwards.

    A fresh target starts the sequence at 100; enrollment tries a bounded number of candidates, so
    restored participants would otherwise make new enrollments fail."""
    if db.execute("select to_regclass('enrollment_private.participant_number')").fetchone()[0] is None:
        return
    last, called = db.execute('select last_value,is_called from enrollment_private.participant_number').fetchone()
    restored = db.execute(r"""select coalesce(max(substr(participant_id,2)::int),0) from audit.participants
        where participant_id ~ '^p[0-9]{2,4}$'""").fetchone()[0]
    maximum = db.execute("""select max_value from pg_sequences
        where schemaname='enrollment_private' and sequencename='participant_number'""").fetchone()[0]
    following = max(last + 1 if called else last, restored + 1)
    if following > maximum:
        # Exhausted (e.g. p9999 restored): keep it at its bound so recovery still succeeds; new
        # enrollment then reports capacity exhaustion on its own instead of blocking the restore.
        db.execute("select setval('enrollment_private.participant_number',%s,true)", (maximum,))
    else:
        db.execute("select setval('enrollment_private.participant_number',%s,false)", (following,))


def restore_backup(reader, backend, admin_db, *, empty_audit=False):
    # Validate every member before any cloud change. Only a new isolated schema may be created.
    for name in reader.info['files']:
        reader.read(name)
    try:
        tables = inventory(reader.info)
    except SentraError:
        raise SentraError('Backup table inventory incomplete; no restoration attempted.') from None
    schema = 'audit' if empty_audit else 'sentra_restore_' + uuid4().hex[:12]
    target = lambda table: relation(table) if empty_audit else sql.Identifier(schema, member(table))
    backend.lock()
    try:
        # Measured source sizes, not a multiple of the serialized JSON (which exceeds the real storage).
        backend.guard(database_add=restore_estimate(reader.info))
        backend.reserve(sum(i['bytes']*2 for name,i in reader.info['files'].items() if not name.startswith('raw-')) + 65_536)
        with admin_db.transaction():
            # Checks and fingerprints must see every row, never a policy-filtered subset.
            admin_db.execute('set local row_security = off')
            for table,_,_ in tables:
                if '.' in table and admin_db.execute('select to_regclass(%s)', (table,)).fetchone()[0] is None:
                    raise SentraError('Apply sql/007 and sql/008 to the target before restoring organization and enrollment tables.')
            if empty_audit:
                if any(admin_db.execute(sql.SQL('select exists(select 1 from {})').format(relation(t))).fetchone()[0] for t,_,_ in tables):
                    raise SentraError('All restored tables must be empty for operational restoration; existing data preserved.')
            else:
                admin_db.execute(sql.SQL('create schema {}').format(sql.Identifier(schema)))
                admin_db.execute(sql.SQL('revoke all on schema {} from public,anon,authenticated,sentra_viewer').format(sql.Identifier(schema)))
            pending = 0
            for table,rows,expected in tables:
                if not empty_audit:
                    admin_db.execute(sql.SQL('create table {} (like {} including all)').format(target(table),relation(table)))
                    admin_db.execute(sql.SQL('revoke all on {} from public,anon,authenticated,sentra_viewer').format(target(table)))
                # Identity values are restored as recorded, so consent and membership ids keep their links.
                insert = sql.SQL('insert into {} {}select * from jsonb_populate_record(null::{},%s)').format(
                    target(table), sql.SQL('overriding system value ' if table in IDENTITY_TABLES else ''), target(table))
                for name in chunks(reader.info, table):
                    body = reader.read(name)
                    for line in body.splitlines():
                        admin_db.execute(insert, (Jsonb(json.loads(line)),))
                    # Recheck real usage as rows land; uncommitted rows already occupy database space.
                    pending += len(body)
                    if pending >= 1_000_000:
                        backend.guard(database_add=2_000_000)
                        pending = 0
                if empty_audit and table in IDENTITY_TABLES:
                    column = IDENTITY_TABLES[table]
                    admin_db.execute(sql.SQL("select setval(pg_get_serial_sequence({},{}),coalesce(max({}),0)+1,false) from {}").format(
                        sql.Literal(table),sql.Literal(column),sql.Identifier(column),relation(table)))
                if empty_audit and table == 'participants':
                    advance_participant_numbers(admin_db)
                count = admin_db.execute(sql.SQL('select count(*) from {}').format(target(table))).fetchone()[0]
                if count != rows:
                    raise SentraError('Restored backup count differs; isolated transaction rolled back.')
                with admin_db.cursor(name='restore_verify_'+member(table).replace('.','_')) as cursor:
                    cursor.execute(sql.SQL('select to_jsonb(t) from {} t').format(target(table)))
                    fingerprint = row_fingerprint(row[0] for row in cursor)
                if fingerprint != expected:
                    raise SentraError('Restored row content differs; isolated transaction rolled back.')
            for location,(digest,size) in reader.info['objects'].items():
                compressed = reader.read('raw-' + hashlib.sha256(location.encode()).hexdigest())
                if hashlib.sha256(gzip.decompress(compressed)).hexdigest() != digest:
                    raise SentraError('Backup original response hash mismatch.')
                # Restore into the same immutable hash namespace; a missing object is uploaded safely.
                backend.guard(object_add=len(compressed))
                backend.storage.put(location.split('/',1)[1],compressed,digest)
        return {'schema':schema,'counts':{table:rows for table,rows,_ in tables},'status':'restored_and_verified'}
    finally:
        backend.unlock()
