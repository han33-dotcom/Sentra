"""Daily wellness refresh: tiers -> processing -> pseudonymous board JSON in the private tier bucket.

Runs in GitHub Actions after collection (.github/workflows/wellness.yml). Database reads use the
read-only sentra_viewer role with reserved egress; object writes use the collector storage account
and go only to `sentra-tiers`. Without changed collection data, tier reads and publication are skipped.

    python -m sentra.wellness_refresh            # skip if no new collection run
    python -m sentra.wellness_refresh --force    # rebuild anyway
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import pandas as pd

from .errors import SentraError
from .processing.board import payload
from .processing.job import runtime_config as viewer_config
from .processing.observations import load
from .processing.pipeline import run
from .shared_backend import PrivateStorage, connect_db
from .tiers import TIER_BUCKET, AuditReader, build, publish

BOARD_KEY = 'board/board.json'
MAX_BOARD_BYTES = 5_000_000


def collector_storage():
    """Only the storage account from the collector bundle; its database and tokens are not used."""
    try:
        credentials = json.loads(os.environ['SENTRA_COLLECTOR_CONFIG'])['credentials']
        url = urlsplit(credentials['url'])
        if url.scheme != 'https' or not (url.hostname or '').endswith('.supabase.co'):
            raise ValueError
        storage = {k: credentials[k] for k in ('url', 'publishable_key', 'storage_email', 'storage_password')}
        if not all(isinstance(v, str) and v for v in storage.values()):
            raise ValueError
        return storage
    except Exception:
        raise SentraError('Collector storage credentials missing or invalid; nothing published.') from None


def latest_run(reader):
    reader.reserve(16_384)
    value = reader.db.execute('''select max(finished_at) from audit.collection_runs
        where coalesce(cast(details->>'changed' as bigint),0)>0''').fetchone()[0]
    return value.isoformat() if value else None


def previous_board(storage):
    code, body = storage.request('GET', BOARD_KEY, maximum=MAX_BOARD_BYTES)
    if code != 200:
        return {}
    try:
        return json.loads(body)
    except ValueError:
        return {}


def refresh(reader, limits, storage, *, force=False, now=None, log=print):
    now = now or datetime.now(timezone.utc)
    source = latest_run(reader)
    if not force and (source is None or previous_board(storage).get('source_run') == source):
        log('No changed collection data since the last board; tiers not read or published.')
        return {'status': 'skipped', 'source_run': source}
    objects, report = build(reader, limits, now=now)
    publish(objects, report, storage, reader, limits)
    with tempfile.TemporaryDirectory(prefix='sentra-wellness-') as folder:
        for key, data in objects.items():
            path = Path(folder) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        measurements = pd.read_parquet(Path(folder) / 'measurements.parquet', columns=['participant', 'provider'])
        devices = {str(p): str(v) for p, v in measurements.drop_duplicates('participant').itertuples(index=False)}
        _, daily, _, _ = run(load(folder), Path(folder) / 'processed', log=lambda *_: None)
    board = payload(daily, devices, built_at=now.isoformat(), source_run=source)
    body = json.dumps(board, separators=(',', ':')).encode()
    if len(body) > MAX_BOARD_BYTES:
        raise SentraError('Board payload exceeds 5 MB; narrow the history before publishing.')
    limits.check(reader.usage(), object_add=len(body))
    code, _ = storage.request('POST', BOARD_KEY, data=body, maximum=65_536, upsert=True, content_type='application/json')
    if code not in (200, 201):
        raise SentraError(f'Board upload failed (HTTP {code}); tiers were published, board unchanged.')
    days = sum(len(p['days']) for p in board['people'])
    log(f'Board published: {len(board["people"])} participants, {days} days, data through {board["data_through"]}.')
    return {'status': 'published', 'participants': len(board['people']), 'days': days, 'source_run': source}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sentra daily wellness board refresh (read-only database)')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix='sentra-viewer-') as folder:
            credentials, limits = viewer_config(folder, env='SENTRA_VIEWER_CONFIG')
            with connect_db(credentials) as db, connect_db(credentials) as budget_db:
                reader = AuditReader(db, limits, budget_db=budget_db)
                storage = PrivateStorage(collector_storage(), reader.reserve, bucket=TIER_BUCKET)
                try:
                    print(json.dumps(refresh(reader, limits, storage, force=args.force)), flush=True)
                finally:
                    storage.session.close()
        return 0
    except SentraError as error:
        print(str(error), flush=True)
        return 1
    except Exception:
        print('Wellness refresh failed; sensitive details omitted. The previous board stays published.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
