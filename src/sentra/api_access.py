"""Individual API credentials and fresh, bounded organization policy reads.

Bearer credentials authenticate an operator-verified account, never a client-supplied
organization. Only their SHA-256 digests are stored in the private credential file.
Roles and consent come from the database on every request, not from that file.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import time

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException

from .access import resolve
from .errors import SentraError
from .processing.job import runtime_config
from .viewer_reader import ViewerReader

MAX_CREDENTIAL_BYTES = 65_536
MAX_CONSENTS = 1000
POLICY_ALLOWANCE = 589_824  # bounded users + 1001 consent rows, including protocol overhead


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def bearer_email(authorization):
    if not isinstance(authorization, str) or not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43,128}', authorization):
        raise HTTPException(401, 'Missing or invalid organization credential')
    try:
        # Reopen each request: removing a digest revokes it without an access cache.
        with Path(os.environ['SENTRA_API_ORG_CREDENTIALS_FILE']).open('rb') as stream:
            raw = stream.read(MAX_CREDENTIAL_BYTES + 1)
        if len(raw) > MAX_CREDENTIAL_BYTES:
            raise ValueError
        credentials = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(credentials, dict) or len(credentials) > 100:
            raise ValueError
        for digest, entry in credentials.items():
            if (not re.fullmatch(r'[a-f0-9]{64}', digest) or not isinstance(entry, dict)
                    or set(entry) != {'email', 'expires_at'}
                    or not isinstance(entry['email'], str)
                    or not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,190}', entry['email'])
                    or type(entry['expires_at']) is not int):
                raise ValueError
    except (OSError, KeyError, ValueError, TypeError):
        raise HTTPException(503, 'Organization API authentication is unavailable') from None
    supplied = hashlib.sha256(authorization[7:].encode('ascii')).hexdigest()
    for digest, entry in credentials.items():
        if hmac.compare_digest(supplied, digest) and entry['expires_at'] > time.time():
            return entry['email'].strip().lower()
    raise HTTPException(401, 'Missing or invalid organization credential')


def read_policy(db, email):
    """One consistent read-only snapshot; never return other organizations' consent."""
    with db.transaction():
        db.execute('set transaction isolation level repeatable read, read only')
        with db.cursor(row_factory=dict_row) as cursor:
            users = cursor.execute('''select org_id,email,role,active from org.org_users
                where email=%s and active limit 3''', (email,)).fetchall()
            # Resolve before reading participant policy; ambiguous/inactive users fail closed.
            decision = resolve(email, team_emails=(), org_users=users)
            consents = cursor.execute('''select participant_id,org_id,sharing,withdrawn,
                membership_open,demonstration from org.current_consent
                where org_id=%s limit %s''', (decision.org_id, MAX_CONSENTS + 1)).fetchall()
            if len(consents) > MAX_CONSENTS:
                raise SentraError('Organization policy exceeds the bounded size.')
            return resolve(email, team_emails=(), org_users=users, consents=consents)


def organization_access(email):
    try:
        with tempfile.TemporaryDirectory(prefix='sentra-api-') as folder:
            credentials, limits = runtime_config(folder, env='SENTRA_API_ORG_CONFIG')
            reader = ViewerReader(credentials, limits, lambda: email)
            try:
                # Persist the conservative reservation before opening the read snapshot.
                reader.reserve(POLICY_ALLOWANCE)
                return read_policy(reader.db, email)
            finally:
                reader.close()
    except SentraError as error:
        from .access import DENIED
        if str(error) == DENIED:
            raise HTTPException(403, 'Organization access denied') from None
        raise HTTPException(503, 'Organization policy is unavailable; access denied') from None
    except psycopg.Error:
        raise HTTPException(503, 'Organization policy is unavailable; access denied') from None
