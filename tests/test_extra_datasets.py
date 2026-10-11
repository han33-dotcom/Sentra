"""Synthetic Google sedentary-period, respiratory-rate-sleep-summary and activity-level contracts."""
from datetime import date, datetime, timezone
import unittest

from sentra.cloud_collect import collect_job
from sentra.curated import curate
from sentra.daily_plan import day_jobs
from sentra.datasets import EXTRA_LIST, plan_jobs
from sentra.errors import SentraError
from sentra.normalize import normalize_record
from sentra.providers import PROVIDERS
from sentra.transport import FetchError

SOURCE = {'recordingMethod': 'PASSIVELY_MEASURED', 'platform': 'FITBIT'}


def interval(start, end):
    return {'startTime': start, 'endTime': end, 'startUtcOffset': '10800s', 'endUtcOffset': '10800s'}


def sedentary(name, start, end):
    return {'name': 'users/me/dataTypes/sedentary-period/dataPoints/' + name, 'dataSource': SOURCE,
            'sedentaryPeriod': {'interval': interval(start, end)}}


def level(name, kind, start, end):
    return {'name': 'users/me/dataTypes/activity-level/dataPoints/' + name, 'dataSource': SOURCE,
            'activityLevel': {'interval': interval(start, end), 'activityLevelType': kind}}


def breathing(name, when):
    return {'name': 'users/me/dataTypes/respiratory-rate-sleep-summary/dataPoints/' + name, 'dataSource': SOURCE,
            'respiratoryRateSleepSummary': {'sampleTime': {'physicalTime': when, 'utcOffset': '10800s'},
                                            'fullSleepStats': {'breathsPerMinute': 14.2, 'standardDeviation': 0.8,
                                                               'signalToNoise': 21.5},
                                            'remSleepStats': {'breathsPerMinute': 15.1}}}


def job(dataset, day=date(2026, 10, 7)):
    return next(j for j in day_jobs('google_health', day) if j.dataset == dataset)


def row(job_, raw):
    r = normalize_record(job_, raw)
    return dict(participant_id='p99', provider='google_health', dataset=job_.dataset, record_key=r['record_key'],
                source_response_id='b' * 64, collected_at=datetime(2026, 10, 9, tzinfo=timezone.utc), record=r)


class Store:
    """In-memory stand-in for CloudStore progress/page/failure persistence."""
    def __init__(self):
        self.current = None; self.pages = []; self.outcome = None

    def progress(self, j): return self.current

    def start(self, j, execution):
        self.current = {'cursor': '', 'seen': [], 'pages': 0, 'received': 0, 'status': 'running', 'execution_id': execution}
        return self.current

    def page(self, j, cursor, payload, body, nxt, p):
        records = payload.get(j.records_key, [])
        self.pages.append((cursor, len(records)))
        self.current = {**p, 'cursor': nxt, 'pages': p['pages'] + 1, 'received': p['received'] + len(records),
                        'seen': p['seen'] + ([cursor] if cursor else []), 'status': 'running' if nxt else 'complete'}
        return {'changed': len(records), 'unchanged': 0}

    def failed(self, j, message, outcome='failed'):
        self.outcome = outcome


