"""Hosted enrollment configuration and bounded provider authentication.

Provider identities are HMACed before persistence. Names and email addresses from
the WHOOP profile response are discarded; neither is needed to join Sentra.
"""
from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
import requests

from .auth import PrivateOAuthSession, token_state
from .errors import SentraError
from .providers import PROVIDERS


class EnrollmentError(SentraError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class EnrollmentSettings:
    origin: str
    db: dict = field(repr=False)
    token_key: str = field(repr=False)
    identity_key: str = field(repr=False)
    clients: dict = field(repr=False)
    consent_version: str = '1.0'

    def __post_init__(self):
        url = urlsplit(self.origin)
        local = url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')
        if (not (url.scheme == 'https' or local) or not url.hostname or url.username
                or url.password or url.path or url.query or url.fragment):
            raise ValueError('Use an HTTPS origin without a path (loopback HTTP only for development).')
        Fernet(self.token_key.encode())
        if len(self.identity_key) < 32 or not re.fullmatch(r'[0-9]+\.[0-9]+', self.consent_version):
            raise ValueError('Invalid enrollment keys or consent version.')
        if not self.clients or not set(self.clients) <= set(PROVIDERS):
            raise ValueError('No supported enrollment clients configured.')
        for provider, client in self.clients.items():
            if not all(isinstance(client.get(k), str) and client[k] for k in ('client_id', 'client_secret')):
                raise ValueError('Missing provider client configuration.')
            if provider == 'google_health' and client.get('publishing_status') not in ('testing', 'production'):
                raise ValueError('Declare Google publishing_status testing or production.')

    @property
    def secure(self):
        return self.origin.startswith('https://')

    @property
    def cookie(self):
        return '__Host-sentra-participant' if self.secure else 'sentra-participant-dev'

    @property
    def cipher(self):
        return Fernet(self.token_key.encode())

    def identity(self, provider, subject):
        return hmac.new(self.identity_key.encode(), f'{provider}/{subject}'.encode(), hashlib.sha256).hexdigest()

    def callback(self, provider):
        return f'{self.origin}/oauth/{provider}/callback'

    @classmethod
    def from_env(cls):
        try:
            return cls(**json.loads(os.environ['SENTRA_ENROLLMENT_CONFIG']))
        except Exception:
            raise EnrollmentError('Enrollment is not configured. Contact the Sentra team.', 503) from None


def scopes(provider):
    # Identity is required to prevent duplicate signup and account substitution on reconnect.
    return [*PROVIDERS[provider].scopes, 'openid' if provider == 'google_health' else 'read:profile']


class ProviderLogin:
    def __init__(self, settings):
        self.settings = settings

    def begin(self, provider):
        c = self.settings.clients[provider]
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        session = PrivateOAuthSession(c['client_id'], scope=scopes(provider),
            redirect_uri=self.settings.callback(provider), state=state)
        params = {'access_type': 'offline', 'prompt': 'consent'} if provider == 'google_health' else {}
        if provider == 'google_health':
            params.update(code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),
                          code_challenge_method='S256')
        url, _ = session.authorization_url(PROVIDERS[provider].authorization_url, **params)
        session.close()
        return url, {'state': state, 'verifier': verifier, 'provider': provider, 'started': time.time()}

    def finish(self, pending, code):
        provider = pending['provider']
        c = self.settings.clients[provider]
        session = PrivateOAuthSession(c['client_id'], scope=scopes(provider),
            redirect_uri=self.settings.callback(provider))
        kwargs = {'code_verifier': pending['verifier']} if provider == 'google_health' else {}
        try:
            token = session.fetch_token(PROVIDERS[provider].token_url, code=code,
                client_secret=c['client_secret'], include_client_id=True, timeout=(10, 30), **kwargs)
            granted = token.get('scope', [])
            if isinstance(granted, str):
                granted = granted.split()
            if not set(scopes(provider)) <= set(granted) or token.get('token_type', '').lower() != 'bearer':
                raise ValueError
            saved = token_state(token)
            if provider == 'google_health' and c['publishing_status'] == 'testing':
                saved['refresh_expires_at'] = time.time() + 7 * 86400
            endpoint = ('https://openidconnect.googleapis.com/v1/userinfo' if provider == 'google_health'
                else 'https://api.prod.whoop.com/developer/v2/user/profile/basic')
            # No response bodies, callback URLs, passwords, names or email in logs/errors.
            with requests.get(endpoint, headers={'Authorization': 'Bearer ' + saved['access_token']},
                    timeout=(10, 30), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ValueError
                body = bytearray()
                for chunk in response.iter_content(4096):
                    body.extend(chunk)
                    if len(body) > 32768:
                        raise ValueError
                profile = json.loads(body)
            subject = profile.get('sub') if provider == 'google_health' else profile.get('user_id')
            if isinstance(subject, bool) or not isinstance(subject, (str, int)) or not 0 < len(str(subject)) <= 255:
                raise ValueError
            return self.settings.identity(provider, str(subject)), saved
        except Exception:
            raise EnrollmentError('Connection could not be completed. Please connect again.', 400) from None
        finally:
            session.close()

    def envelope(self, provider, pid, token):
        c = self.settings.clients[provider]
        connection = {**c, 'provider': provider, 'participant_id': pid, 'agreed': True,
                      'redirect_uri': self.settings.callback(provider)}
        return self.settings.cipher.encrypt(json.dumps({'connection': connection, 'token': token}).encode())


def main(argv=None):
    """Private operator invitations and bounded counts; never a public admin API."""
    import argparse
    from .enrollment_store import open_store
    parser = argparse.ArgumentParser(description='Manage private Sentra invitations and participation counts')
    parser.add_argument('--organization', required=True)
    parser.add_argument('--seats', type=int, default=5, choices=range(1, 101))
    parser.add_argument('--days', type=int, default=7, choices=range(1, 31))
    parser.add_argument('--summary', action='store_true', help='Read private aggregate participation counts; create no invitation')
    args = parser.parse_args(argv)
    try:
        settings = EnrollmentSettings.from_env()
        if args.summary:
            with open_store(settings) as store:
                result = store.summary(args.organization)
            print(json.dumps(result))
            return 0
        invite = secrets.token_urlsafe(32)
        with open_store(settings) as store:
            store.invite(digest(invite), args.organization, args.seats, args.days)
        print(f'{settings.origin}/join#invite={invite}')
        return 0
    except Exception:
        print('Enrollment operation unavailable. Check private configuration and organization.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
