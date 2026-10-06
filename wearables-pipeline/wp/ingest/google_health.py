"""Google Health API client (v4) for our ONE team OAuth client.

Every person (Mohamad, a friend, later workers) connects once in the browser;
we keep their refresh token and pull their data on a schedule.
Docs: https://developers.google.com/health/reference/rest
"""
import json
import time
from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from .. import config

API = "https://health.googleapis.com/v4/users/me/dataTypes/{dt}/dataPoints"

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
]

# data type id -> record kind (decides the filter field). From the Data Types reference.
DATA_TYPES = {
    "heart-rate": "sample",
    "heart-rate-variability": "sample",
    "oxygen-saturation": "sample",
    "respiratory-rate-sleep-summary": "sample",
    "steps": "interval",
    "active-zone-minutes": "interval",
    "sedentary-period": "interval",
    "activity-level": "interval",
    "sleep": "session",
    "exercise": "session",
    "daily-resting-heart-rate": "daily",
    "daily-heart-rate-variability": "daily",
    "daily-oxygen-saturation": "daily",
    "daily-respiratory-rate": "daily",
    "daily-sleep-temperature-derivations": "daily",
}

PAGE_SIZE = {"sample": 10000, "interval": 10000, "daily": 1000, "session": 25}


class NeedsReconnect(Exception):
    """Refresh token expired/revoked (Testing-mode tokens die after 7 days)."""


def camel(dt: str) -> str:
    head, *rest = dt.split("-")
    return head + "".join(w.capitalize() for w in rest)


def snake(dt: str) -> str:
    return dt.replace("-", "_")


# ---------------------------------------------------------------- auth ------
def token_path(label):
    return config.TOKENS_DIR / f"{label}.json"


def _client_info():
    if not config.CLIENT_SECRET.exists():
        raise SystemExit(f"Missing {config.CLIENT_SECRET}. Put the OAuth client JSON from Google Cloud there.")
    raw = json.loads(config.CLIENT_SECRET.read_text())
    kind = "web" if "web" in raw else "installed"
    return kind, raw[kind]


def auth_link(label: str, email: str | None = None) -> str:
    """The consent link for one person. `email` pre-selects their Google account."""
    from urllib.parse import urlencode
    kind, c = _client_info()
    redirect = (c.get("redirect_uris") or ["https://www.google.com"])[0]
    q = {"client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
         "access_type": "offline", "prompt": "consent", "scope": " ".join(SCOPES), "state": label}
    if email:
        q["login_hint"] = email
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(q)


def connect_account(label: str, code: str | None = None, email: str | None = None):
    """One-time consent for one person (repeat weekly while the app is in Testing mode).
    Web client with redirect https://www.google.com (our setup): open the link, tap Allow, and give
    back the google.com address you land on (it contains ?code=...), either pasted when asked or
    with --code. The code works once and only for a few minutes.
    A Desktop ("installed") client opens the browser and needs no pasting."""
    import requests
    from urllib.parse import parse_qs, urlparse

    config.ensure_dirs()
    kind, c = _client_info()
    if kind == "installed":
        from google_auth_oauthlib.flow import InstalledAppFlow
        creds = InstalledAppFlow.from_client_secrets_file(str(config.CLIENT_SECRET), SCOPES).run_local_server(
            port=0, access_type="offline", prompt="consent")
        info = json.loads(creds.to_json())
    else:
        redirect = (c.get("redirect_uris") or ["https://www.google.com"])[0]
        if not code:
            print(f"\n1) Open this link signed in as {label}'s Google account, tap Allow:\n\n{auth_link(label, email)}\n")
            code = input("2) Paste the full address you landed on (or just the code): ").strip()
        code = parse_qs(urlparse(code).query).get("code", [code])[0]
        r = requests.post(c["token_uri"], data={"code": code, "client_id": c["client_id"],
                                                "client_secret": c["client_secret"], "redirect_uri": redirect,
                                                "grant_type": "authorization_code"}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"Token exchange failed: {r.text}")
        t = r.json()
        info = {"token": t["access_token"], "refresh_token": t.get("refresh_token"), "token_uri": c["token_uri"],
                "client_id": c["client_id"], "client_secret": c["client_secret"], "scopes": t.get("scope", "").split()}
        if t.get("refresh_token_expires_in"):
            # Testing-mode apps get refresh tokens that die after 7 days; remember when
            info["refresh_expires_at"] = (utcnow().timestamp() + int(t["refresh_token_expires_in"]))
    token_path(label).write_text(json.dumps(info))
    return info


def refresh_expires_at(label):
    p = token_path(label)
    return json.loads(p.read_text()).get("refresh_expires_at") if p.exists() else None


def load_credentials(label: str) -> Credentials:
    p = token_path(label)
    if not p.exists():
        raise NeedsReconnect(f"No token for '{label}'. Run: python -m wp connect {label}")
    info = json.loads(p.read_text())
    creds = Credentials.from_authorized_user_info(info)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise NeedsReconnect(f"Token for '{label}' expired or was revoked: {e}") from e
        info.update(json.loads(creds.to_json()))
        p.write_text(json.dumps(info))
    return creds