class ExtraDatasetTests(unittest.TestCase):
    def test_plan_adds_priority_ordered_weekly_list_jobs_with_documented_filters(self):
        jobs = plan_jobs('google_health', date(2026, 10, 3), date(2026, 10, 10))
        names = [j.dataset for j in jobs]
        self.assertEqual([n for n in names if n in EXTRA_LIST], list(EXTRA_LIST))
        self.assertEqual(EXTRA_LIST, ('sedentary-period', 'respiratory-rate-sleep-summary', 'activity-level'))
        expected = {'sedentary-period': 'sedentary_period.interval.start_time',
                    'respiratory-rate-sleep-summary': 'respiratory_rate_sleep_summary.sample_time.physical_time',
                    'activity-level': 'activity_level.interval.start_time'}
        for j in jobs:
            if j.dataset in expected:
                params = j.request()['params']
                self.assertEqual(j.mode, 'list')
                self.assertEqual(params['filter'], f'{expected[j.dataset]} >= "2026-10-02T21:00:00Z" AND '
                                                   f'{expected[j.dataset]} < "2026-10-09T21:00:00Z"')
                self.assertEqual(params['pageSize'], 1000)
                self.assertEqual(params['dataSourceFamily'], 'users/me/dataSourceFamilies/google-wearables')
                self.assertTrue(j.request()['url'].endswith('/dataTypes/' + j.dataset + '/dataPoints'))
        self.assertEqual({j.dataset for j in day_jobs('google_health', date(2026, 10, 7))} & set(EXTRA_LIST), set(EXTRA_LIST))

    def test_existing_oauth_scopes_cover_the_new_types(self):
        scopes = PROVIDERS['google_health'].scopes
        # Google data-types table: sedentary-period/activity-level -> activity_and_fitness,
        # respiratory-rate-sleep-summary -> health_metrics_and_measurements.
        for group in ('activity_and_fitness', 'health_metrics_and_measurements'):
            self.assertIn('https://www.googleapis.com/auth/googlehealth.' + group + '.readonly', scopes)

    def test_all_pages_are_followed_and_records_outcome_recorded(self):
        j = job('sedentary-period')
        pages = {'': ({'dataPoints': [sedentary('a', '2026-10-07T06:00:00Z', '2026-10-07T07:00:00Z')],
                       'nextPageToken': 'p2'}, b'{}'),
                 'p2': ({'dataPoints': [sedentary('b', '2026-10-07T09:00:00Z', '2026-10-07T09:30:00Z')]}, b'{}')}
        store = Store()
        result = collect_job(store, j, lambda job_, cursor: pages[cursor], 'run')
        self.assertEqual(store.pages, [('', 1), ('p2', 1)])
        self.assertEqual((result['status'], result['outcome']), ('complete', 'records'))

    def test_no_records_denied_and_failed_are_distinct(self):
        j = job('activity-level')
        store = Store()
        result = collect_job(store, j, lambda *_: ({'dataPoints': []}, b'{"dataPoints":[]}'), 'run')
        self.assertEqual(result['outcome'], 'no_records')
        for status, outcome in ((403, 'denied'), (401, 'denied'), (404, 'failed')):
            store = Store()
            def refuse(*_): raise FetchError(status)
            with self.subTest(status=status), self.assertRaises(SentraError):
                collect_job(store, j, refuse, 'run')
            self.assertEqual(store.outcome, outcome)

    def test_normalization_keeps_vendor_paths_units_and_no_invented_values(self):
        r = normalize_record(job('respiratory-rate-sleep-summary'), breathing('n1', '2026-10-07T04:30:00Z'))
        metrics = {m['metric']: m for m in r['measurements']}
        full = metrics['/respiratoryRateSleepSummary/fullSleepStats/breathsPerMinute']
        self.assertEqual((full['value'], full['unit'], full['value_kind']), (14.2, 'breaths/min', 'vendor_calculation'))
        sd = metrics['/respiratoryRateSleepSummary/fullSleepStats/standardDeviation']
        self.assertEqual((sd['value'], sd['vendor_value'], sd['value_kind']), (None, 0.8, 'unknown'))
        self.assertNotIn('/respiratoryRateSleepSummary/deepSleepStats/breathsPerMinute', metrics)
        self.assertEqual(r['measured_at'], '2026-10-07T04:30:00Z')
        a = normalize_record(job('activity-level'), level('l1', 'LIGHTLY_ACTIVE', '2026-10-07T06:00:00Z', '2026-10-07T06:10:00Z'))
        kind = next(m for m in a['measurements'] if m['metric'] == '/activityLevel/activityLevelType')
        self.assertEqual((kind['vendor_value'], kind['value']), ('LIGHTLY_ACTIVE', None))
        self.assertEqual((a['record_key'], a['interval_start']), ('l1', '2026-10-07T06:00:00Z'))

    def test_viewer_sums_non_overlapping_periods_per_day_without_zero_filling(self):
        s = job('sedentary-period'); lv = job('activity-level'); br = job('respiratory-rate-sleep-summary')
        rows = [row(s, sedentary('a', '2026-10-07T06:00:00Z', '2026-10-07T07:00:00Z')),
                row(s, sedentary('b', '2026-10-07T09:00:00Z', '2026-10-07T09:30:00Z')),
                row(lv, level('l1', 'VERY_ACTIVE', '2026-10-07T06:00:00Z', '2026-10-07T06:20:00Z')),
                row(lv, level('l2', 'MYSTERY_LEVEL', '2026-10-07T07:00:00Z', '2026-10-07T07:20:00Z')),
                row(br, breathing('n1', '2026-10-07T04:30:00Z'))]
        result = curate(rows, date(2026, 10, 7), date(2026, 10, 9))
        today, tomorrow = result['Daily activity']
        self.assertEqual(today['Sedentary time'], '1 h 30 min')
        self.assertEqual(today['Time very active'], '0 h 20 min')
        self.assertEqual(today['Fitbit breathing rate (full sleep)'], '14.2 breaths/min')
        self.assertEqual(today['Fitbit breathing rate (REM sleep)'], '15.1 breaths/min')
        self.assertNotIn('Time lightly active', today)  # unknown enum values are not reclassified
        self.assertEqual(tomorrow['Sedentary time'], 'Not returned')
        total = next(e for e in result['export'] if e['Metric'] == 'Sedentary time')
        self.assertEqual((total['Exact value'], total['Classification']), ('5400.0', 'sentra_calculation'))

    def test_overlapping_periods_are_reported_not_summed(self):
        s = job('sedentary-period')
        rows = [row(s, sedentary('a', '2026-10-07T06:00:00Z', '2026-10-07T07:00:00Z')),
                row(s, sedentary('b', '2026-10-07T06:30:00Z', '2026-10-07T07:30:00Z'))]
        today = curate(rows, date(2026, 10, 7), date(2026, 10, 8))['Daily activity'][0]
        self.assertEqual(today['Sedentary time'], 'Not summed: invalid or overlapping intervals')


if __name__ == '__main__':
    unittest.main()
