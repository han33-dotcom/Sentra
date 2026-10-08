"""Synthetic-only tests. No credentials or participant records."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from pglast import parse_sql
from requests_oauthlib import OAuth2Session
import requests

from sentra.auth import access_token, callback_code, token_state, PrivateOAuthSession
from sentra.config import Connection, load_connection
from sentra.errors import SentraError
from sentra.providers import PROVIDERS
from sentra.sample import collect_sample
from sentra.vault import TokenVault
from sentra.vault import local_cipher


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cipher = Fernet(Fernet.generate_key())
        self.conn = Connection("whoop", "p02", self.root, self.root / "client.json",
                               "http://localhost:8765/callback", True, "unknown", "fake-client", "fake-secret")
        self.vault = TokenVault(self.root, "whoop", "p02", self.cipher)
        self.old = token_state({"access_token": "fake-access", "refresh_token": "fake-refresh", "expires_in": 3600})
        self.vault.write(self.old)

    def tearDown(self):
        self.temp.cleanup()

    def test_callback_state_and_error_never_echo_code(self):
        self.assertEqual(callback_code("/callback?code=fake-code&state=12345678", "12345678"), "fake-code")
        for query in ("code=fake-secret&state=wrong", "code=x&state=12345678&state=12345678",
                      "error=private-description&state=12345678"):
            with self.assertRaises(SentraError) as result:
                callback_code("/callback?" + query, "12345678")
            self.assertNotIn("fake-secret", str(result.exception))
            self.assertNotIn("private-description", str(result.exception))

    def test_google_offline_scopes_and_pkce(self):
        session = OAuth2Session("fake-client", redirect_uri=self.conn.redirect_uri,
                               scope=list(PROVIDERS["google_health"].scopes), state="fake-state", pkce="S256")
        url, _ = session.authorization_url(PROVIDERS["google_health"].authorization_url,
                                           access_type="offline", prompt="consent")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(all(scope.endswith(".readonly") for scope in query["scope"][0].split()))
        self.assertNotIn("profile", query["scope"][0])

    def test_code_exchange_transport_does_not_redirect_or_leak_extra_form_parameter(self):
        scopes = list(PROVIDERS["google_health"].scopes)
        session = PrivateOAuthSession("fake-client", redirect_uri=self.conn.redirect_uri,
                                      scope=scopes, state="fake-state", pkce="S256")
        session.authorization_url(PROVIDERS["google_health"].authorization_url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"access_token": "fake-token", "refresh_token": "fake-refresh",
                                        "token_type": "Bearer", "expires_in": 3600, "scope": " ".join(scopes)}).encode()

        def send(request, **kwargs):
            response.request = request
            self.assertFalse(kwargs["allow_redirects"])
            fields = parse_qs(request.body)
            self.assertIn("code_verifier", fields)
            self.assertNotIn("allow_redirects", fields)
            return response

        with patch("requests.sessions.Session.send", side_effect=send):
            token = session.fetch_token(PROVIDERS["google_health"].token_url, code="fake-code",
                                        include_client_id=True, client_secret="fake-secret", timeout=(10, 30))
        self.assertEqual(token["refresh_token"], "fake-refresh")

    def test_encrypted_state_and_rotated_refresh_token(self):
        self.assertNotIn(b"fake-refresh", self.vault.path.read_bytes())
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}
        with patch("sentra.auth.requests.post", return_value=response) as request:
            self.assertEqual(access_token(self.conn, self.vault, force_refresh=True), "new-access")
        self.assertEqual(self.vault.read()["refresh_token"], "new-refresh")
        self.assertEqual(request.call_args.kwargs["data"]["scope"], "offline")
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_google_keeps_unrotated_refresh_and_original_deadline(self):
        renewed = token_state({"access_token": "new", "expires_in": 3600},
                              dict(self.old, refresh_expires_at=12345))
        self.assertEqual(renewed["refresh_token"], "fake-refresh")
        self.assertEqual(renewed["refresh_expires_at"], 12345)

    def test_nonfinite_expiry_is_rejected(self):
        for expiry in ("nan", "inf", -1):
            with self.assertRaises(SentraError):
                token_state({"access_token": "fake", "refresh_token": "fake", "expires_in": expiry})

    def test_two_local_process_clients_refresh_once_after_expiry(self):
        self.vault.write(dict(self.old, expires_at=0))
        second = TokenVault(self.root, "whoop", "p02", self.cipher)
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "new", "refresh_token": "replacement", "expires_in": 3600}

        def rotate(*args, **kwargs):
            time.sleep(0.03)
            return response

        with patch("sentra.auth.requests.post", side_effect=rotate) as request:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda v: access_token(self.conn, v), [self.vault, second]))
            self.assertEqual(results, ["new", "new"])
            self.assertEqual(request.call_count, 1)

    def test_ambiguous_refresh_is_not_retried(self):
        with patch("sentra.auth.requests.post", side_effect=TimeoutError) as request:
            with self.assertRaises(SentraError):
                access_token(self.conn, self.vault, force_refresh=True)
            with self.assertRaises(SentraError):
                access_token(self.conn, self.vault, force_refresh=True)
            self.assertEqual(request.call_count, 1)
        self.assertTrue(self.vault.read()["reconnect_required"])

    def test_rotated_token_persistence_failure_returns_no_access(self):
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}
        original_write = self.vault.write
        calls = []

        def fail_on_replacement(value):
            calls.append(value)
            if len(calls) == 2:
                raise SentraError("Synthetic persistence failure")
            original_write(value)

        with patch("sentra.auth.requests.post", return_value=response), patch.object(self.vault, "write", side_effect=fail_on_replacement):
            with self.assertRaises(SentraError):
                access_token(self.conn, self.vault, force_refresh=True)
        self.assertTrue(self.vault.read()["reconnect_required"])

    def test_consent_and_expired_testing_token_block_before_network(self):
        declined = Connection(**{**self.conn.__dict__, "agreed": False})
        with patch("sentra.auth.requests.post") as request:
            with self.assertRaises(SentraError):
                access_token(declined, self.vault)
            self.vault.write(dict(self.old, refresh_expires_at=0))
            with self.assertRaises(SentraError):
                access_token(self.conn, self.vault)
            request.assert_not_called()

    def test_sample_is_bounded_encrypted_and_preserves_body(self):
        body = b'{ "records": [{"id": "synthetic", "score": null}], "next_token": "synthetic-next" }'
        with patch("sentra.sample.get_json", return_value=(json.loads(body), body)) as get:
            evidence = collect_sample(self.conn, self.vault, now=datetime(2026, 10, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(evidence["requested_start"], "2026-10-05T21:00:00Z")
        self.assertEqual(evidence["requested_end"], "2026-10-06T21:00:00Z")
        self.assertEqual(get.call_args.args[2]["limit"], 1)
        self.assertTrue(evidence["more_pages"])
        self.assertEqual(evidence["coverage"], "sample_only")
        stored = self.root / "samples" / "whoop" / "p02" / evidence["body_file"]
        self.assertEqual(gzip.decompress(self.cipher.decrypt(stored.read_bytes())), body)
        self.assertNotIn(b"synthetic", stored.read_bytes())

    def test_google_sample_verifies_identity_and_uses_wearable_source(self):
        conn = Connection(**{**self.conn.__dict__, "provider": "google_health"})
        body = b'{"dataPoints": []}'
        with patch("sentra.sample.get_json", side_effect=[({"healthUserId": "synthetic-id"}, b"{}"), (json.loads(body), body)]) as get:
            evidence = collect_sample(conn, self.vault)
        self.assertTrue(evidence["identity_verified"])
        self.assertEqual(evidence["record_count"], 0)
        params = get.call_args.args[2]
        self.assertEqual(params["pageSize"], 5)
        self.assertEqual(params["dataSourceFamily"], "users/me/dataSourceFamilies/google-wearables")
        self.assertNotIn("synthetic-id", json.dumps(evidence))

    def test_configuration_requires_exact_callback_and_no_secret_repr(self):
        self.assertNotIn("fake-secret", repr(self.conn))
        config = self.root / "local.toml"
        config.write_text('private_dir="private"\n[whoop]\nparticipant_id="p02"\nclient_file="client.json"\nredirect_uri="http://evil.example/callback"\n')
        with self.assertRaises(SentraError):
            load_connection(config, "whoop", require_client=False)

    def test_plaintext_keyring_backend_is_rejected(self):
        with patch("sentra.vault.keyring.get_keyring", return_value=Mock()), patch("sentra.vault.keyring.get_password") as read:
            with self.assertRaises(SentraError):
                local_cipher(create=True)
            read.assert_not_called()

    def test_google_client_checks_project_and_callback(self):
        folder = self.root / "config"
        folder.mkdir()
        private = self.root / ".private"
        private.mkdir()
        client = {"web": {"client_id": "fake-client", "client_secret": "fake-secret", "project_id": "sentra-510913",
                          "redirect_uris": ["http://localhost:8765/callback"]}}
        client_path = private / "google-client.json"
        client_path.write_text(json.dumps(client))
        config = folder / "local.toml"
        config.write_text('private_dir="../.private"\n[google_health]\nparticipant_id="p01"\nproject_id="sentra-510913"\nclient_file="../.private/google-client.json"\nredirect_uri="http://localhost:8765/callback"\nteam_data_agreement=true\n')
        self.assertEqual(load_connection(config, "google_health").participant_id, "p01")
        client["web"]["project_id"] = "different-project"
        client_path.write_text(json.dumps(client))
        with self.assertRaises(SentraError):
            load_connection(config, "google_health")

    def test_schema_parses_and_credentials_are_separate(self):
        sql = Path("sql/001_foundation.sql").read_text(encoding="utf-8")
        self.assertGreater(len(parse_sql(sql)), 10)
        self.assertIn("create table collector_private.provider_credentials", sql)
        self.assertNotIn("access_token text", sql)


if __name__ == "__main__":
    unittest.main()
