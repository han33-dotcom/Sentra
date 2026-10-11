"""`sentra process-run`: tiers -> wellness features; outputs stay in a private folder."""
from pathlib import Path
import tempfile

from ..config import load_connection
from ..errors import SentraError


def add_commands(sub):
    p = sub.add_parser('process-run', help='Build v0 wellness features from parquet tiers (no provider requests)')
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--tiers', type=Path, help='Local tier folder from `tiers-build --local` (beneath .private)')
    source.add_argument('--from-bucket', action='store_true', help='Download the latest tiers with the viewer role')
    p.add_argument('--out', type=Path, default=Path('.private/processed'), help='Output folder beneath .private')


def private_path(path, private):
    resolved = path.resolve()
    if not resolved.is_relative_to(private.resolve()):
        raise SentraError('Processed wellness data stays beneath .private.')
    return resolved


def run_command(args):
    from .observations import load
    from .pipeline import run
    private = load_connection(args.config, 'google_health', require_client=False).private_dir
    out = private_path(args.out, private)
    if args.tiers is not None:
        run(load(private_path(args.tiers, private)), out)
        return 0
    from ..shared_backend import PrivateStorage, connect_db
    from ..shared_config import read_shared
    from ..tiers import TIER_BUCKET, AuditReader, fetch
    from ..vault import local_cipher
    viewer, limits, _ = read_shared(args.config, local_cipher(), role='viewer')
    db = connect_db(viewer)
    try:
        storage = PrivateStorage(viewer, AuditReader(db, limits).reserve, bucket=TIER_BUCKET)
        with tempfile.TemporaryDirectory(dir=private) as folder:
            fetch(storage, folder)
            run(load(folder), out)
        return 0
    finally:
        db.close()
