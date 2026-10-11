"""Synthetic fixtures only; exercise real planning, HTTP boundary and encrypted store."""
from dataclasses import replace
from datetime import date, datetime, timezone
import gzip
import importlib
import json
from pathlib import Path
import tempfile
import unittest
import io
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from cryptography.fernet import Fernet
import requests

from sentra.config import Connection
from sentra.errors import SentraError


class CollectorTests(unittest.TestCase):
    def module(self, name):
        try:
            return importlib.import_module('sentra.' + name)
        except ModuleNotFoundError:
            self.fail('Stage 2 component not implemented: ' + name)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cipher = Fernet(Fernet.generate_key())
        self.conn = Connection('whoop', 'p02', self.root, self.root / 'client.json',
                               'http://localhost:8765/callback', True, 'unknown', 'fake', 'fake')

    def tearDown(self):
        self.temp.cleanup()

    def jobs(self, provider='whoop'):
        return self.module('datasets').plan_jobs(provider, date(2026, 10, 1), date(2026, 10, 8))

    def store(self):
        return self.module('local_store').LocalStore(self.conn, self.cipher)

    def test_bounded_jobs_match_provider_filters_and_dst(self):
        ds = self.module('datasets')
        jobs = ds.plan_jobs('google_health', date(2026, 10, 1), date(2026, 10, 8))
        heart = next(j for j in jobs if j.dataset == 'minute_heart-rate')
        self.assertEqual(heart.request()['json']['windowSize'], '60s')
        self.assertEqual(heart.start, '2026-09-30T21:00:00Z')
        sleep = next(j for j in jobs if j.dataset == 'sleep')
        self.assertIn('sleep.interval.end_time', sleep.request()['params']['filter'])
        original = [j for j in jobs if j.dataset == 'original_heart-rate']
        self.assertEqual(len(original), 1)
        self.assertEqual(original[0].start, '2026-10-06T21:00:00Z')
        daily = next(j for j in jobs if j.dataset == 'daily_steps')
        self.assertEqual(daily.request()['json']['range']['start']['date'], {'year': 2026, 'month': 10, 'day': 1})
        self.assertEqual(daily.request()['json']['dataSourceFamily'], 'users/me/dataSourceFamilies/google-wearables')
        dst = ds.plan_jobs('google_health', date(2026, 10, 24), date(2026, 10, 27))
        day = next(j for j in dst if j.dataset == 'minute_steps' and j.start_date == '2026-10-24')
        self.assertEqual((day.start, day.end), ('2026-10-23T21:00:00Z', '2026-10-24T22:00:00Z'))
        with self.assertRaises(SentraError):
            ds.plan_jobs('whoop', date(2026, 8, 1), date(2026, 10, 8))

    def test_http_retries_read_only_rollup_preserves_response_bytes(self):
        transport = self.module('transport')
        job = next(j for j in self.jobs('google_health') if j.dataset == 'minute_steps')
        raw = b'{ "rollupDataPoints": [], "nextPageToken": "synthetic-page" }'
        responses = [response(429, b'private error', {'Retry-After': '0'}), response(500, b'private error'), response(200, raw)]
        with patch('sentra.transport.requests.request', side_effect=responses) as send:
            client = transport.ReadClient(lambda refresh=False: 'fake-token', pause=lambda _: None, pace=0)
            payload, body = client.fetch(job, '')
        self.assertEqual(body, raw)
        self.assertEqual(payload['nextPageToken'], 'synthetic-page')
        self.assertEqual(send.call_count, 3)
        self.assertEqual(send.call_args.args[0], 'POST')
        self.assertFalse(send.call_args.kwargs['allow_redirects'])

    def test_daily_health_filter_and_sleep_source_family_contract(self):
        jobs = self.jobs('google_health')
        daily = next(j for j in jobs if j.dataset == 'daily-resting-heart-rate')
        self.assertIn('daily_resting_heart_rate.date', daily.request()['params']['filter'])
        sleep = next(j for j in jobs if j.dataset == 'sleep')
        self.assertNotIn('dataSourceFamily', sleep.request()['params'])

    def test_daily_history_uses_weekly_requests_without_changing_resolution(self):
        jobs = self.module('datasets').plan_jobs('google_health', date(2026, 9, 8), date(2026, 10, 8))
        daily = [j for j in jobs if j.dataset == 'daily_steps']
        self.assertEqual(len(daily), 5)
        self.assertEqual(sum((date.fromisoformat(j.end_date) - date.fromisoformat(j.start_date)).days for j in daily), 30)
        self.assertTrue(all(j.request()['json']['windowSizeDays'] == 1 for j in daily))
        self.assertEqual(len([j for j in jobs if j.dataset == 'minute_heart-rate']), 7)

    def test_usage_handles_an_atomic_temp_file_disappearing(self):
        store = self.store()
        transient = store.root / '.sentra-race'
        transient.write_bytes(b'ciphertext')
        original = Path.stat
        calls = 0
        def disappearing(path, *args, **kwargs):
            nonlocal calls
            if path == transient:
                calls += 1
                if calls == 2:
                    transient.unlink()
                    raise FileNotFoundError('atomic rename raced with scan')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'stat', disappearing):
            self.assertGreaterEqual(store.usage(), 0)

    def test_http_retry_budget_and_auth_refresh_are_bounded(self):
        transport = self.module('transport')
        job = self.jobs()[0]
        renewed = []
        def token(refresh=False):
            renewed.append(refresh)
            return 'fake-new' if refresh else 'fake-old'
        with patch('sentra.transport.requests.request', side_effect=[response(401, b'private'), response(200, b'{"records": []}')]) as send:
            transport.ReadClient(token, pause=lambda _: None, pace=0).fetch(job, '')
        self.assertEqual(renewed.count(True), 1)
        self.assertEqual(send.call_args.kwargs['headers']['Authorization'], 'Bearer fake-new')
        for code in (403, 400, 429, 500):
            with patch('sentra.transport.requests.request', return_value=response(code, b'fake-secret private health', {'Retry-After': '86400'})) as send:
                with self.assertRaises(SentraError) as error:
                    transport.ReadClient(token, pause=lambda _: None, pace=0).fetch(job, '')
                self.assertNotIn('fake-secret', str(error.exception))
                self.assertLessEqual(send.call_count, 4)
                if code in (400, 403, 429):
                    self.assertEqual(send.call_count, 1)

    def test_http_limits_stream_size_and_rejects_redirects(self):
        transport = self.module('transport')
        for resp in (response(200, b'x' * 100), response(302, b'private redirect')):
            with patch('sentra.transport.requests.request', return_value=resp):
                with self.assertRaises(SentraError):
                    transport.ReadClient(lambda refresh=False: 'fake', max_bytes=50, pace=0).fetch(self.jobs()[0], '')

    def test_normalization_identity_ignores_corrected_value_and_retains_unknowns(self):
        norm = self.module('normalize')
        job = next(j for j in self.jobs('google_health') if j.dataset == 'original_heart-rate')
        record = {'heartRate': {'sampleTime': {'physicalTime': '2026-10-07T10:00:00.123456789Z', 'utcOffset': '10800s'}, 'beatsPerMinute': '61', 'newVendorField': 'unknown'}, 'dataSource': {'platform': 'FITBIT'}}
        first = norm.normalize_record(job, record)
        corrected = norm.normalize_record(job, {**record, 'heartRate': {**record['heartRate'], 'beatsPerMinute': '65'}})
        self.assertEqual(first['record_key'], corrected['record_key'])
        metric = next(m for m in first['measurements'] if m['vendor_metric'] == '/heartRate/beatsPerMinute')
        self.assertEqual((metric['value'], metric['unit'], metric['value_kind']), (61, 'beats/min', 'measurement'))
        self.assertEqual(metric['measured_at'], '2026-10-07T10:00:00.123456789Z')
        self.assertEqual(metric['resolution_seconds'], None)
        unknown = next(m for m in first['measurements'] if m['vendor_metric'].endswith('/newVendorField'))
        self.assertEqual((unknown['vendor_value'], unknown['value_kind']), ('unknown', 'unknown'))
        self.assertIn('dataSource', first['vendor_fields'])
        self.assertIn('sampleTime', first['vendor_fields']['heartRate'])
        self.assertFalse(any(m['vendor_metric'].startswith('/dataSource/') or '/sampleTime/' in m['vendor_metric'] for m in first['measurements']))

    def test_documented_vendor_summary_units_are_not_guessed(self):
        norm = self.module('normalize')
        job = next(j for j in self.jobs('google_health') if j.dataset == 'daily_distance')
        record = {'civilStartTime': {'date': {'year': 2026, 'month': 10, 'day': 1}},
                  'distance': {'millimetersSum': '1234'}}
        value = norm.normalize_record(job, record)
        metric = next(m for m in value['measurements'] if m['vendor_metric'].endswith('millimetersSum'))
        self.assertEqual((metric['value'], metric['unit'], metric['value_kind']), (1234, 'mm', 'vendor_summary'))
        sleep = next(j for j in self.jobs() if j.dataset == 'sleep')
        record = {**cycle_record(), 'score': {'stage_summary': {'total_rem_sleep_time_milli': 1234, 'total_future_metric_milli': 9}}}
        value = norm.normalize_record(sleep, record)
        known = next(m for m in value['measurements'] if m['vendor_metric'].endswith('total_rem_sleep_time_milli'))
        future = next(m for m in value['measurements'] if m['vendor_metric'].endswith('total_future_metric_milli'))
        self.assertEqual(known['unit'], 'ms')
        self.assertEqual((future['unit'], future['value_kind']), (None, 'unknown'))

    def test_expired_cursor_restarts_once_without_duplicates(self):
        collect = self.module('collect')
        error = self.module('transport').FetchError
        job = self.jobs()[0]
        store = self.store()
        store.start_job(job)
        raw = json.dumps({'records': [cycle_record()], 'next_token': 'expired'}).encode()
        store.save_page(job, '', json.loads(raw), raw, 'expired')
        calls = []
        def fetch(job, cursor):
            calls.append(cursor)
            if cursor:
                raise error(400)
            final = json.dumps({'records': [cycle_record(), cycle_record(2)]}).encode()
            return json.loads(final), final
        result = collect.run_jobs(store, [job], fetch)
        self.assertEqual((result['failed'], calls), (0, ['expired', '']))
        self.assertEqual(len(self.store().records()), 2)

    def test_export_capacity_failure_removes_partial_files(self):
        export = self.module('exports')
        capacity = self.module('local_store').CapacityStop
        store = self.store()
        store.max_bytes = 1
        with self.assertRaises(capacity):
            export.export_records(store)
        self.assertEqual(list((store.root / 'exports').rglob('*.gz')), [])

    def test_large_export_does_not_rescan_private_storage_for_every_chunk(self):
        export = self.module('exports')
        collect = self.module('collect')
        raw = json.dumps({'records': [cycle_record(i) for i in range(500)]}).encode()
        store = self.store()
        collect.run_jobs(store, [self.jobs()[0]], lambda j, t: (json.loads(raw), raw))
        with patch.object(store, 'usage', wraps=store.usage) as scan:
            paths = export.export_records(store)
        self.assertLess(scan.call_count, 20)
        self.assertEqual(len(json.loads(gzip.decompress(paths['records'].read_bytes()))), 500)

    def test_recovery_uses_associated_cycle_not_creation_time(self):
        norm = self.module('normalize')
        job = next(j for j in self.jobs() if j.dataset == 'recovery')
        cycle = cycle_record()
        record = {'cycle_id': 1, 'user_id': 555, 'created_at': '2026-10-08T09:00:00Z', 'score_state': 'UNSCORABLE', 'score': None}
        value = norm.normalize_record(job, record, cycle=cycle)
        self.assertEqual(value['interval_start'], '2026-10-01T03:00:00Z')
        self.assertEqual(value['timestamp_basis'], 'associated_cycle_interval')
        self.assertNotIn('user_id', value['vendor_fields'])
        self.assertEqual(norm.normalize_record(job, record)['timestamp_basis'], 'unresolved_cycle_interval')

    def test_resume_all_pages_empty_page_and_idempotent_corrections(self):
        collect = self.module('collect')
        job = self.jobs()[0]
        calls = []
        def fetch(job, token):
            calls.append(token)
            if not token:
                body = b'{"records": [], "next_token": "second"}'
            else:
                body = json.dumps({'records': [cycle_record()], 'next_token': None}).encode()
            return json.loads(body), body
        store = self.store()
        outcome = collect.run_jobs(store, [job], fetch)
        self.assertEqual(outcome['failed'], 0)
        self.assertEqual(calls, ['', 'second'])
        self.assertEqual(len(store.records()), 1)
        collect.run_jobs(store, [job], fetch)
        self.assertEqual(len(calls), 2)
        changed = cycle_record()
        changed['score']['strain'] = 9
        changed['score'].pop('average_heart_rate')
        def correction(job, token):
            raw = json.dumps({'records': [changed]}).encode()
            return json.loads(raw), raw
        collect.run_jobs(store, [job], correction, recheck=True)
        fresh = self.store()
        self.assertEqual(len(fresh.records()), 1)
        row = fresh.records()[0]
        self.assertEqual(row['vendor_fields']['score']['strain'], 9)
        self.assertFalse(any(m['vendor_metric'].endswith('average_heart_rate') for m in row['measurements']))
        self.assertEqual(fresh.progress(job)['status'], 'complete')
        self.assertEqual(len(fresh.manifests()), 3)

    def test_failed_page_resumes_from_last_durable_cursor(self):
        collect = self.module('collect')
        job = self.jobs()[0]
        body = json.dumps({'records': [cycle_record()], 'next_token': 'resume-here'}).encode()
        def fetch(job, token):
            if token:
                raise SentraError('Synthetic network failure')
            return json.loads(body), body
        store = self.store()
        self.assertEqual(collect.run_jobs(store, [job], fetch)['failed'], 1)
        fresh = self.store()
        self.assertEqual(fresh.progress(job)['cursor'], 'resume-here')
        def resume(job, token):
            self.assertEqual(token, 'resume-here')
            raw = json.dumps({'records': [cycle_record(2)]}).encode()
            return json.loads(raw), raw
        collect.run_jobs(fresh, [job], resume)
        self.assertEqual(len(self.store().records()), 2)

    def test_persist_failure_does_not_advance_durable_state(self):
        collect = self.module('collect')
        job = self.jobs()[0]
        raw = json.dumps({'records': [cycle_record()], 'next_token': 'next'}).encode()
        store = self.store()
        store.start_job(job)
        with patch('sentra.local_store.atomic_write', side_effect=OSError('Synthetic disk interruption')):
            with self.assertRaises(SentraError):
                store.save_page(job, '', {'records': [cycle_record()]}, raw, 'next')
        fresh = self.store()
        self.assertEqual(fresh.progress(job)['cursor'], '')
        self.assertEqual(fresh.records(), [])

    def test_snapshot_failure_after_raw_write_keeps_cursor_and_reuses_raw(self):
        collect = self.module('collect')
        module = self.module('local_store')
        job = self.jobs()[0]
        raw = json.dumps({'records': [cycle_record()]}).encode()
        store = self.store()
        store.start_job(job)
        real_write = module.atomic_write
        def interrupted(path, content):
            if path == store.path:
                raise OSError('Synthetic checkpoint interruption after raw object')
            real_write(path, content)
        with patch('sentra.local_store.atomic_write', side_effect=interrupted):
            with self.assertRaises(SentraError):
                store.save_page(job, '', json.loads(raw), raw, 'next')
        self.assertEqual(self.store().progress(job)['cursor'], '')
        self.assertEqual(self.store().records(), [])
        self.assertEqual(len(list(store.raw_folder.glob('*.enc'))), 1)
        collect.run_jobs(self.store(), [job], lambda j, t: (json.loads(raw), raw))
        self.assertEqual(len(self.store().records()), 1)
        self.assertEqual(len(list(store.raw_folder.glob('*.enc'))), 1)

    def test_corrupted_original_fails_verification_without_resetting_store(self):
        collect = self.module('collect')
        raw = json.dumps({'records': [cycle_record()]}).encode()
        store = self.store()
        collect.run_jobs(store, [self.jobs()[0]], lambda j, t: (json.loads(raw), raw))
        manifest = store.manifests()[0]
        (store.raw_folder / manifest['body_file']).write_bytes(b'corrupted synthetic ciphertext')
        with self.assertRaises(SentraError):
            store.original_bytes(manifest)
        self.assertEqual(len(self.store().records()), 1)
        result = collect.run_jobs(store, [self.jobs()[0]], lambda j, t: (json.loads(raw), raw), recheck=True)
        self.assertEqual(result['failed'], 1)

    def test_repeated_cursor_and_malformed_page_fail_without_false_coverage(self):
        collect = self.module('collect')
        job = self.jobs()[0]
        for payload in ({'records': [], 'next_token': 'same'}, {'records': 'not-a-list'}, {'unexpected': 'structure'},
                        {'records': [], 'next_token': 0}, {'records': [], 'next_token': False}):
            store = self.store()
            raw = json.dumps(payload).encode()
            result = collect.run_jobs(store, [job], lambda j, t: (payload, raw), recheck=True)
            self.assertEqual(result['failed'], 1)
            self.assertNotEqual(self.store().progress(job)['status'], 'complete')

    def test_recovery_timing_follows_cycle_arriving_later_without_refetch(self):
        collect = self.module('collect')
        cycle, recovery = self.jobs()[:2]
        raw = json.dumps({'records': [{'cycle_id': 1, 'score': {'recovery_score': 50}}]}).encode()
        store = self.store()
        collect.run_jobs(store, [recovery], lambda j, t: (json.loads(raw), raw))
        self.assertEqual(store.records('recovery')[0]['timestamp_basis'], 'unresolved_cycle_interval')
        cyc = json.dumps({'records': [cycle_record()]}).encode()
        collect.run_jobs(store, [cycle], lambda j, t: (json.loads(cyc), cyc))
        row = self.store().records('recovery')[0]
        self.assertEqual(row['interval_start'], cycle_record()['start'])
        self.assertEqual(row['timestamp_basis'], 'associated_cycle_interval')
        self.assertIsNotNone(row['associated_cycle_source_response_id'])

    def test_identical_recheck_keeps_fetch_observations_and_deduplicates_raw(self):
        collect = self.module('collect')
        raw = json.dumps({'records': [cycle_record()]}).encode()
        store = self.store()
        fetch = lambda j, t: (json.loads(raw), raw)
        collect.run_jobs(store, [self.jobs()[0]], fetch)
        collect.run_jobs(store, [self.jobs()[0]], fetch, recheck=True)
        self.assertEqual(len(self.store().manifests()), 2)
        self.assertEqual(len(list(store.raw_folder.glob('*.enc'))), 1)
        self.assertEqual(len(self.store().records()), 1)

    def test_google_malformed_nested_time_is_a_sanitized_dataset_failure(self):
        collect = self.module('collect')
        jobs = [j for j in self.module('datasets').plan_jobs('google_health', date(2026, 9, 24), date(2026, 10, 8)) if j.dataset == 'sleep']
        conn = replace(self.conn, provider='google_health')
        store = self.module('local_store').LocalStore(conn, self.cipher)
        def fetch(job, token):
            payload = {'dataPoints': [{'name': 'synthetic', 'sleep': {'interval': None}}]} if job == jobs[0] else {}
            return payload, json.dumps(payload).encode()
        result = collect.run_jobs(store, jobs, fetch)
        self.assertEqual((result['failed'], result['completed']), (1, 1))

    def test_failure_isolated_and_capacity_stops_before_fetch(self):
        collect = self.module('collect')
        jobs = self.jobs()[:2]
        def fetch(job, token):
            if job.dataset == 'cycle':
                raise SentraError('Synthetic access denied')
            return {'records': []}, b'{"records": []}'
        result = collect.run_jobs(self.store(), jobs, fetch)
        self.assertEqual((result['failed'], result['completed']), (1, 1))
        limited = self.module('local_store').LocalStore(self.conn, self.cipher, max_bytes=1)
        with patch('sentra.transport.requests.request') as network:
            result = collect.run_jobs(limited, [jobs[0]], lambda j, t: network())
        self.assertEqual(result['capacity_stop'], True)
        network.assert_not_called()

    def test_completed_larger_window_supersedes_old_failed_attempt_without_deletion(self):
        collect = self.module('collect')
        job = self.jobs()[0]
        old = replace(job, end_date='2026-10-02', end='2026-10-01T21:00:00Z')
        store = self.store()
        def failure(j, t):
            raise SentraError('Synthetic interrupted earlier request')
        collect.run_jobs(store, [old], failure)
        collect.run_jobs(store, [job], lambda j, t: ({'records': []}, b'{"records":[]}'))
        prior = self.store().progress(old)
        self.assertEqual(prior['status'], 'superseded')
        self.assertEqual(prior['superseded_by'], job.key)
        self.assertIn('Synthetic', prior['failure'])

    def test_private_exports_sanitize_identity_and_formula_strings(self):
        export = self.module('exports')
        collect = self.module('collect')
        job = self.jobs()[0]
        record = cycle_record()
        record['unknown_field'] = '=1+1'
        raw = json.dumps({'records': [record]}).encode()
        store = self.store()
        collect.run_jobs(store, [job], lambda j, t: (json.loads(raw), raw))
        with patch.object(store, 'records', side_effect=AssertionError('Exports must stream rows')):
            paths = export.export_records(store, 'cycle')
        text = gzip.decompress(paths['records'].read_bytes()).decode()
        self.assertNotIn('user_id', text)
        self.assertNotIn('fake', text)
        self.assertIn("'=1+1", gzip.decompress(paths['measurements'].read_bytes()).decode())
        originals = export.export_originals(store)
        self.assertEqual(gzip.decompress(originals[0].read_bytes()), raw)
        self.assertTrue(all(p.is_relative_to(self.root / 'exports') for p in paths.values()))

    def test_encrypted_store_keeps_metric_context_once_and_restores_export_shape(self):
        collect = self.module('collect')
        job = self.jobs()[0]
        raw = json.dumps({'records': [cycle_record()]}).encode()
        store = self.store()
        collect.run_jobs(store, [job], lambda j, t: (json.loads(raw), raw))
        blob = store.db.execute('SELECT data FROM records').fetchone()[0]
        self.assertIsInstance(blob, bytes)
        stored = self.module('local_store').decode_record(blob)
        self.assertNotIn('vendor_time', stored['measurements'][0])
        row = self.store().records()[0]
        self.assertEqual(row['measurements'][0]['vendor_time'], row['vendor_time'])
        self.assertEqual(row['measurements'][0]['source_response_id'], row['source_response_id'])

    def test_cli_import_status_and_exports_use_authorized_private_store(self):
        from sentra.cli import main
        self.module('collect')
        with patch('sentra.cli.load_connection', return_value=self.conn), patch('sentra.cli.local_cipher', return_value=self.cipher), \
             patch('sentra.transport.ReadClient.fetch', return_value=({'records': [cycle_record()]}, json.dumps({'records': [cycle_record()]}).encode())):
            out = io.StringIO()
            with redirect_stdout(out):
                try:
                    result = main(['initial-import', 'whoop', '--start', '2026-10-01', '--end', '2026-10-08', '--dataset', 'cycle'])
                except SystemExit:
                    self.fail('CLI initial-import command not implemented')
                status = main(['status', 'whoop'])
                exported = main(['export', 'whoop', '--dataset', 'cycle'])
            self.assertEqual((result, status, exported), (0, 0, 0))
            self.assertIn('succeeded', out.getvalue())
            self.assertNotIn('user_id', out.getvalue())
        declined = replace(self.conn, agreed=False)
        with patch('sentra.cli.load_connection', return_value=declined), patch('sentra.cli.local_cipher', return_value=self.cipher), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['initial-import', 'whoop']), 1)


def response(code, body, headers=None):
    resp = requests.Response()
    resp.status_code = code
    resp._content = body
    resp._content_consumed = True
    resp.headers.update(headers or {})
    return resp


def cycle_record(identifier=1):
    return {'id': identifier, 'user_id': 555, 'created_at': '2026-10-01T10:00:00Z',
            'updated_at': '2026-10-01T11:00:00Z', 'start': '2026-10-01T03:00:00Z',
            'end': '2026-10-02T03:00:00Z', 'timezone_offset': '+03:00', 'score_state': 'SCORED',
            'score': {'strain': 5, 'average_heart_rate': 60}}
