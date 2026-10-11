import argparse
from datetime import date
import json
import logging
from pathlib import Path
import sys

from filelock import Timeout

from .auth import access_token, authorize
from .config import load_connection, require_agreement
from .datasets import plan_jobs
from .local_store import LocalStore
from .collect import run_jobs
from .transport import ReadClient
from .exports import export_records, export_originals
from .errors import SentraError
from .providers import PROVIDERS
from .sample import collect_sample
from .vault import local_cipher, TokenVault
from .shared_cli import add_commands,run_command
from .recovery import key_recovery
from .cloud_cli import add_commands as add_cloud_commands,run_command as run_cloud_command
from .tiers_cli import add_commands as add_tier_commands,run_command as run_tier_command
from .processing.cli import add_commands as add_process_commands,run_command as run_process_command
import psycopg
import requests


def main(argv=None):
    # OAuth libraries can log request/response credentials at DEBUG. The CLI
    # uses only explicit sanitized status messages, regardless of root config.
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description="Sentra local wearable extraction and audit workspace")
    parser.add_argument("--config", type=Path, default=Path("config/local.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    add_commands(sub)
    add_cloud_commands(sub)
    add_tier_commands(sub)
    add_process_commands(sub)
    sub.add_parser("init-vault", help="Create encryption key in the OS credential store")
    for command in ('save-recovery-key','recover-key'):
        item=sub.add_parser(command)
        item.add_argument('file',type=Path,help='Private encrypted recovery envelope beneath .private/recovery')
    for command in ("check-config", "authorize", "sample", "refresh"):
        item = sub.add_parser(command)
        item.add_argument("provider", choices=PROVIDERS)
    item = sub.add_parser('initial-import', help='Bounded history import; resume by repeating the same dates')
    item.add_argument('provider', choices=[*PROVIDERS, 'all'])
    item.add_argument('--start', type=date.fromisoformat, help='Inclusive calendar date in Asia/Beirut; default previous 30 days')
    item.add_argument('--end', type=date.fromisoformat, help='Exclusive calendar date; default today in Asia/Beirut')
    item.add_argument('--dataset', action='append', help='Collect only named datasets; may be repeated')
    item.add_argument('--recheck', action='store_true', help='Revisit completed ranges for corrections')
    item.add_argument('--max-private-mib', type=int, default=200, help='Local private storage ceiling; default 200 MiB')
    for command in ('status', 'verify-import', 'export', 'export-originals'):
        item = sub.add_parser(command)
        item.add_argument('provider', choices=PROVIDERS)
        if command == 'export':
            item.add_argument('--dataset', help='Export one dataset, or all if omitted')
    args = parser.parse_args(argv)
    try:
        if args.command in ('save-recovery-key','recover-key'):
            connection=load_connection(args.config,'google_health',require_client=False)
            path=args.file.resolve()
            if not path.is_relative_to(connection.private_dir/'recovery'):
                raise SentraError('Keep the encrypted key envelope beneath .private/recovery.')
            key_recovery(path,save=args.command=='save-recovery-key')
            print('Recovery operation completed; key value never displayed. Keep the envelope and passphrase separately, accessible only to collector operators.')
            return 0
        if args.command.startswith('shared-'):
            return run_command(args)
        if args.command.startswith('cloud-'):
            return run_cloud_command(args)
        if args.command.startswith('tiers-'):
            return run_tier_command(args)
        if args.command.startswith('process-'):
            return run_process_command(args)
        if args.command == "init-vault":
            local_cipher(create=True)
            print("Local encryption key ready in the OS credential store; its value is never displayed.")
            return 0
        if args.command == 'initial-import':
            if not 1 <= args.max_private_mib <= 200:
                raise SentraError('Local storage ceiling must be 1–200 MiB; hosted quotas are separate Stage 3 work.')
            providers = list(PROVIDERS) if args.provider == 'all' else [args.provider]
            failed = False
            for provider in providers:
                try:
                    connection = load_connection(args.config, provider)
                    require_agreement(connection)
                    jobs = plan_jobs(provider, args.start, args.end)
                    if args.dataset:
                        selected = set(args.dataset)
                        if not selected.issubset({j.dataset for j in jobs}):
                            raise SentraError('Unknown dataset for this provider/date range; see docs/stage-2-collection.md.')
                        jobs = [j for j in jobs if j.dataset in selected]
                    cipher = local_cipher()
                    vault = TokenVault(connection.private_dir, provider, connection.participant_id, cipher)
                    store = LocalStore(connection, cipher, max_bytes=args.max_private_mib * 1024 * 1024)
                    client = ReadClient(lambda refresh=False: access_token(connection, vault, force_refresh=refresh))
                    def report(dataset, state, detail):
                        print(f'{provider} {dataset}: {state}; {detail}', flush=True)
                    result = run_jobs(store, jobs, client.fetch, recheck=args.recheck, notify=report)
                    print(json.dumps({'provider': provider, **result}), flush=True)
                    failed = failed or result['status'] != 'succeeded'
                except SentraError as error:
                    print(f'{provider}: {error}', file=sys.stderr)
                    failed = True
            return 1 if failed else 0
        connection = load_connection(args.config, args.provider)
        if args.command == "check-config":
            print("Configuration and client file valid. Participant agreement: " + ("recorded" if connection.agreed else "pending"))
            return 0
        if args.command in ('status', 'verify-import', 'export', 'export-originals'):
            require_agreement(connection)
            store = LocalStore(connection, local_cipher())
            if args.command == 'status':
                with store.lock:
                    store.reload()
                    print(json.dumps(store.status(), indent=2))
            elif args.command == 'verify-import':
                with store.lock:
                    store.reload()
                    manifests = store.manifests()
                    for manifest in manifests:
                        body = store.original_bytes(manifest)
                        payload = json.loads(body)
                        key = 'records' if connection.provider == 'whoop' else ('dataPoints' if manifest['aggregation'] == 'list' else 'rollupDataPoints')
                        if len(payload.get(key, [])) != manifest['record_count']:
                            raise SentraError('Source count mismatch; inspect private import before continuing.')
                    sources = {m['response_id'] for m in manifests}
                    if any(r['source_response_id'] not in sources for r in store.records()):
                        raise SentraError('Record source reference missing.')
                    print(f'Verified {len(manifests)} encrypted original responses, hashes, counts and record source references.')
            elif args.command == 'export':
                for kind, path in export_records(store, args.dataset).items():
                    print(f'Private {kind} extract: {path}')
            else:
                paths = export_originals(store)
                print(f'Exported {len(paths)} compressed original responses under .private/exports; sensitive files remain private.')
            return 0
        vault = TokenVault(connection.private_dir, connection.provider, connection.participant_id, local_cipher())
        if args.command == "authorize":
            authorize(connection, vault)
            print("Authorization saved encrypted. Run sample to verify actual data access.")
        elif args.command == "refresh":
            access_token(connection, vault, force_refresh=True)
            print("Refresh completed and replacement credentials persisted encrypted. Run sample again to verify renewed access.")
        else:
            evidence = collect_sample(connection, vault)
            print(f"HTTP 200; sample contains {evidence['record_count']} record(s); more pages: {evidence['more_pages']}.")
            print("Encrypted original response and manifest saved under the configured private directory.")
            if evidence["record_count"] == 0:
                print("Empty sample: authenticated request succeeded, but no measurement demonstrated in yesterday's window.")
        return 0
    except SentraError as error:
        print(str(error), file=sys.stderr)
    except Timeout:
        print("Connection is busy; wait for the other local process to finish.", file=sys.stderr)
    except (psycopg.Error, requests.RequestException):
        print('Hosted operation failed; check project status, permissions and capacity. Sensitive details omitted.',file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError):
        print("Local operation failed; check configuration, private storage permissions and callback port. Sensitive details omitted.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
