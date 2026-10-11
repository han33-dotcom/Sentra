import secrets
import math
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit
import webbrowser

import requests
from requests_oauthlib import OAuth2Session

from .config import require_agreement
from .errors import SentraError
from .providers import PROVIDERS


class PrivateOAuthSession(OAuth2Session):
    def request(self, method, url, **kwargs):
        # fetch_token passes arbitrary kwargs into the OAuth form, not Requests.
        # Enforce redirect behavior at the actual transport boundary.
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def callback_code(target: str, expected_state: str):
    url = urlsplit(target)
    if url.path != "/callback":
        raise SentraError("Unexpected callback path.")
    query = parse_qs(url.query)
    state = query.get("state", [])
    if len(state) != 1 or not secrets.compare_digest(state[0], expected_state):
        raise SentraError("OAuth state mismatch; restart authorization.")
    if "error" in query:
        raise SentraError("Provider authorization declined or failed; restart authorization.")
    code = query.get("code", [])
    if len(code) != 1 or not code[0]:
        raise SentraError("No authorization code received.")
    return code[0]


def token_state(token, previous=None):
    previous = previous or {}
    if not token.get("access_token") or not (token.get("refresh_token") or previous.get("refresh_token")):
        raise SentraError("Background authorization requires a refresh token; reconnect with offline access.")
    try:
        lifetime = float(token["expires_in"])
        if lifetime <= 0 or not math.isfinite(lifetime):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise SentraError("Provider returned invalid token expiry; reconnect.") from None
    now = time.time()
    result = {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token") or previous["refresh_token"],
        "expires_at": now + lifetime,
        "scope": token.get("scope", previous.get("scope", [])),
        "authorized_at": previous.get("authorized_at", now),
        "updated_at": now,
        "reconnect_required": False,
    }
    if "refresh_token_expires_in" in token:
        try:
            refresh_lifetime = float(token["refresh_token_expires_in"])
            if refresh_lifetime <= 0 or not math.isfinite(refresh_lifetime):
                raise ValueError
            result["refresh_expires_at"] = now + refresh_lifetime
        except (ValueError, TypeError):
            raise SentraError("Provider returned invalid refresh expiry; reconnect.") from None
    elif "refresh_expires_at" in previous:
        result["refresh_expires_at"] = previous["refresh_expires_at"]
    return result


def authorize(connection, vault, *, timeout=300):
    with vault.lock:
        try: previous=vault.read()
        except SentraError: previous={}
        if previous.get('cloud_owned'):
            raise SentraError('Connection is cloud-managed; use cloud-connect --reauthorize for serialized reconnect.')
        return _authorize_locked(connection,vault,timeout=timeout)


def _authorize_locked(connection, vault, *, timeout=300):
    require_agreement(connection)
    provider = PROVIDERS[connection.provider]
    state = secrets.token_urlsafe(6) if connection.provider == "whoop" else secrets.token_urlsafe(32)
    session = PrivateOAuthSession(connection.client_id, scope=list(provider.scopes),
                            redirect_uri=connection.redirect_uri, state=state,
                            pkce="S256" if connection.provider == "google_health" else None)
    params = {"access_type": "offline", "prompt": "consent"} if connection.provider == "google_health" else {}
    url, _ = session.authorization_url(provider.authorization_url, **params)
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass # The callback URL contains a credential. Never log it.

        def do_GET(self):
            if urlsplit(self.path).path != "/callback":
                self.send_error(404)
                return
            try:
                received["code"] = callback_code(self.path, state)
            except SentraError as error:
                received["error"] = error
            self.send_response(200 if "code" in received else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Return to the Sentra terminal for the authorization result. You can close this tab.")

    # Keep the connection lock across authorization to avoid refresh during reconnect.
    with vault.lock:
        with HTTPServer(("127.0.0.1", 8765), Handler) as server:
            server.timeout = 1
            print("Opening the system browser. Complete participant authorization within five minutes.")
            if not webbrowser.open(url):
                raise SentraError("Cannot open system browser; configure a default browser and retry.")
            deadline = time.monotonic() + timeout
            while not received and time.monotonic() < deadline:
                server.handle_request()
        if not received:
            raise SentraError("Authorization timed out; restart authorization.")
        if "error" in received:
            raise received["error"]
        try:
            token = session.fetch_token(provider.token_url, code=received["code"],
                                        client_secret=connection.client_secret, include_client_id=True,
                                        timeout=(10, 30))
        except Exception:
            raise SentraError("Token exchange failed; check client/callback/scopes and restart authorization.") from None
        saved = token_state(token)
        if connection.provider == "google_health" and connection.publishing_status == "testing":
            saved["refresh_expires_at"] = time.time() + 7 * 86400
        vault.write(saved)


def access_token(connection, vault, *, force_refresh=False):
    require_agreement(connection)
    with vault.lock:
        previous = vault.read()
        if previous.get('cloud_owned'):
            raise SentraError('Connection is cloud-managed; use cloud collection or cloud-connect --reauthorize. Local token copy must not refresh.')
        if previous.get("reconnect_required"):
            raise SentraError("Connection requires reauthorization; run sentra authorize.")
        if previous.get("refresh_expires_at", float("inf")) <= time.time():
            raise SentraError("Refresh authorization expired; reconnect this participant.")
        if not force_refresh and previous["expires_at"] > time.time() + 60:
            return previous["access_token"]
        # Persist intent first. An interrupted/ambiguous rotation must not reuse an invalid refresh token.
        pending = dict(previous, reconnect_required=True)
        vault.write(pending)
        data = {"grant_type": "refresh_token", "refresh_token": previous["refresh_token"],
                "client_id": connection.client_id, "client_secret": connection.client_secret}
        if connection.provider == "whoop":
            data["scope"] = "offline"
        try:
            response = requests.post(PROVIDERS[connection.provider].token_url, data=data,
                                     timeout=(10, 30), allow_redirects=False)
            if response.status_code != 200:
                raise SentraError(f"Token renewal failed (HTTP {response.status_code}); reconnect. No automatic retry of rotation.")
            token = response.json()
            if connection.provider == "whoop" and not token.get("refresh_token"):
                raise SentraError("WHOOP did not return a replacement refresh token; reconnect.")
            renewed = token_state(token, previous)
            vault.write(renewed)
            return renewed["access_token"]
        except SentraError:
            raise
        except Exception:
            raise SentraError("Token renewal outcome is uncertain; reconnect before another request.") from None
