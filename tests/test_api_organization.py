"""Organization API acceptance with synthetic credentials, policy and processed data."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import pandas as pd
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sentra import api, api_access
from sentra.access import resolve
from sentra.errors import SentraError

TOKEN = 'synthetic_organization_credential_' + 'a' * 32
EMAIL = 'officer@example.test'


class OrganizationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.credentials = self.folder / 'credentials.json'
        self.entry = {hashlib.sha256(TOKEN.encode()).hexdigest():
                      {'email': EMAIL, 'expires_at': int(time.time()) + 3600}}
        self.credentials.write_text(json.dumps(self.entry))
        self.env = mock.patch.dict(os.environ, {'SENTRA_PROCESSED_DIR': str(self.folder),
            'SENTRA_API_KEY': 'k' * 40, 'SENTRA_API_ORG_CREDENTIALS_FILE': str(self.credentials)})
        self.env.start()
        self.users = [{'email': EMAIL, 'org_id': 'org-a', 'role': 'officer', 'active': True}]
        self.consents = [dict(participant_id=f'p{i:02}', org_id='org-a', sharing='individual' if i == 1 else 'group_only',
            withdrawn=False, membership_open=True, demonstration=False) for i in range(1, 7)]
        self.consents.append(dict(self.consents[0], participant_id='p90', org_id='org-b'))
        self.policy = mock.patch.object(api, 'organization_access', side_effect=self.access)
        self.policy_mock = self.policy.start()
        rows = [dict(subject_id=f'p{i:02}', date=pd.Timestamp('2026-10-02'), device='Fitbit',
                     usable_day=True, rhr=60.0, sleep_min=420.0, steps=1000.0 if i <= 4 else None,
                     hr_mean=65.0, flag_short_sleep=False, flag_sustained_high_hr=False,
                     wellness_signals=0, wellness_level='green', email='DO-NOT-EXPOSE',
                     raw_ref='PRIVATE-ORIGINAL', location='PRIVATE-LOCATION') for i in range(1, 7)]
        rows.append(dict(rows[0], subject_id='p90', date=pd.Timestamp('2020-01-01'), sleep_min=10000.0))
        self.frame = pd.DataFrame(rows)
        self.write_data()
        pd.DataFrame([dict(date='2020-01-01', device='WHOOP', workers=999, median_sleep_h=999)]).to_parquet(
            self.folder / 'cohort_daily.parquet')
        (self.folder / 'metadata.json').write_text(json.dumps({'subjects': 999, 'days': ['2020-01-01', '2030-01-01'],
                                                             'notice': 'GLOBAL-MARKER', 'assessment_version': 'assessment-v1'}))
        api._cache.clear()
        self.client = TestClient(api.app)
        self.headers = {'Authorization': 'Bearer ' + TOKEN}

    def tearDown(self):
        self.policy.stop()
        self.env.stop()
        api._cache.clear()
        self.temp.cleanup()

    def access(self, email):
        try:
            return resolve(email, team_emails=(), org_users=self.users, consents=self.consents)
        except SentraError:
            raise HTTPException(403, 'Organization access denied') from None

    def write_data(self):
        self.frame.to_parquet(self.folder / 'daily_features.parquet')
        api._cache.clear()

    def get(self, route, **kwargs):
        return self.client.get('/api/v1/' + route, headers=self.headers, **kwargs)

    def test_officer_and_reviewer_scoped_lists_downloads_and_metadata(self):
        for role in ('officer', 'reviewer'):
            self.users[0]['role'] = role
            self.assertEqual(self.get('subjects').json(), ['p01'])
            response = self.get('daily')
            self.assertEqual(response.status_code, 200)
            self.assertEqual({r['subject_id'] for r in response.json()['rows']}, {'p01'})
            for secret in ('p02', 'p90', 'DO-NOT-EXPOSE', 'PRIVATE-', 'GLOBAL-MARKER'):
                self.assertNotIn(secret, response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            meta = self.get('metadata').json()
            self.assertEqual(meta['subjects'], 1)
            self.assertEqual(meta['days'], ['2026-10-02', '2026-10-02'])
            for pid in ('p02', 'p90', 'p99'):
                self.assertEqual(self.get('daily', params={'subject': pid}).json()['rows'], [])

    def test_every_request_rechecks_withdrawal_sharing_role_and_organization(self):
        self.assertEqual(self.get('subjects').json(), ['p01'])
        self.consents[0]['sharing'] = 'group_only'
        self.assertEqual(self.get('subjects').json(), [])
        self.assertIsNone(self.get('metadata').json()['days'])
        self.consents[0]['sharing'] = 'individual'
        self.consents[0]['withdrawn'] = True
        self.assertEqual(self.get('daily').json()['rows'], [])
        self.assertEqual(self.get('cohort').json()['rows'][0]['workers'], 5)
        self.users[0]['org_id'] = 'org-b'
        self.assertEqual(self.get('subjects').json(), ['p90'])
        self.assertEqual(self.get('cohort').json()['rows'], [])
        self.users[0]['active'] = False
        with mock.patch.object(api, '_table', side_effect=AssertionError('protected read')):
            for route in ('subjects', 'daily', 'cohort', 'metadata'):
                self.assertEqual(self.get(route).status_code, 403)

    def test_cohort_recomputed_in_scope_per_statistic_without_hidden_counts(self):
        body = self.get('cohort').json()
        self.assertEqual(len(body['rows']), 1)
        row = body['rows'][0]
        self.assertEqual((row['device'], row['workers'], row['median_sleep_h']), ('Fitbit', 6, 7.0))
        self.assertIsNone(row['median_steps'])
        self.assertIsNone(row['n_median_steps'])
        self.assertEqual(row['n_median_sleep_h'], 6)
        self.assertNotIn('999', json.dumps(body))
        self.consents[0]['withdrawn'] = True
        self.consents[1]['withdrawn'] = True
        self.assertEqual(self.get('cohort').json()['rows'], [])

    def test_devices_missing_inputs_and_duplicate_days_fail_closed(self):
        self.frame.loc[self.frame.subject_id == 'p06', 'device'] = 'WHOOP'
        self.write_data()
        rows = self.get('cohort').json()['rows']
        self.assertEqual([(r['device'], r['workers']) for r in rows], [('Fitbit', 5)])
        self.frame = pd.concat([self.frame, self.frame.iloc[:1]])
        self.write_data()
        self.assertEqual(self.get('cohort').status_code, 503)
        self.frame = self.frame.drop(columns=['device'])
        self.write_data()
        self.assertEqual(self.get('cohort').status_code, 503)

    def test_unknown_devices_never_supply_a_group_statistic(self):
        self.frame['device'] = None
        self.write_data()
        self.assertEqual(self.get('cohort').json()['rows'], [])

    def test_cache_cannot_reuse_another_processed_directory(self):
        self.assertEqual(self.get('subjects').json(), ['p01'])
        other = self.folder / 'other'
        other.mkdir()
        original = self.folder / 'daily_features.parquet'
        target = other / 'daily_features.parquet'
        self.frame.iloc[0:0].to_parquet(target)
        stamp = original.stat().st_mtime_ns
        os.utime(target, ns=(stamp, stamp))
        with mock.patch.dict(os.environ, {'SENTRA_PROCESSED_DIR': str(other)}):
            self.assertEqual(self.get('subjects').json(), [])

    def test_invalid_revoked_expired_and_ambiguous_credentials_never_read_policy(self):
        with mock.patch.object(api, '_table', side_effect=AssertionError('protected read')):
            for headers in ({'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer ' + 'b' * 64},
                            {**self.headers, 'X-API-Key': 'k' * 40}):
                self.assertEqual(self.client.get('/api/v1/daily', headers=headers).status_code, 401)
            self.entry[next(iter(self.entry))]['expires_at'] = 1
            self.credentials.write_text(json.dumps(self.entry))
            self.assertEqual(self.get('daily').status_code, 401)
            self.credentials.write_text('{}')
            self.assertEqual(self.get('daily').status_code, 401)
        self.policy_mock.assert_not_called()

    def test_missing_malformed_or_oversized_credentials_fail_closed(self):
        for content in ('not-json', '[]', '{"x":{},"x":{}}', 'x' * 65_537):
            self.credentials.write_text(content)
            response = self.get('daily')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(str(self.credentials), response.text)
        self.credentials.unlink()
        self.assertEqual(self.get('daily').status_code, 503)
        self.policy_mock.assert_not_called()

    def test_ambiguous_roles_and_policy_failure_never_use_team_fallback(self):
        self.users.append(dict(self.users[0], org_id='org-b'))
        self.assertEqual(self.get('daily').status_code, 403)
        self.policy_mock.side_effect = HTTPException(503, 'Policy unavailable')
        for route in ('daily', 'subjects', 'cohort', 'metadata'):
            self.assertEqual(self.get(route).status_code, 503)

    def test_organization_query_limits_and_team_compatibility(self):
        self.assertEqual(self.get('daily', params={'limit': 5001}).status_code, 422)
        self.assertEqual(self.get('cohort', params={'since': '2026-02-30'}).status_code, 422)
        rows = self.client.get('/api/v1/daily', headers={'X-API-Key': 'k' * 40}).json()['rows']
        self.assertIn('p90', {r['subject_id'] for r in rows})
        self.assertNotIn('days', self.client.get('/health').json())


class ApiPolicyBudgetTests(unittest.TestCase):
    def test_reservation_failure_stops_policy_read_and_closes_reader(self):
        with mock.patch.object(api_access, 'runtime_config', return_value=({}, None)), \
                mock.patch.object(api_access, 'ViewerReader') as factory, \
                mock.patch.object(api_access, 'read_policy') as read:
            factory.return_value.reserve.side_effect = SentraError('exhausted')
            with self.assertRaises(HTTPException) as error:
                api_access.organization_access(EMAIL)
            self.assertEqual(error.exception.status_code, 503)
            read.assert_not_called()
            factory.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
