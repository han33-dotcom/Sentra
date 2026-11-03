"""Bounded operator inspection; never refreshes tokens or calls a wearable API."""
from collections import Counter
from datetime import datetime, timezone
import json
import math
import re

from cryptography.fernet import Fernet

from .cloud_setup import read_setup
from .daily_plan import collection_day, window_status
from .errors import SentraError
from .providers import PROVIDERS
from .shared import CapacityStop
from .shared_backend import SharedBackend
from .shared_config import read_shared
from .vault import atomic_write, local_cipher


def _timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError
    return value


def credential_check(connection, token, refresh_status, now):
    """Only return allowlisted metadata, never token/client values or provider errors."""
    result = {'status': 'reconnect_required', 'live_authorization': 'unverified'}
    if refresh_status == 'withdrawn':
        return {**result, 'status': 'participation_withdrawn'}
    if refresh_status != 'active' or token.get('reconnect_required'):
        return result
    if connection.get('agreed') is not True:
        return {**result, 'status': 'agreement_missing'}
    try:
        if not all(isinstance(token.get(k), str) and token[k] for k in ('access_token', 'refresh_token')):
            raise ValueError
        expires = _timestamp(token['expires_at'])
        deadline = _timestamp(token['refresh_expires_at']) if 'refresh_expires_at' in token else None
        provider = connection['provider']
        if provider == 'google_health':
            publishing = connection.get('publishing_status')
            result['publishing_status'] = publishing if publishing in ('testing', 'production') else 'unknown'
            if publishing not in ('testing', 'production'):
                return {**result, 'status': 'publishing_status_unknown'}
            if publishing == 'testing':
                # A missing explicit expiry cannot turn Testing into indefinite authorization.
                testing_end = _timestamp(token['authorized_at']) + 7 * 86400
                deadline = min(deadline, testing_end) if deadline is not None else testing_end
        scopes = token.get('scope', [])
        if isinstance(scopes, str):
            scopes = scopes.split()
        if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes):
            raise ValueError
        if not set(PROVIDERS[provider].scopes).issubset(scopes):
            return {**result, 'status': 'required_scopes_missing'}
        if deadline is not None:
            result['refresh_deadline_utc'] = datetime.fromtimestamp(deadline, timezone.utc).isoformat()
            if deadline <= now.timestamp():
                return {**result, 'status': 'refresh_authorization_expired'}
        return {**result, 'status': 'refresh_needed' if expires <= now.timestamp() + 60 else 'access_current'}
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return {**result, 'status': 'credential_metadata_invalid'}


def configured_connections(participants):
    """Accept legacy provider mappings and #28's explicit per-provider lists."""
    if not isinstance(participants, dict) or not participants:
        raise SentraError('No configured cloud connections; inspect operator setup.')
    result = []
    for provider, ids in participants.items():
        if provider not in PROVIDERS:
            raise SentraError('Invalid configured provider; inspect operator setup.')
        ids = [ids] if isinstance(ids, str) else ids
        if not isinstance(ids, list) or not ids:
            raise SentraError('Invalid configured participants; inspect operator setup.')
        for pid in ids:
            if not isinstance(pid, str) or not re.fullmatch(r'p[0-9]{2,4}', pid):
                raise SentraError('Invalid configured participant; inspect operator setup.')
            result.append((pid, provider))
    if len(result) > 100 or len(set(result)) != len(result):
        raise SentraError('Readiness inspection requires 1–100 distinct configured connections.')
    return result


