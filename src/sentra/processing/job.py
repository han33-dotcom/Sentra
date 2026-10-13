"""Container processing job: download tiers with the viewer role, process, write to a volume.

Configuration comes from SENTRA_PROCESSING_CONFIG (JSON, viewer-only credentials; same fields as
the hosted viewer's managed secrets minus the identity provider). Collector credentials are refused.

    python -m sentra.processing.job            # loop: run, then sleep SENTRA_PROCESS_INTERVAL_HOURS (default 24)
    python -m sentra.processing.job --once
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time

from ..errors import SentraError
from ..shared import Limits
from ..shared_backend import PrivateStorage, connect_db
from ..shared_config import validate_credentials
from ..tiers import TIER_BUCKET, AuditReader, fetch
from .observations import load
from .pipeline import run


def runtime_config(folder, env='SENTRA_PROCESSING_CONFIG'):
    try:
        config = json.loads(os.environ[env])
        if config.get('confirmed_free_plan') is not True:
            raise ValueError
        certificate = Path(folder) / 'supabase-ca.crt'
        certificate.write_text(config['certificate_pem'], encoding='utf-8')
        certificate.chmod(0o600)
        credentials = {k: config[k] for k in ('url', 'publishable_key', 'storage_email', 'storage_password')}
        credentials['db'] = {**config['db'], 'sslrootcert': str(certificate)}
        validate_credentials(credentials, Path(folder))
        if credentials['db']['user'].split('.')[0] != 'sentra_viewer':
            raise ValueError
        return credentials, Limits(**config['limits'])
    except Exception:
        raise SentraError('Processing configuration missing or invalid (viewer-only credentials required).') from None


def once(out):
    with tempfile.TemporaryDirectory(prefix='sentra-processing-') as folder:
        credentials, limits = runtime_config(folder)
        db = connect_db(credentials)
        try:
            storage = PrivateStorage(credentials, AuditReader(db, limits).reserve, bucket=TIER_BUCKET)
            tiers = Path(folder) / 'tiers'
            report = fetch(storage, tiers)
            run(load(tiers), out)
            print(f'processed tiers built at {report.get("built_at")}', flush=True)
        finally:
            db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sentra processing job (read-only)')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--out', type=Path, default=Path(os.environ.get('SENTRA_PROCESSED_DIR', '/data/processed')))
    args = parser.parse_args(argv)
    hours = float(os.environ.get('SENTRA_PROCESS_INTERVAL_HOURS', '24'))
    if not 1 <= hours <= 168:
        raise SystemExit('SENTRA_PROCESS_INTERVAL_HOURS must be 1-168.')
    while True:
        try:
            once(args.out)
            status = 0
        except SentraError as error:
            print(str(error), flush=True)
            status = 1
        except Exception:
            print('Processing failed; sensitive details omitted. Previous outputs retained.', flush=True)
            status = 1
        if args.once:
            return status
        time.sleep(hours * 3600)


if __name__ == '__main__':
    raise SystemExit(main())
