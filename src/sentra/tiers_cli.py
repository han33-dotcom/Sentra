"""Operator commands for parquet tiers; no provider requests and no audit-table writes."""
import hashlib
import json
from pathlib import Path

import psycopg
from psycopg import sql

from .config import load_connection
from .errors import SentraError
from .shared_backend import PrivateStorage, connect_db
from .shared_config import read_shared
from .shared_setup import read_admin
from .tiers import DEFAULT_MAX_READ_BYTES, TIER_BUCKET, AuditReader, build, publish
from .vault import local_cipher

MIGRATION = Path(__file__).resolve().parents[2] / 'sql' / '006_parquet_tiers.sql'


def add_commands(sub):
    sub.add_parser('tiers-migrate', help='Create the private sentra-tiers bucket and its policies (admin, once)')
    p = sub.add_parser('tiers-build', help='Read audit tables as the viewer role and publish zstd parquet tiers')
    p.add_argument('--local', type=Path, help='Write tiers beneath .private instead of uploading (no object capacity used)')
    p.add_argument('--max-read-mb', type=int, default=DEFAULT_MAX_READ_BYTES // 1_000_000,
                   help='Per-run database egress cap in decimal MB; default 500')
    p.add_argument('--employees', type=int, default=10)
    p.add_argument('--days', type=int, default=30)


def migrate(private):
    db = connect_db(read_admin(private))
    try:
        content = MIGRATION.read_text(encoding='utf-8')
        digest = hashlib.sha256(content.encode()).hexdigest()
        found = db.execute('select sha256 from collector_private.schema_versions where version=%s', (MIGRATION.name,)).fetchone()
        if found:
            if found[0] != digest: raise SentraError('Installed tier migration differs; use a reviewed additive migration.')
            return 'already installed'
        if not db.execute("select 1 from collector_private.schema_versions where version='005_viewer_status.sql'").fetchone():
            raise SentraError('Deploy the Stage 5 viewer migration before parquet tiers.')
        marker = sql.SQL('insert into collector_private.schema_versions values ({},{}); commit;').format(
            sql.Literal(MIGRATION.name), sql.Literal(digest)).as_string(db)
        db.execute(content.rstrip().removesuffix('commit;') + marker)
        return 'installed'
    except psycopg.Error:
        raise SentraError('Tier migration unavailable; sensitive database details omitted.') from None
    finally:
        db.close()


def run_command(args):
    cipher = local_cipher()
    private = load_connection(args.config, 'google_health', require_client=False).private_dir
    if args.command == 'tiers-migrate':
        print('Parquet tier bucket: ' + migrate(private))
        return 0
    if not (0 < args.max_read_mb <= 2_000 and 0 < args.employees <= 1_000 and 0 < args.days <= 366):
        raise SentraError('Use a read cap of 1–2000 MB, 1–1000 employees and 1–366 days.')
    if args.local is not None and not args.local.resolve().is_relative_to(private.resolve()):
        raise SentraError('Local tiers contain health data; keep them beneath .private.')
    viewer, limits, _ = read_shared(args.config, cipher, role='viewer')
    collector, _, _ = read_shared(args.config, cipher, role='collector')
    db = connect_db(viewer)
    try:
        reader = AuditReader(db, limits, max_read_bytes=args.max_read_mb * 1_000_000)
        objects, report = build(reader, limits, employees=args.employees, period_days=args.days)
        # Writes use the collector storage account; the database side stays read-only.
        storage = PrivateStorage(collector, reader.reserve, bucket=TIER_BUCKET)
        try:
            result = publish(objects, report, storage, reader, limits, local_dir=args.local)
        finally:
            storage.session.close()
        print(json.dumps({**result, **report}, indent=2))
        return 0
    finally:
        db.close()
