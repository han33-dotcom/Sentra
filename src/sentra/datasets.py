"""Provider request contracts verified against official v4/v2 docs, 2026-10-08."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo

from .errors import SentraError

BEIRUT = ZoneInfo('Asia/Beirut')
WEARABLES = 'users/me/dataSourceFamilies/google-wearables'
# Extra Google LIST datasets in collection priority order; filter fields follow
# https://developers.google.com/health/filters (Interval: interval.start_time,
# Sample: sample_time.physical_time). Scopes: sedentary-period/activity-level use
# activity_and_fitness, respiratory-rate-sleep-summary health_metrics_and_measurements.
EXTRA_LIST = ('sedentary-period', 'respiratory-rate-sleep-summary', 'activity-level')
PHYSICAL_FILTERS = {'heart-rate': 'heart_rate.sample_time.physical_time',
                    'respiratory-rate-sleep-summary': 'respiratory_rate_sleep_summary.sample_time.physical_time',
                    'sedentary-period': 'sedentary_period.interval.start_time',
                    'activity-level': 'activity_level.interval.start_time',
                    'sleep': 'sleep.interval.end_time'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def utc_day(day):
    return datetime.combine(day, time(), BEIRUT).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def camel(name):
    first, *parts = name.split('-')
    return first + ''.join(p.title() for p in parts)


@dataclass(frozen=True)
class Job:
    provider: str
    dataset: str
    datatype: str
    mode: str
    start_date: str
    end_date: str
    start: str
    end: str

    @property
    def key(self):
        return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()

    @property
    def records_key(self):
        return 'records' if self.provider == 'whoop' else ('dataPoints' if self.mode == 'list' else 'rollupDataPoints')

    @property
    def resolution(self):
        return {'daily': 'vendor civil-day aggregation', 'minute': 'vendor 60-second aggregation',
                'list': 'original API resolution; observed cadence not assumed'}[self.mode]

    def request(self, cursor=''):
        if self.provider == 'whoop':
            endpoint = {'cycle': 'cycle', 'recovery': 'recovery', 'sleep': 'activity/sleep', 'workout': 'activity/workout'}[self.dataset]
            params = {'limit': 25, 'start': self.start, 'end': self.end}
            if cursor:
                params['nextToken'] = cursor
            return {'method': 'GET', 'url': 'https://api.prod.whoop.com/developer/v2/' + endpoint, 'params': params}
        base = 'https://health.googleapis.com/v4/users/me/dataTypes/' + self.datatype + '/dataPoints'
        if self.mode in ('minute', 'daily'):
            if self.mode == 'minute':
                body = {'range': {'startTime': self.start, 'endTime': self.end}, 'windowSize': '60s'}
                suffix = ':rollUp'
            else:
                def civil(text):
                    day = date.fromisoformat(text)
                    return {'date': {'year': day.year, 'month': day.month, 'day': day.day}}
                body = {'range': {'start': civil(self.start_date), 'end': civil(self.end_date)}, 'windowSizeDays': 1}
                suffix = ':dailyRollUp'
            body.update(pageSize=1000, dataSourceFamily=WEARABLES)
            if cursor:
                body['pageToken'] = cursor
            return {'method': 'POST', 'url': base + suffix, 'json': body}
        if self.datatype.startswith('daily-'):
            path, start, end = self.datatype.replace('-', '_') + '.date', self.start_date, self.end_date
        elif self.datatype in PHYSICAL_FILTERS:
            path, start, end = PHYSICAL_FILTERS[self.datatype], self.start, self.end
        else: # Exercise supports civil start time, not the generic physical filter.
            path, start, end = 'exercise.interval.civil_start_time', self.start_date, self.end_date
        params = {'pageSize': 25 if self.datatype in ('sleep', 'exercise') else 1000,
                  'filter': f'{path} >= "{start}" AND {path} < "{end}"', 'dataSourceFamily': WEARABLES}
        # Sleep LIST rejects source-family filtering. Preserve all returned
        # sources and their provenance; do not silently filter manual edits.
        if self.datatype == 'sleep':
            params.pop('dataSourceFamily')
        if cursor:
            params['pageToken'] = cursor
        return {'method': 'GET', 'url': base, 'params': params}


def plan_jobs(provider, start=None, end=None, *, now=None):
    end = end or (now or datetime.now(timezone.utc)).astimezone(BEIRUT).date()
    start = start or end - timedelta(days=30)
    if not isinstance(start, date) or not isinstance(end, date) or not 0 < (end - start).days <= 30:
        raise SentraError('Initial import must cover 1–30 calendar days; end is exclusive.')
    if provider not in ('whoop', 'google_health'):
        raise SentraError('Unknown provider.')
    def job(dataset, datatype, mode, first, last):
        return Job(provider, dataset, datatype, mode, first.isoformat(), last.isoformat(), utc_day(first), utc_day(last))
    if provider == 'whoop':
        return [job(name, name, 'list', start, end) for name in ('cycle', 'recovery', 'sleep', 'workout')]
    jobs = []
    day = start
    daily = ('steps', 'distance', 'total-calories', 'active-zone-minutes', 'active-minutes', 'heart-rate')
    health = ('daily-resting-heart-rate', 'daily-heart-rate-variability', 'daily-oxygen-saturation',
              'daily-respiratory-rate', 'daily-sleep-temperature-derivations', 'daily-vo2-max')
    while day < end:
        after = day + timedelta(days=1)
        if (day - start).days % 7 == 0:
            batch_end = min(day + timedelta(days=7), end)
            jobs.extend(job('daily_' + metric, metric, 'daily', day, batch_end) for metric in daily)
            jobs.extend(job(metric, metric, 'list', day, batch_end) for metric in health)
            jobs.extend(job(metric, metric, 'list', day, batch_end) for metric in ('sleep', 'exercise'))
            jobs.extend(job(metric, metric, 'list', day, batch_end) for metric in EXTRA_LIST)
        if day >= end - timedelta(days=7):
            jobs.extend(job('minute_' + metric, metric, 'minute', day, after)
                        for metric in ('steps', 'distance', 'total-calories', 'active-zone-minutes', 'heart-rate'))
        day = after
    jobs.append(job('original_heart-rate', 'heart-rate', 'list', end - timedelta(days=1), end))
    return jobs
