"""Encrypted, project-scoped resume files for a bounded local dashboard refresh."""
import base64
import hashlib
import json
from pathlib import Path

from psycopg import sql
from psycopg.adapt import Transformer
from psycopg.pq import Format

from .errors import SentraError
from .shared import CapacityStop
from .vault import atomic_write

PAGE_ROWS = 512
MAX_PAGES = 4096
PLAN_ALLOWANCE = 327_680
PAGE_OVERHEAD = 4096


def page_charge(wire_bytes):
    return (wire_bytes * 6 + 4) // 5 + PAGE_OVERHEAD


class RefreshCheckpoint:
    def __init__(self, folder, cipher, project, *, expected_sources=None, expected_objects=None):
        self.folder = Path(folder)
        self.cipher = cipher
        self.project = project
        self.expected_sources = expected_sources
        self.expected_objects = expected_objects

    def verify_plan(self, sources, published):
        if self.expected_sources is not None and sources != self.expected_sources:
            raise SentraError('Dashboard sources changed since sizing. Check the allowance again.')
        if self.expected_objects is not None and published != self.expected_objects:
            if published != self._read(['prepared', sources]):
                raise SentraError('Published dashboard tiers changed since sizing. Reconcile before resuming.')

    def record_prepared(self, sources, digests):
        self._write(['prepared', sources], digests)

    def path(self, key):
        identity = json.dumps(['dashboard-resume-v1', self.project, key], separators=(',', ':'), sort_keys=True)
        return self.folder / (hashlib.sha256(identity.encode()).hexdigest() + '.enc')

    def _read(self, key):
        path = self.path(key)
        if not path.exists():
            return None
        name, value = json.loads(self.cipher.decrypt(path.read_bytes()))
        if name != path.name:
            raise SentraError('Dashboard checkpoint identity mismatch.')
        return value

    def _write(self, key, value):
        path = self.path(key)
        payload = json.dumps([path.name, value], separators=(',', ':')).encode()
        atomic_write(path, self.cipher.encrypt(payload))

    def load(self, identity):
        saved = self._read(['group', identity])
        if saved is None:
            return None
        return {key: base64.b64decode(data, validate=True) for key, data in saved.items()}

    def save(self, identity, objects):
        self._write(['group', identity], {key: base64.b64encode(data).decode() for key, data in objects.items()})

    def read_partition(self, reader, query, values, identity):
        # One repeatable-read snapshot also supplies the source fingerprint in identity.
        # A stable order gives each page the same contents across interrupted attempts.
        reader.reserve(PLAN_ALLOWANCE)
        source = sql.SQL(query)
        description = reader.db.execute(sql.SQL('select * from ({}) q limit 0').format(source), values).description
        fields = [sql.SQL('q.{}::text').format(sql.Identifier(col.name)) for col in description]
        width = sql.SQL(' + ').join(sql.SQL('coalesce(octet_length({}),0)').format(f) for f in fields)
        order = sql.SQL('q::text collate "C"')
        plan = sql.SQL("""select count(*),sum(width) from
            (select (row_number() over(order by {})-1)/{} as page,
             {}+{} as width from ({}) q) p group by page order by page limit {}""").format(
                 order, sql.Literal(PAGE_ROWS), width, sql.Literal(64 + 4 * len(fields)), source,
                 sql.Literal(MAX_PAGES + 1))
        pages = reader.db.execute(plan, values).fetchall()
        size = sum(int(nbytes) for _, nbytes in pages)
        if len(pages) > MAX_PAGES or reader.read_bytes + size > reader.max_read_bytes:
            raise CapacityStop('Dashboard source exceeds the bounded read limit.')
        reader.read_bytes += size
        codec = Transformer.from_context(reader.db)
        loaders = [codec.get_loader(col.type_code, Format.TEXT) for col in description]
        result = []
        with reader.db.cursor(name='sentra_dashboard_pages', scrollable=True) as cursor:
            cursor.execute(sql.SQL('select {} from ({}) q order by {}').format(
                sql.SQL(',').join(fields), source, order), values)
            for index, (count, nbytes) in enumerate(pages):
                key = ['rows', identity, [(col.name, col.type_code) for col in description], PAGE_ROWS, index]
                rows = self._read(key)
                if rows is None:
                    reader.reserve(page_charge(int(nbytes)))
                    rows = cursor.fetchmany(count)
                    if len(rows) != count:
                        raise SentraError('Dashboard page row count mismatch.')
                    self._write(key, rows)
                else:
                    cursor.scroll(count, mode='relative')
                if len(rows) != count or any(len(row) != len(fields) for row in rows):
                    raise SentraError('Invalid dashboard checkpoint page.')
                result.extend(tuple(None if v is None else loader.load(v.encode('utf-8'))
                                    for loader, v in zip(loaders, row)) for row in rows)
        return result
