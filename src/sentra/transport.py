"""Only bounded provider read operations; no secret URLs or bodies in errors."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import random
import time

import requests

from .errors import SentraError


class FetchError(SentraError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Fetch failed (HTTP {status}); check access/scopes or retry this import later. Body omitted.')


class ReadClient:
    def __init__(self, token, *, pause=time.sleep, pace=0.65, max_bytes=16 * 1024 * 1024):
        self.token = token
        self.pause = pause
        self.pace = pace
        self.max_bytes = max_bytes
        self.last_request = 0

    def fetch(self, job, cursor):
        request = job.request(cursor)
        access = self.token()
        refreshed = False
        for attempt in range(4):
            delay = self.pace - (time.monotonic() - self.last_request)
            if delay > 0:
                self.pause(delay)
            self.last_request = time.monotonic()
            try:
                with requests.request(request['method'], request['url'],
                                      headers={'Authorization': 'Bearer ' + access},
                                      params=request.get('params'), json=request.get('json'),
                                      stream=True, timeout=(10, 30), allow_redirects=False) as response:
                    status = response.status_code
                    if status == 200:
                        parts, size = [], 0
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise SentraError('Response exceeds configured size limit; reduce page size/history.')
                            parts.append(chunk)
                        body = b''.join(parts)
                        try:
                            payload = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                        except (ValueError, UnicodeError):
                            raise SentraError('Provider returned invalid JSON; body omitted.') from None
                        if not isinstance(payload, dict):
                            raise SentraError('Provider returned an unexpected page structure; body omitted.')
                        return payload, body
                    if status == 401 and not refreshed and attempt < 3:
                        access = self.token(refresh=True)
                        refreshed = True
                        continue
                    if status != 429 and not 500 <= status <= 599:
                        raise FetchError(status)
                    retry_after = response.headers.get('Retry-After')
                    wait = 2 ** attempt + random.uniform(0, 0.5)
                    if retry_after:
                        try:
                            wait = max(wait, float(retry_after))
                        except ValueError:
                            try:
                                wait = max(wait, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                            except (ValueError, TypeError, OverflowError):
                                pass
                    if not math.isfinite(wait) or wait > 30 or attempt == 3:
                        raise FetchError(status)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise SentraError('Read request timed out or connection failed after bounded retries.') from None
                wait = 2 ** attempt + random.uniform(0, 0.5)
            except requests.RequestException:
                raise SentraError('Provider read failed; sensitive transport details omitted.') from None
            self.pause(wait)
        raise SentraError('Read retry budget exhausted.')
