"""One bounded page for Stage 1 authorization evidence, not a history collector."""
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

from .auth import access_token
from .errors import SentraError
from .providers import PROVIDERS
from .vault import atomic_write


def get_json(url, token, params=None):
    try:
        response = requests.get(url, params=params, headers={"Authorization": "Bearer " + token},
                                timeout=(10, 30), allow_redirects=False)
        if response.status_code != 200:
            raise SentraError(f"Sample request failed (HTTP {response.status_code}). Check account linkage/scopes or reconnect; response body omitted.")
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise SentraError("Unexpected provider response structure.")
        return parsed, response.content
    except SentraError:
        raise
    except Exception:
        raise SentraError("Sample request failed or returned invalid JSON; provider payload omitted.") from None


def collect_sample(connection, vault, *, now=None):
    token = access_token(connection, vault)
    provider = PROVIDERS[connection.provider]
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("Asia/Beirut"))
    end = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    start_text = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_text = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    identity_verified = False
    if connection.provider == "google_health":
        identity, _ = get_json("https://health.googleapis.com/v4/users/me/identity", token)
        if not identity.get("healthUserId"):
            raise SentraError("Google Health identity is not linked; sign into the Google Health app using this account.")
        identity_verified = True # Do not store/display vendor identity values.
        params = {"pageSize": 5, "filter": f'steps.interval.start_time >= "{start_text}" AND steps.interval.start_time < "{end_text}"',
                  "dataSourceFamily": "users/me/dataSourceFamilies/google-wearables"}
    else:
        params = {"limit": 1, "start": start_text, "end": end_text}
    payload, body = get_json(provider.sample_url, token, params)
    records = payload.get(provider.records_key, [])
    if not isinstance(records, list):
        raise SentraError("Unexpected provider records; no sample stored.")
    digest = hashlib.sha256(body).hexdigest()
    sample_id = str(uuid4())
    sample_dir = connection.private_dir / "samples" / connection.provider / connection.participant_id
    body_path = sample_dir / (digest + ".json.gz.enc")
    if not body_path.exists():
        atomic_write(body_path, vault.cipher.encrypt(gzip.compress(body, mtime=0)))
    evidence = {"sample_id": sample_id, "provider": connection.provider,
                "participant_id": connection.participant_id, "endpoint": provider.sample_url,
                "requested_start": start_text, "requested_end": end_text,
                "requested_page_size": 5 if connection.provider == "google_health" else 1,
                "collected_at": datetime.now(timezone.utc).isoformat(), "record_count": len(records),
                "identity_verified": identity_verified, "http_status": 200,
                "more_pages": bool(payload.get("nextPageToken") or payload.get("next_token")),
                "payload_sha256": digest, "body_file": body_path.name,
                "coverage": "sample_only", "provenance": "original_api_response"}
    atomic_write(sample_dir / (sample_id + ".manifest.json.enc"),
                 vault.cipher.encrypt(json.dumps(evidence).encode("utf-8")))
    return evidence
