"""Restart inspection must fail closed and never renew stored credentials."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
import pytest

from sentra.providers import PROVIDERS
from sentra.errors import SentraError
from sentra.readiness import credential_check, configured_connections, inspect_readiness, run_readiness
from sentra.shared import CapacityStop, Limits


NOW = datetime(2026, 11, 3, 16, tzinfo=timezone.utc)
MISSING = object()


def envelope(provider='whoop', **changes):
    connection = {'provider': provider, 'participant_id': 'p9999', 'agreed': True,
                  'publishing_status': 'testing', 'client_id': 'example-private-id',
                  'client_secret': 'example-private-client'}
    token = {'access_token': 'example-private-access', 'refresh_token': 'example-private-refresh',
             'expires_at': NOW.timestamp() - 1, 'authorized_at': NOW.timestamp() - 86400,
             'scope': list(PROVIDERS[provider].scopes)}
    token.update(changes)
    return {'connection': connection, 'token': token}


def backend_fixture(value=None, *, control=None):
    cipher = Fernet(Fernet.generate_key())
    value = value or envelope()
    encrypted = cipher.encrypt(json.dumps(value).encode())
    statements = []

    def execute(statement, parameters=None):
        statements.append(statement)
        assert statement.lstrip().startswith('select '), 'Inspection must not update control/token/health tables'
        if 'observation_control' in statement:
            row = ({'enabled': False} if control is None else control,)
        elif 'select octet_length' in statement:
            row = (len(encrypted),)
        else:
            assert 'case when octet_length' in statement
            row = (encrypted, 'active')
        return SimpleNamespace(fetchone=lambda: row)

    backend = SimpleNamespace(
        limits=Limits(), db=SimpleNamespace(execute=execute), reserve=Mock(), close=Mock(),
        usage=Mock(return_value={'database_bytes': 310_000_000, 'object_bytes': 4_000_000,
                                 'egress_bytes': 1_000_000_000}))
    return backend, cipher, statements


def test_expired_access_is_not_confused_with_expired_refresh_authorization():
    value = envelope()
    assert credential_check(value['connection'], value['token'], 'active', NOW)['status'] == 'refresh_needed'
    value['token']['refresh_expires_at'] = NOW.timestamp()
    assert credential_check(value['connection'], value['token'], 'active', NOW)['status'] == 'refresh_authorization_expired'


def test_google_testing_deadline_is_not_extended_by_access_token_refresh():
    value = envelope('google_health', authorized_at=NOW.timestamp() - 8 * 86400,
                     expires_at=NOW.timestamp() + 3600, refresh_expires_at=NOW.timestamp() + 86400)
    assert credential_check(value['connection'], value['token'], 'active', NOW)['status'] == 'refresh_authorization_expired'
    del value['token']['refresh_expires_at']
    assert credential_check(value['connection'], value['token'], 'active', NOW)['status'] == 'refresh_authorization_expired'


@pytest.mark.parametrize('changes', [
    {'expires_at': float('nan')}, {'expires_at': True}, {'refresh_expires_at': 'unknown'},
    {'scope': ['offline']}, {'refresh_token': ''}, {'reconnect_required': True},
])
def test_invalid_or_incomplete_credentials_do_not_pass(changes):
    value = envelope(**changes)
    assert credential_check(value['connection'], value['token'], 'active', NOW)['status'] not in ('access_current', 'refresh_needed')


@pytest.mark.parametrize('status,expected', [
    ('refresh_pending', 'reconnect_required'), ('handoff_pending', 'reconnect_required'),
    ('reconnect_pending', 'reconnect_required'), ('withdrawn', 'participation_withdrawn'),
])
def test_pending_or_withdrawn_connection_requires_attention(status, expected):
    value = envelope(expires_at=NOW.timestamp() + 3600)
    assert credential_check(value['connection'], value['token'], status, NOW)['status'] == expected


@pytest.mark.parametrize('provider', ['google_health', 'whoop'])
@pytest.mark.parametrize('access_lifetime,expected', [(-1, 'refresh_needed'), (3600, 'access_current')])
def test_inspection_is_bounded_and_never_fetches_or_rotates_credentials(provider, access_lifetime, expected):
    backend, cipher, statements = backend_fixture(envelope(provider, expires_at=NOW.timestamp() + access_lifetime))
    with patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP allowed')):
        result = inspect_readiness(backend, {provider: 'p9999'}, cipher, now=NOW)
    assert result['decision'] == 'operator_review_required'
    assert result['blockers'] == []
    assert result['connections'][0]['status'] == expected
    assert result['provider_requests'] == 0
    assert result['sql_control'] == 'paused'
    assert result['operator_evidence_required']
    assert backend.reserve.call_args.args[0] >= 65_536
    assert len(statements) == 3
    encoded = json.dumps(result)
    assert 'example-private' not in encoded
    assert 'access_token' not in encoded
    assert 'refresh_token' not in encoded


@pytest.mark.parametrize('field', ['client_id', 'client_secret'])
@pytest.mark.parametrize('invalid', [
    pytest.param(MISSING, id='missing'), pytest.param(None, id='null'),
    pytest.param('', id='empty'), pytest.param(123, id='non-string'),
    pytest.param('   ', id='whitespace'),
])
@pytest.mark.parametrize('access_lifetime', [-1, 3600], ids=['expired-access', 'current-access'])
def test_invalid_client_fields_block_inspection_without_disclosing_credentials(field, invalid, access_lifetime):
    value = envelope(expires_at=NOW.timestamp() + access_lifetime)
    if invalid is MISSING:
        del value['connection'][field]
    else:
        value['connection'][field] = invalid
    backend, cipher, _ = backend_fixture(value)
    with patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP allowed')):
        result = inspect_readiness(backend, {'whoop': 'p9999'}, cipher, now=NOW)
    assert result['decision'] == 'blocked'
    assert result['blockers'] == ['connection_requires_attention']
    assert result['connections'][0]['status'] == 'credential_metadata_invalid'
    assert result['provider_requests'] == 0
    assert 'example-private' not in json.dumps(result)


def test_stale_egress_stops_before_any_control_or_credential_read():
    backend, cipher, statements = backend_fixture()
    backend.usage.side_effect = CapacityStop('example private failure')
    result = inspect_readiness(backend, {'whoop': 'p9999'}, cipher, now=NOW)
    assert result['blockers'] == ['capacity_or_egress_unavailable']
    assert not statements
    assert 'example private failure' not in json.dumps(result)


def test_capacity_stop_preserves_measurement_but_stops_further_inspection():
    backend, cipher, statements = backend_fixture()
    backend.usage.return_value['database_bytes'] = 380_000_000
    result = inspect_readiness(backend, {'whoop': 'p9999'}, cipher, now=NOW)
    assert result['decision'] == 'blocked'
    assert result['usage_bytes']['database_bytes'] == 380_000_000
    assert not statements


def test_enabled_control_is_reported_without_changing_it():
    backend, cipher, statements = backend_fixture(control={'enabled': True, 'mode': 'ongoing', 'start': '2026-11-03'})
    result = inspect_readiness(backend, {'whoop': 'p9999'}, cipher, now=NOW)
    assert result['sql_control'] == 'active'
    assert 'sql_control_not_paused' in result['blockers']


def test_mismatched_credential_identity_is_rejected_without_disclosure():
    value = envelope()
    value['connection']['participant_id'] = 'p9998'
    backend, cipher, _ = backend_fixture(value)
    result = inspect_readiness(backend, {'whoop': 'p9999'}, cipher, now=NOW)
    assert result['connections'][0]['status'] == 'credential_unreadable'
    assert 'p9998' not in json.dumps(result)


def test_configured_connections_support_multiple_participants_with_limits():
    assert configured_connections({'whoop': ['p9998', 'p9999']}) == [('p9998', 'whoop'), ('p9999', 'whoop')]
    for participants in ({}, {'whoop': ['p9999', 'p9999']}, {'whoop': ['bad']},
                         {'whoop': [f'p{i:04d}' for i in range(101)]}):
        with pytest.raises(SentraError):
            configured_connections(participants)


def test_command_encrypts_private_details_and_prints_only_aggregate_states():
    backend, token_cipher, _ = backend_fixture()
    local = Fernet(Fernet.generate_key())
    with TemporaryDirectory() as folder:
        output = io.StringIO()
        with patch('sentra.readiness.local_cipher', return_value=local), \
             patch('sentra.readiness.read_shared', return_value=({}, backend.limits, Path(folder))), \
             patch('sentra.readiness.read_setup', return_value={
                 'config': {'participants': {'whoop': 'p9999'}},
                 'token_key': 'example'}):
            with patch('sentra.readiness.Fernet', return_value=token_cipher), \
                 patch('sentra.readiness.SharedBackend', return_value=backend), redirect_stdout(output):
                run_readiness(Path('synthetic.toml'))
        saved = Path(folder, 'readiness', 'latest.enc').read_bytes()
        private = json.loads(local.decrypt(saved))
        assert private['connections'][0]['participant_id'] == 'p9999'
        assert 'p9999' not in output.getvalue()
        assert 'example-private' not in output.getvalue()
        assert b'p9999' not in saved
        backend.close.assert_called_once()