# ---------------------------------------------------------------- reads -----
def _candidates(dt, t0: datetime, t1: datetime):
    """Filter shapes to try, most likely first. Field naming is not documented per type, so we try
    a few and remember the one that works (learned from the first extraction run)."""
    kind, out = DATA_TYPES[dt], []
    iso0, iso1 = f"{t0:%Y-%m-%dT%H:%M:%SZ}", f"{t1:%Y-%m-%dT%H:%M:%SZ}"
    civ0, civ1 = f"{t0:%Y-%m-%dT%H:%M:%S}", f"{t1:%Y-%m-%dT%H:%M:%S}"
    from datetime import timedelta
    # day-level bounds padded by a day each side: a same-day range ("date >= X AND date < X") is rejected
    d0, d1 = f"{t0 - timedelta(days=1):%Y-%m-%d}", f"{t1 + timedelta(days=1):%Y-%m-%d}"
    for f in (snake(dt), camel(dt)):
        if kind == "sample":
            out += [f'{f}.sample_time.physical_time >= "{iso0}" AND {f}.sample_time.physical_time < "{iso1}"',
                    f'{f}.sample_time.civil_time >= "{civ0}" AND {f}.sample_time.civil_time < "{civ1}"']
        elif kind == "interval":
            out += [f'{f}.interval.start_time >= "{iso0}" AND {f}.interval.start_time < "{iso1}"',
                    f'{f}.interval.civil_start_time >= "{civ0}" AND {f}.interval.civil_start_time < "{civ1}"']
        elif kind == "daily":
            out += [f'{f}.date >= "{d0}" AND {f}.date < "{d1}"',
                    f'{f}.civil_date >= "{d0}" AND {f}.civil_date < "{d1}"']
        else:  # session (sleep, exercise): physical time works for sleep; civil time for exercise
            out += [f'{f}.interval.start_time >= "{iso0}" AND {f}.interval.start_time < "{iso1}"',
                    f'{f}.interval.civil_start_time >= "{civ0}" AND {f}.interval.civil_start_time < "{civ1}"',
                    f'{f}.interval.civil_start_time >= "{d0}"']
    if kind in ("daily", "session"):
        out.append(None)   # small types: fall back to an unfiltered read (what the first extractor did for sleep)
    return out


class SkipType(Exception):
    """Scope not granted or type not available for this account."""


class GoogleHealthClient:
    _working = {}   # data type -> index of the filter shape that worked

    def __init__(self, label: str, http=None):
        self.label = label
        self.http = http or AuthorizedSession(load_credentials(label))

    def list_points(self, dt: str, since: datetime, until: datetime | None = None):
        """Yields every point of `dt` in [since, until). Dense types are read one day at a time so a
        single query never gets huge (heart rate is ~40k points/day). No silent page cap."""
        from datetime import timedelta
        until = until or utcnow()
        step = timedelta(days=1) if DATA_TYPES[dt] in ("sample", "interval") else (until - since)
        t0, ok, errors = since, 0, []
        while t0 < until:
            t1 = min(until, t0 + step)
            try:
                yield from self._window(dt, t0, t1)
                ok += 1
            except RuntimeError as e:     # e.g. INVALID_TIME_RANGE for days the API won't serve: skip the day
                errors.append(f"{t0:%Y-%m-%d}: {e}")
            t0 = t1
        if errors and not ok:
            raise RuntimeError(errors[-1])

    def _window(self, dt, t0, t1):
        url = API.format(dt=dt)
        cands = _candidates(dt, t0, t1)
        known = self._working.get(dt)
        order = [known] + [i for i in range(len(cands)) if i != known] if known is not None else range(len(cands))
        last = None
        for i in order:
            params = {"pageSize": PAGE_SIZE[DATA_TYPES[dt]]}
            if cands[i] is not None:
                params["filter"] = cands[i]
            r = self._get(url, params)
            if r.status_code == 400:
                last = r.text[:200]
                continue
            self._check(r)
            self._working[dt] = i
            while True:
                body = r.json()
                yield from body.get("dataPoints", [])
                tok = body.get("nextPageToken")
                if not tok:
                    return
                params["pageToken"] = tok
                r = self._get(url, params)
                self._check(r)
        raise RuntimeError(f"no filter shape accepted for {dt}: {last}")

    @staticmethod
    def _check(r):
        if r.status_code == 401:
            raise NeedsReconnect("401 unauthorized")
        if r.status_code in (403, 404):
            raise SkipType(f"HTTP {r.status_code}")
        r.raise_for_status()

    def _get(self, url, params, tries=5):
        for i in range(tries):
            try:
                r = self.http.get(url, params=params, timeout=180)
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(2 ** i)
                continue
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
            time.sleep(min(60, 2 ** i))      # back off on rate limits / server errors
        return r


def utcnow():
    return datetime.now(timezone.utc)
