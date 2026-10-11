"""Read API over synthetic processed outputs: key required, pseudonyms only, read-only."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd

HAS_API = all(importlib.util.find_spec(m) for m in ('fastapi', 'httpx'))
KEY = 'k' * 40


@unittest.skipUnless(HAS_API, 'install the api extra and httpx to run API tests')
class ApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from sentra import api
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        pd.DataFrame({'subject_id': ['p01', 'p01', 'p02', 'alice'], 'date': pd.to_datetime(['2026-10-01', '2026-10-02', '2026-10-02', '2026-10-02']),
                      'rhr': [60.0, 61.0, 55.0, 50.0], 'wellness_level': ['green', 'amber', 'green', 'green']}
                     ).to_parquet(folder / 'daily_features.parquet')
        pd.DataFrame({'date': pd.to_datetime(['2026-10-02']), 'workers': [2], 'pct_short_sleep': [None], 'suppressed': [True]}
                     ).to_parquet(folder / 'cohort_daily.parquet')
        (folder / 'metadata.json').write_text(json.dumps({'notice': 'Wellness indicators; not a medical assessment.',
            'thresholds': {'_status': 'v0 — pending medical expert sign-off'}, 'days': ['2026-10-01', '2026-10-02']}), encoding='utf-8')
        self.env = mock.patch.dict(os.environ, {'SENTRA_PROCESSED_DIR': str(folder), 'SENTRA_API_KEY': KEY})
        self.env.start()
        api._cache.clear()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def test_health_is_public_and_leaks_no_rows(self):
        body = self.client.get('/health').json()
        self.assertEqual(body['status'], 'ok')
        self.assertNotIn('p01', json.dumps(body))

    def test_key_is_required_and_compared(self):
        self.assertEqual(self.client.get('/api/v1/daily').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/daily', headers={'X-API-Key': 'wrong'}).status_code, 401)
        with mock.patch.dict(os.environ, {'SENTRA_API_KEY': 'short'}):
            self.assertEqual(self.client.get('/api/v1/daily', headers={'X-API-Key': 'short'}).status_code, 503)

    def test_daily_returns_pseudonyms_only_with_notice_and_filters(self):
        h = {'X-API-Key': KEY}
        body = self.client.get('/api/v1/daily', headers=h).json()
        self.assertEqual({r['subject_id'] for r in body['rows']}, {'p01', 'p02'})
        self.assertIn('not a medical assessment', body['notice'])
        rows = self.client.get('/api/v1/daily?subject=p01&since=2026-10-02', headers=h).json()['rows']
        self.assertEqual([(r['subject_id'], r['wellness_level']) for r in rows], [('p01', 'amber')])
        self.assertEqual(self.client.get('/api/v1/daily?subject=alice', headers=h).status_code, 422)
        self.assertEqual(self.client.get('/api/v1/subjects', headers=h).json(), ['p01', 'p02'])
        meta = self.client.get('/api/v1/metadata', headers=h).json()
        self.assertEqual(meta['thresholds_status'], 'v0 — pending medical expert sign-off')
        self.assertTrue(self.client.get('/api/v1/cohort', headers=h).json()['rows'][0]['suppressed'])

    def test_no_write_routes_exist(self):
        from sentra import api
        methods = {m for route in api.app.routes for m in getattr(route, 'methods', set())}
        self.assertLessEqual(methods, {'GET', 'HEAD'})


class ProcessingJobConfigTests(unittest.TestCase):
    def test_collector_or_missing_config_is_refused(self):
        try:
            from sentra.processing.job import runtime_config
        except ImportError:
            self.skipTest('processing extra not installed')
        from sentra.errors import SentraError
        config = {'confirmed_free_plan': True, 'url': 'https://abc.supabase.co', 'publishable_key': 'x', 'storage_email': 'a@b.c',
                  'storage_password': 'x', 'certificate_pem': 'synthetic', 'limits': {},
                  'db': {'host': 'h.pooler.supabase.com', 'port': 5432, 'dbname': 'postgres', 'user': 'sentra_collector.abc', 'password': 'x'}}
        with tempfile.TemporaryDirectory() as folder:
            for env in ({}, {'SENTRA_PROCESSING_CONFIG': json.dumps(config)}):
                with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(SentraError):
                    runtime_config(folder)
            config['db']['user'] = 'sentra_viewer.abc'
            with mock.patch.dict(os.environ, {'SENTRA_PROCESSING_CONFIG': json.dumps(config)}, clear=True):
                credentials, _ = runtime_config(folder)
            self.assertEqual(credentials['db']['user'], 'sentra_viewer.abc')


if __name__ == '__main__':
    unittest.main()
