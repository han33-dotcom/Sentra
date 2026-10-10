"""Pure viewer authorization, filter, audit and export contracts."""
import base64
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import html
import io
import math
import re
import time as clock
from zoneinfo import ZoneInfo

from .errors import SentraError
from .exports import csv_value

BEIRUT = ZoneInfo('Asia/Beirut')
MAX_ROWS = 10_000
MAX_BYTES = 20_000_000
MEASUREMENT_COLUMNS = ('participant_id','provider','dataset','record_key','metric','value','unit',
    'vendor_value','vendor_unit','value_kind','availability','measured_at','interval_start','interval_end',
    'civil_date','timestamp_basis','vendor_time','collected_at','resolution_seconds','resolution_description',
    'source_response_id','source_pointer','provisional','score_state')


def authorize(claims, allowed_emails, *, now=None):
    """Claims are supplied by Streamlit's verified OIDC cookie, never query input."""
    try:
        email = claims.get('email','').strip().lower()
        allowed = {item.strip().lower() for item in allowed_emails}
        expiry = claims.get('exp')
        if (claims.get('is_logged_in') is not True or claims.get('email_verified') is not True
                or claims.get('iss') not in ('https://accounts.google.com','accounts.google.com')
                or not email or email not in allowed or type(expiry) not in (int,float)
                or not math.isfinite(expiry) or expiry <= (clock.time() if now is None else now)):
            raise ValueError
        return email
    except (ValueError,TypeError,AttributeError):
        raise SentraError('Access restricted to authorized team accounts. Sign in again if your session expired.') from None


@dataclass(frozen=True)
class Selection:
    participant: str
    provider: str
    dataset: str
    start: date
    end: date
    metric: str = ''
    search: str = ''

    def __post_init__(self):
        if (not re.fullmatch(r'p[0-9]{2,4}',self.participant)
                or self.provider not in ('google_health','whoop','fitbit_export')
                or not isinstance(self.dataset,str) or not 1 <= len(self.dataset) <= 100
                or type(self.start) is not date or type(self.end) is not date
                or not 0 < (self.end-self.start).days <= 31
                or not isinstance(self.metric,str) or len(self.metric)>512
                or not isinstance(self.search,str) or len(self.search)>100):
            raise SentraError('Choose one participant, provider and dataset, and a date range of 1–31 days.')

    @property
    def start_utc(self):
        return datetime.combine(self.start,time.min,BEIRUT).astimezone(timezone.utc)

    @property
    def end_utc(self):
        return datetime.combine(self.end,time.min,BEIRUT).astimezone(timezone.utc)


def measurement_csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream,fieldnames=MEASUREMENT_COLUMNS,extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({k:csv_value(v.isoformat() if isinstance(v,(datetime,date)) else v) for k,v in row.items()})
        if stream.tell()>MAX_BYTES:
            raise SentraError('Extract too large. Narrow the filters; no partial CSV prepared.')
    result = stream.getvalue().encode('utf-8-sig')
    if len(result)>MAX_BYTES:
        raise SentraError('Extract too large. Narrow the filters; no partial CSV prepared.')
    return result


def inline_download(payload, filename, mime):
    """No server URL: bytes travel only in the already-authorized session iframe."""
    if (not isinstance(payload,bytes) or len(payload)>MAX_BYTES
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}',filename)
            or mime not in ('text/csv','application/gzip')):
        raise SentraError('Invalid or oversized private download.')
    encoded = base64.b64encode(payload).decode('ascii')
    return ('<style>body{font:14px system-ui}a{display:inline-block;background:#12634d;color:white;'
            'padding:10px 16px;border-radius:6px;text-decoration:none}</style>'
            f'<a download="{html.escape(filename)}" href="data:{mime};base64,{encoded}">'
            f'Download {html.escape(filename)}</a>')


def civil_day(value):
    if isinstance(value,str):
        try: return date.fromisoformat(value[:10]).isoformat()
        except ValueError: return None
    day=value.get('date',value) if isinstance(value,dict) else None
    try: return date(int(day['year']),int(day['month']),int(day['day'])).isoformat()
    except (KeyError,ValueError,TypeError): return None


def latest_timing(rows):
    return {'latest_point_time':max((r['measured_at'] for r in rows if r.get('measured_at')),default=None),
            'latest_interval_end':max((r['interval_end'] for r in rows if r.get('interval_end')),default=None),
            'latest_civil_day':max((civil_day(r.get('civil_date')) for r in rows if civil_day(r.get('civil_date'))),default=None)}


def fetch_status(state,dataset):
    last_success=max((s.get('last_success_at') for s in state['connection'] if s.get('last_success_at')),default=None)
    failures=[r.get('finished_at') or r['started_at'] for r in state['runs'] if r.get('status')!='paused' and
              any(f.get('dataset') in (None,dataset) for f in (r.get('failures') or []))]
    failed=max(failures,default=None)
    if failed is not None and (last_success is None or failed>last_success):return 'Fetch failed / needs review',last_success
    return ('Successful fetch recorded' if last_success else 'No successful fetch recorded'),last_success


def sampling_summary(rows):
    groups = {}
    missing = no_numeric = unscored = provisional = 0
    for row in rows:
        missing += row.get('availability')=='missing'
        no_numeric += row.get('value') is None
        unscored += row.get('score_state') in ('UNSCORED','UNSCORABLE','PENDING_SCORE')
        provisional += row.get('provisional') is True
        stamp = row.get('measured_at') or row.get('interval_start')
        if isinstance(stamp,datetime):
            groups.setdefault((row.get('metric'),row.get('unit'),row.get('resolution_seconds')),set()).add(stamp)
    intervals = []
    gaps = 0
    for (_,_,resolution), points in groups.items():
        ordered = sorted(points)
        observed = [(b-a).total_seconds() for a,b in zip(ordered,ordered[1:]) if b>a]
        intervals.extend(observed)
        if resolution is not None and resolution>0:
            gaps += sum(delta>float(resolution)*1.5 for delta in observed)
    return dict(returned_rows=len(rows),explicit_missing=missing,no_numeric_value=no_numeric,
                unscored_rows=unscored,provisional_rows=provisional,
                observed_intervals_seconds=sorted(set(intervals)),gap_candidates=gaps)
