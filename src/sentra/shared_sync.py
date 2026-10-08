"""Resumable transfer of durable local imports; never refresh provider tokens here."""
import gzip
import json

from .errors import SentraError
from .shared import signature


def sync_store(store, backend, *, batch_size=100, notify=None):
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise SentraError('Shared batch size must be 1–100 records.')
    result = {'uploaded_manifests': 0, 'changed_records': 0, 'unchanged_records': 0}
    with store.private_lock, store.lock:
        store.reload()
        backend.lock()
        try:
            known = backend.manifest_ids(store.connection.provider,store.connection.participant_id) if hasattr(backend,'manifest_ids') else None
            # Durable objects precede manifests, which precede normalized source references.
            for m in store.manifests():
                if (m['response_id'] in known) if known is not None else backend.has_manifest(m['response_id']):
                    continue
                body = store.original_bytes(m) # Authenticated decryption + unchanged body hash.
                backend.put_manifest(m, gzip.compress(body, mtime=0))
                result['uploaded_manifests'] += 1
            dataset, hashes, batch = None, {}, []
            for record in store.iter_records():
                if record['dataset'] != dataset:
                    backend.put_records(batch)
                    result['changed_records'] += len(batch)
                    batch = []
                    dataset = record['dataset']
                    hashes = backend.record_hashes(record['participant_id'],record['provider'],dataset)
                    if notify:
                        notify(dataset)
                if hashes.get(record['record_key']) == signature(record):
                    result['unchanged_records'] += 1
                    continue
                batch.append(record)
                if len(batch) == batch_size:
                    backend.put_records(batch)
                    result['changed_records'] += len(batch)
                    batch = []
                    if notify and result['changed_records'] // 1000 != (result['changed_records']-batch_size) // 1000:
                        notify(f"{dataset}; {result['changed_records']} records stored")
            backend.put_records(batch)
            result['changed_records'] += len(batch)
            jobs = [json.loads(row[0]) for row in store.db.execute('select data from jobs order by key')]
            runs = [json.loads(row[0]) for row in store.db.execute('select data from runs order by key')]
            # No shared coverage is advanced if any earlier step failed.
            backend.save_state(store.connection.participant_id,store.connection.provider,jobs,runs)
            result['counts'] = backend.counts(store.connection.participant_id,store.connection.provider)
            result['usage'] = backend.usage()
            result['status'] = 'succeeded'
            return result
        finally:
            backend.unlock()


def compare_store(store, backend):
    with store.lock:
        store.reload()
        dataset, hashes, seen, metrics, sessions = None, {}, 0, 0, 0
        for record in store.iter_records():
            if record['dataset'] != dataset:
                dataset = record['dataset']
                hashes = backend.record_hashes(record['participant_id'],record['provider'],dataset)
            if hashes.get(record['record_key']) != signature(record):
                raise SentraError('Local/shared record content differs. Repeat shared-sync before claiming matching results.')
            seen += 1
            metrics += len(record['measurements'])
            sessions += bool(record['session_type'])
        counts = backend.counts(store.connection.participant_id,store.connection.provider)
        if (counts['records'],counts['measurements'],counts['sessions'],counts['raw_response_manifest']) != (
                seen,metrics,sessions,len(store.manifests())):
            raise SentraError('Local/shared counts differ; preserve both copies and inspect coverage.')
        if backend.verify_content(store.connection.participant_id,store.connection.provider) != seen:
            raise SentraError('Shared content verification incomplete.')
        backend.verify_projections(store.connection.participant_id,store.connection.provider)
        return counts
