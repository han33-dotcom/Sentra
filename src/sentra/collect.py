"""Independent, idempotent bounded imports. Coverage means pages traversed only."""
from datetime import datetime, timezone
from uuid import uuid4

from .errors import SentraError
from .local_store import CapacityStop
from .transport import FetchError


def run_jobs(store, jobs, fetch, *, recheck=False, notify=None):
    result = {'run_id': str(uuid4()), 'started_at': datetime.now(timezone.utc).isoformat(),
              'completed': 0, 'skipped': 0, 'failed': 0, 'capacity_stop': False}
    # Import lock is distinct from per-connection token refresh lock.
    with store.private_lock, store.lock:
        store.reload()
        for job in jobs:
            try:
                store.check_capacity()
                progress = store.progress(job)
                if progress and progress['status'] == 'complete' and not recheck:
                    result['skipped'] += 1
                    continue
                store.start_job(job, recheck=recheck)
                restarted = False
                while True:
                    store.check_capacity()
                    progress = store.progress(job)
                    if progress['pages'] >= 1000:
                        raise SentraError('Pagination safety limit reached; inspect provider response before resuming.')
                    cursor = progress['cursor']
                    try:
                        payload, body = fetch(job, cursor)
                    except FetchError as error:
                        if error.status == 400 and cursor and not restarted:
                            store.reset_cursor(job)
                            restarted = True
                            continue
                        raise
                    next_cursor = payload.get('next_token' if job.provider == 'whoop' else 'nextPageToken')
                    next_cursor = '' if next_cursor is None else next_cursor
                    if not isinstance(next_cursor, str):
                        raise SentraError('Invalid pagination token; page not checkpointed.')
                    store.save_page(job, cursor, payload, body, next_cursor)
                    if not next_cursor:
                        result['completed'] += 1
                        break
                if notify:
                    notify(job.dataset, 'complete', store.progress(job)['received'])
            except CapacityStop:
                result['capacity_stop'] = True
                break # No additional fetch or persistence after a capacity stop.
            except SentraError as error:
                result['failed'] += 1
                try:
                    store.fail_job(job, str(error))
                except SentraError:
                    result['capacity_stop'] = True
                    break
                if notify:
                    notify(job.dataset, 'failed', str(error))
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        result['status'] = 'capacity_stop' if result['capacity_stop'] else ('partial' if result['failed'] else 'succeeded')
        if not result['capacity_stop']:
            store.retire_covered_jobs(jobs)
            store.save_run(result['run_id'], {**result, 'jobs': [store.progress(j) for j in jobs]})
    return result