def inspect_readiness(backend, participants, token_cipher, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise SentraError('Readiness clock must include a timezone.')
    connections = configured_connections(participants)
    report = {
        'checked_at_utc': now.astimezone(timezone.utc).isoformat(),
        'beirut_date': collection_day(now).isoformat(),
        'decision': 'blocked',
        'scope': 'explicitly configured cloud connections; enrolled-connection discovery not inspected',
        'provider_requests': 0,
        'blockers': [],
        'connections': [],
        'operator_evidence_required': [
            'Current provider dashboard quotas, publication/test-user eligibility and live authorization',
            'Current Supabase Free, organization egress and GitHub Actions zero-spend controls',
            'Participation approval (#26/#27) and storage/backup/recovery/capacity evidence (#29/#30/#46/#50)',
            'Agreed forward/catch-up dates and explicit restart authorization; human acceptance of #44',
        ],
    }
    try:
        report['usage_bytes'] = backend.usage()
        backend.limits.check(report['usage_bytes'])
        # Bound response allowance before reading control/credential metadata. No health rows.
        backend.reserve(131_072 + len(connections) * 65_536)
    except CapacityStop:
        report['blockers'].append('capacity_or_egress_unavailable')
        return report
    control = backend.db.execute(
        'select settings from collector_private.observation_control where singleton').fetchone()
    try:
        report['sql_control'] = window_status(control[0], collection_day(now)) if control else 'missing'
    except (SentraError, AttributeError, TypeError):
        report['sql_control'] = 'invalid'
    if report['sql_control'] != 'paused':
        report['blockers'].append('sql_control_not_paused')
    for pid, provider in connections:
        # Do not fetch an unexpectedly large encrypted envelope into an unbounded report.
        size = backend.db.execute('''select octet_length(encrypted_token_bundle)
            from collector_private.provider_credentials where participant_id=%s and provider=%s''',
            (pid, provider)).fetchone()
        if not size:
            check = {'status': 'connection_missing', 'live_authorization': 'unverified'}
        elif size[0] > 65_536:
            check = {'status': 'credential_envelope_too_large', 'live_authorization': 'unverified'}
        else:
            try:
                # Check length and decrypt within the same bounded SELECT, even during a rotation.
                row = backend.db.execute('''select case when octet_length(encrypted_token_bundle)<=65536
                    then encrypted_token_bundle end, refresh_status
                    from collector_private.provider_credentials where participant_id=%s and provider=%s''',
                    (pid, provider)).fetchone()
                if not row or row[0] is None:
                    raise SentraError('Credential state changed during inspection.')
                value = json.loads(token_cipher.decrypt(bytes(row[0])))
                c, token = value['connection'], value['token']
                if c['provider'] != provider or c['participant_id'] != pid or not isinstance(token, dict):
                    raise ValueError
                check = credential_check(c, token, row[1], now)
            except Exception:
                # No exception message, ciphertext or provider payload enters the report.
                check = {'status': 'credential_unreadable', 'live_authorization': 'unverified'}
        report['connections'].append({'participant_id': pid, 'provider': provider, **check})
        if check['status'] not in ('access_current', 'refresh_needed'):
            report['blockers'].append('connection_requires_attention')
    report['blockers'] = sorted(set(report['blockers']))
    if not report['blockers']:
        report['decision'] = 'operator_review_required'
    return report


def run_readiness(config):
    cipher = local_cipher()
    credentials, limits, private = read_shared(config, cipher)
    setup = read_setup(config, cipher)
    backend = SharedBackend(credentials, limits)
    try:
        report = inspect_readiness(backend, setup['config']['participants'], Fernet(setup['token_key'].encode()))
    finally:
        backend.close()
    atomic_write(private / 'readiness' / 'latest.enc', cipher.encrypt(json.dumps(report).encode()))
    summary = {k: report[k] for k in ('checked_at_utc', 'decision', 'provider_requests', 'blockers')}
    for name in ('usage_bytes', 'sql_control'):
        if name in report:
            summary[name] = report[name]
    summary['credential_states'] = dict(Counter(c['status'] for c in report['connections']))
    summary['private_report'] = '.private/readiness/latest.enc'
    summary['restart_authorization'] = 'not granted by this command; operator evidence still required'
    print(json.dumps(summary, indent=2))
    return 1 if report['blockers'] else 0
