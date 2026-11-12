"""Hosted enrollment configuration and bounded provider authentication.

Provider identities are HMACed before persistence. A verified Gmail address
is checked only when redeeming a link for a manually connected Fitbit account.
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

GOOGLE_EMAIL_SCOPE = 'https://www.googleapis.com/auth/userinfo.email'


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

    def fitbit_email_hash(self, email):
        local, _, domain = email.strip().lower().partition('@') if isinstance(email, str) else ('', '', '')
        if (domain not in ('gmail.com', 'googlemail.com') or len(local) > 64
                or not re.fullmatch(r'[a-z0-9]+(?:\.[a-z0-9]+)*', local)):
            raise EnrollmentError('Enter the verified Gmail address for the existing Fitbit connection.')
        return self.identity('fitbit-link-email', local.replace('.', '') + '@gmail.com')

    def callback(self, provider):
        return f'{self.origin}/oauth/{provider}/callback'

    @classmethod
    def from_env(cls):
        try:
            return cls(**json.loads(os.environ['SENTRA_ENROLLMENT_CONFIG']))
        except Exception:
            raise EnrollmentError('Enrollment is not configured. Contact the Sentra team.', 503) from None


def scopes(provider, *, fitbit_link=False):
    # Identity is required to prevent duplicate signup and account substitution on reconnect.
    if fitbit_link:
        if provider != 'google_health':
            raise EnrollmentError('Use the original Fitbit account for this link.', 403)
        return ['openid', GOOGLE_EMAIL_SCOPE]
    return [*PROVIDERS[provider].scopes, 'openid' if provider == 'google_health' else 'read:profile']


class ProviderLogin:
    def __init__(self, settings):
        self.settings = settings

    def begin(self, provider, *, fitbit_email_hash=None):
        c = self.settings.clients[provider]
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        session = PrivateOAuthSession(c['client_id'], scope=scopes(provider, fitbit_link=fitbit_email_hash is not None),
            redirect_uri=self.settings.callback(provider), state=state)
        params = {}
        if provider == 'google_health':
            if fitbit_email_hash is not None:
                params['prompt'] = 'select_account'
            else:
                params.update(access_type='offline', prompt='consent')
            params.update(code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),
                          code_challenge_method='S256')
        url, _ = session.authorization_url(PROVIDERS[provider].authorization_url, **params)
        session.close()
        pending = {'state': state, 'verifier': verifier, 'provider': provider, 'started': time.time()}
        if fitbit_email_hash is not None:
            pending['fitbit_email_hash'] = fitbit_email_hash
        return url, pending

    def finish(self, pending, code):
        provider = pending['provider']
        c = self.settings.clients[provider]
        expected_email = pending.get('fitbit_email_hash')
        required = scopes(provider, fitbit_link=expected_email is not None)
        session = PrivateOAuthSession(c['client_id'], scope=required,
            redirect_uri=self.settings.callback(provider))
        kwargs = {'code_verifier': pending['verifier']} if provider == 'google_health' else {}
        try:
            token = session.fetch_token(PROVIDERS[provider].token_url, code=code,
                client_secret=c['client_secret'], include_client_id=True, timeout=(10, 30), **kwargs)
            granted = token.get('scope', [])
            if isinstance(granted, str):
                granted = granted.split()
            if not set(required) <= set(granted) or token.get('token_type', '').lower() != 'bearer':
                raise ValueError
            access_token = token.get('access_token')
            if not isinstance(access_token, str) or not access_token:
                raise ValueError
            saved = None
            if expected_email is None:
                saved = token_state(token)
                if provider == 'google_health' and c['publishing_status'] == 'testing':
                    saved['refresh_expires_at'] = time.time() + 7 * 86400
            endpoint = ('https://openidconnect.googleapis.com/v1/userinfo' if provider == 'google_health'
                else 'https://api.prod.whoop.com/developer/v2/user/profile/basic')
            # No response bodies, callback URLs, passwords, names or email in logs/errors.
            with requests.get(endpoint, headers={'Authorization': 'Bearer ' + access_token},
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
            if expected_email is not None and (
                provider != 'google_health'
                or profile.get('email_verified') is not True
                or not hmac.compare_digest(expected_email, self.settings.fitbit_email_hash(profile.get('email')))
            ):
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
    from getpass import getpass, GetPassWarning
    import warnings
    from .enrollment_store import open_store
    parser = argparse.ArgumentParser(description='Manage private Sentra invitations and participation counts')
    parser.add_argument('--organization', required=True)
    parser.add_argument('--seats', type=int, choices=range(1, 101))
    parser.add_argument('--days', type=int, default=7, choices=range(1, 31))
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--summary', action='store_true', help='Read private aggregate participation counts; create no invitation')
    operation.add_argument('--link-fitbit', metavar='PARTICIPANT_ID',
                           help='Create a single-use link for an existing manually connected Fitbit participant')
    args = parser.parse_args(argv)
    if args.link_fitbit and args.seats is not None:
        parser.error('--link-fitbit links one existing participant and does not take --seats')
    try:
        settings = EnrollmentSettings.from_env()
        if args.summary:
            with open_store(settings) as store:
                result = store.summary(args.organization)
            print(json.dumps(result))
            return 0
        invite = secrets.token_urlsafe(32)
        if args.link_fitbit:
            if 'google_health' not in settings.clients:
                raise EnrollmentError('Fitbit enrollment is unavailable.')
            with warnings.catch_warnings():
                warnings.simplefilter('error', GetPassWarning)
                address = getpass('Verified Gmail address for the existing Fitbit connection: ')
            email_hash = settings.fitbit_email_hash(address)
        with open_store(settings) as store:
            if args.link_fitbit:
                store.invite_fitbit_link(digest(invite), args.organization, args.link_fitbit, email_hash, args.days)
            else:
                store.invite(digest(invite), args.organization, args.seats or 5, args.days)
        print(f'{settings.origin}/join#invite={invite}')
        return 0
    except GetPassWarning:
        print('Run this command from a private interactive terminal to enter the Gmail address.')
    except EnrollmentError as error:
        print(error)
    except Exception:
        print('Enrollment operation unavailable. Check private configuration and organization.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
