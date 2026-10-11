"""Synthetic viewer security/export contracts; no participant data or credentials."""
import base64
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import gzip
import io
import re
import unittest

from sentra.errors import SentraError


class ViewerContracts(unittest.TestCase):
    def module(self):
        try:
            from sentra import viewer_data
            return viewer_data
        except ImportError:
            self.fail('Viewer contracts not implemented')

    def test_exact_verified_google_identity_required_and_expired_session_denied(self):
        m = self.module()
        now = 1000
        good = dict(is_logged_in=True, email='TEAM@example.test', email_verified=True,
                    iss='https://accounts.google.com', exp=1100)
        self.assertEqual(m.authorize(good, ['team@example.test'], now=now), 'team@example.test')
        for overrides in ({'is_logged_in':False}, {'email':'other@example.test'},
                          {'email_verified':False}, {'email_verified':'true'},
                          {'exp':999}, {'iss':'https://untrusted.example.test'}, {'exp':None}):
            with self.subTest(overrides=overrides), self.assertRaises(SentraError):
                m.authorize({**good, **overrides}, ['team@example.test'], now=now)
        with self.assertRaises(SentraError): m.authorize(good, [], now=now)

    def test_beirut_dates_include_civil_days_and_dst_without_fixed_offset(self):
        m = self.module()
        f = m.Selection('p99', 'google_health', 'minute_heart-rate', date(2026,3,29),date(2026,3,30))
        self.assertEqual((f.end_utc-f.start_utc).total_seconds(), 23*3600)
        with self.assertRaises(SentraError): m.Selection('p99','whoop','sleep',date(2026,10,9),date(2026,10,8))
        with self.assertRaises(SentraError): m.Selection('p99','whoop','sleep',date(2026,1,1),date(2026,10,8))
        with self.assertRaises(SentraError): m.Selection('identity@example.test','whoop','sleep',date(2026,10,7),date(2026,10,8))

    def test_csv_matches_selected_rows_and_preserves_decimals_and_vendor_fields(self):
        m = self.module()
        rows = [{'participant_id':'p99', 'provider':'whoop','dataset':'sleep','metric':'/synthetic',
                 'value':Decimal('70.12345678901234'),'vendor_value':{'x':1}, 'vendor_unit':'beats/min',
                 'unit':'beats/min','source_response_id':'a'*64,'source_pointer':'/records/0/score/x',
                 'provisional':True}, {'participant_id':'p99','provider':'whoop','dataset':'sleep',
                 'metric':'=unsafe','vendor_value':'@unsafe','value':None}]
        raw = m.measurement_csv(rows)
        exported = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(len(exported),2)
        self.assertEqual(exported[0]['value'],'70.12345678901234')
        self.assertEqual(exported[0]['vendor_value'],'{"x":1}')
        self.assertEqual(exported[0]['source_pointer'],'/records/0/score/x')
        self.assertTrue(exported[1]['metric'].startswith("'="))
        self.assertTrue(exported[1]['vendor_value'].startswith("'@"))

    def test_download_bytes_are_inline_without_server_media_or_storage_urls(self):
        m = self.module()
        payload = gzip.compress(b'{"synthetic":123}',mtime=0)
        html = m.inline_download(payload,'original-synthetic.json.gz','application/gzip')
        content = re.search(r'base64,([A-Za-z0-9+/=]+)',html).group(1)
        self.assertEqual(base64.b64decode(content),payload)
        self.assertIn('download="original-synthetic.json.gz"',html)
        self.assertNotIn('/media/',html)
        self.assertNotIn('https://',html)
        with self.assertRaises(SentraError): m.inline_download(payload,'../bad.html','text/html')

    def test_sampling_is_observed_and_does_not_invent_expected_records(self):
        m = self.module()
        rows = [{'metric':'/hr','unit':'beats/min','measured_at':datetime(2026,10,7,0,i,tzinfo=timezone.utc),
                 'value':70, 'availability':'available','provisional':True,'score_state':'SCORED',
                 'resolution_seconds':60} for i in (0,1,3)]
        rows += [{'metric':'/hr','unit':'beats/min','value':None,'availability':'missing',
                  'score_state':'UNSCORABLE','provisional':True}]
        audit = m.sampling_summary(rows)
        self.assertEqual(audit['returned_rows'],4)
        self.assertEqual(audit['explicit_missing'],1)
        self.assertEqual(audit['no_numeric_value'],1)
        self.assertEqual(audit['observed_intervals_seconds'],[60.0,120.0])
        self.assertEqual(audit['gap_candidates'],1)
        self.assertEqual(audit['unscored_rows'],1)
        self.assertNotIn('missing_expected_records',audit)
        # Different metrics/units cannot create artificial sampling intervals.
        self.assertEqual(m.sampling_summary([{**rows[0],'unit':'ms'},rows[1]])['observed_intervals_seconds'],[])

    def test_latest_time_distinguishes_physical_points_intervals_and_civil_days(self):
        m=self.module()
        stamp=datetime(2026,10,7,12,tzinfo=timezone.utc)
        result=m.latest_timing([{'interval_end':stamp},
                                {'civil_date':{'date':{'year':2026,'month':10,'day':8}}},
                                {'civil_date':{'year':2026,'month':10,'day':7}}])
        self.assertEqual(result['latest_interval_end'],stamp)
        self.assertEqual(result['latest_civil_day'],'2026-10-08')
        self.assertIsNone(result['latest_point_time'])


if __name__ == '__main__':
    unittest.main()
