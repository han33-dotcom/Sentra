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


from .errors import SentraError
from .processing.board import BOARD_VERSION, payload
from .processing.job import runtime_config as viewer_config
from .processing.observations import devices as participant_devices, load
from .processing.pipeline import ASSESSMENT_VERSION, run
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
    # Run counters omit committed pages when a later page fails; use durable record writes.
    value = reader.db.execute('''select max(run.finished_at) from audit.collection_runs run
        where exists (select 1 from audit.records record
          where record.participant_id=run.participant_id and record.provider=run.provider
            and record.collected_at between run.started_at and run.finished_at)''').fetchone()[0]
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
    if not force:
        before = previous_board(storage) if source is not None else {}
        previous = before.get('source_run')
        # A board built under older assessment rules or an older board format (for example device
        # labels before #45) is rebuilt from existing data even without new collection data.
        current_rules = (before.get('assessment_version') == ASSESSMENT_VERSION
                         and before.get('board_version') == BOARD_VERSION)
        if source is None or (current_rules and previous and datetime.fromisoformat(source) <= datetime.fromisoformat(previous)):
            log('No changed collection data or rules since the last board; tiers not read or published.')
            return {'status': 'skipped', 'source_run': source}
    objects, report = build(reader, limits, now=now)
    # Process before publishing anything: a processing failure leaves both tiers and board unchanged.
    with tempfile.TemporaryDirectory(prefix='sentra-wellness-') as folder:
        for key, data in objects.items():
            path = Path(folder) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        devices = participant_devices(folder)
        _, daily, _, _ = run(load(folder), Path(folder) / 'processed', log=lambda *_: None, devices=devices)
    board = payload(daily, devices, built_at=now.isoformat(), source_run=source)
    body = json.dumps(board, separators=(',', ':')).encode()
    if len(body) > MAX_BOARD_BYTES:
        raise SentraError('Board payload exceeds 5 MB; narrow the history before publishing.')
    # One capacity check before any write covers the tiers, their report and the board together.
    publish(objects, report, storage, reader, limits, extra_bytes=len(body))
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
