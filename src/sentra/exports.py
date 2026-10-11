"""Explicit streaming private extracts; original API bytes are never rewritten."""
from contextlib import ExitStack, contextmanager
import csv
import gzip
import io
import os
from uuid import uuid4

from .datasets import canonical


def csv_value(value):
    if isinstance(value, (dict, list)):
        value = canonical(value)
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


class ExportBudget:
    def __init__(self, store):
        self.store, self.initial_usage, self.written = store, store.usage(), 0

    def check(self, additional):
        # The private writer lock excludes other import/export writers.
        self.store.check_capacity(self.written + additional, known_usage=self.initial_usage)


class QuotaWriter:
    """Check compressed bytes before every write; flush so usage scans see them."""
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def write(self, content):
        if not content:
            return 0
        self.budget.check(len(content))
        written = self.stream.write(content)
        self.stream.flush()
        self.budget.written += written
        return written

    def flush(self):
        self.stream.flush()


@contextmanager
def compressed_text(path, budget):
    with path.open('wb') as binary:
        with gzip.GzipFile(filename='', fileobj=QuotaWriter(binary, budget), mode='wb', compresslevel=3, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding='utf-8', newline='') as text:
                yield text
        binary.flush()
        os.fsync(binary.fileno())


@contextmanager
def export_folder(store):
    parent = store.root / 'exports' / store.connection.provider / store.connection.participant_id
    identity = str(uuid4())
    staging, final = parent / ('.partial-' + identity), parent / identity
    staging.mkdir(parents=True)
    try:
        yield staging, final
        store.check_capacity() # Reconcile actual usage before publishing.
        os.replace(staging, final)
    except Exception:
        # Only files created in this exact staging directory, never other exports.
        if not staging.resolve().is_relative_to((store.root / 'exports').resolve()):
            raise RuntimeError('Invalid export staging path') from None
        for path in staging.iterdir():
            path.unlink()
        staging.rmdir()
        raise


def export_records(store, dataset=None):
    with store.private_lock, store.lock:
        store.reload()
        budget = ExportBudget(store)
        # Discover columns without retaining health rows.
        columns = sorted({key for record in store.iter_records(dataset) for metric in record['measurements'] for key in metric})
        names = {'records': 'records.json.gz', 'measurements': 'measurements.csv.gz',
                 'sessions': 'sessions.json.gz', 'coverage': 'coverage.json.gz'}
        with export_folder(store) as (folder, final):
            with ExitStack() as stack:
                streams = {kind: stack.enter_context(compressed_text(folder / name, budget)) for kind, name in names.items()}
                streams['records'].write('[')
                streams['sessions'].write('[')
                first_record = first_session = True
                writer = csv.DictWriter(streams['measurements'], fieldnames=columns)
                writer.writeheader()
                for record in store.iter_records(dataset):
                    text = canonical(record)
                    streams['records'].write(('' if first_record else ',') + text)
                    first_record = False
                    if record['session_type']:
                        streams['sessions'].write(('' if first_session else ',') + text)
                        first_session = False
                    for metric in record['measurements']:
                        writer.writerow({k: csv_value(v) for k, v in metric.items()})
                streams['records'].write(']')
                streams['sessions'].write(']')
                streams['coverage'].write(canonical(store.status()))
        return {kind: final / name for kind, name in names.items()}


def export_originals(store):
    with store.private_lock, store.lock:
        store.reload()
        budget = ExportBudget(store)
        manifests = store.manifests()
        seen = set()
        with export_folder(store) as (folder, final):
            for manifest in manifests:
                digest = manifest['content_sha256']
                if digest in seen:
                    continue
                seen.add(digest)
                content = store.original_bytes(manifest)
                with (folder / (digest + '.json.gz')).open('wb') as binary:
                    with gzip.GzipFile(filename='', fileobj=QuotaWriter(binary, budget), mode='wb', compresslevel=3, mtime=0) as compressed:
                        compressed.write(content)
                    binary.flush()
                    os.fsync(binary.fileno())
            with compressed_text(folder / 'manifest.json.gz', budget) as stream:
                stream.write(canonical([{**m, 'export_file': m['content_sha256'] + '.json.gz'} for m in manifests]))
        return [final / (digest + '.json.gz') for digest in sorted(seen)]
