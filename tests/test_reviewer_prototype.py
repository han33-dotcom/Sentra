"""Synthetic reviewer prototype: every displayed field traces to Sentra's contracts; no real data."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from sentra.processing.pipeline import MIN_SCALE, TH
from sentra.reviewer import contracts

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'src' / 'sentra' / 'reviewer' / 'prototype.html'
FIELD_MAP = ROOT / 'src' / 'sentra' / 'reviewer' / 'field_map.json'


class ReviewerPrototypeTests(unittest.TestCase):
    def setUp(self):
        self.html = PAGE.read_text(encoding='utf-8')

    def test_every_field_reference_matches_the_repository(self):
        self.assertEqual(contracts.failures(root=ROOT), [])

    def test_a_broken_reference_is_reported(self):
        broken = [{'id': 'x', 'status': 'in_sentra',
                   'checks': [['mapping', 'google_health', 'sleep', '/sleep/summary/renamed', 'daily_sleep_min'],
                              ['board', 'no_such_key'], ['dataset', 'whoop', 'heart-rate']]}]
        self.assertEqual(len(contracts.failures(broken, root=ROOT)), 3)

    def test_page_embeds_the_current_field_map(self):
        embedded = re.search(r'<script id="field-map" type="application/json">(.*?)</script>', self.html, re.S).group(1)
        self.assertEqual(json.loads(embedded), contracts.load(FIELD_MAP),
                         'Run python scripts/build_reviewer_prototype.py after editing field_map.json')

    def test_page_rules_match_processing(self):
        th = re.search(r'const TH=\{short:(\d+),z:([\d.]+),baseDays:(\d+),baseMin:(\d+),k:(\d+)\}', self.html)
        self.assertEqual(tuple(float(v) for v in th.groups()),
                         (TH['short_sleep_minutes'], TH['z_alert'], TH['baseline_days'], TH['baseline_min_days'],
                          TH['cohort_k_anonymity']))
        floor = dict(re.findall(r'(\w+):([\d.]+)', re.search(r'const FLOOR=\{(.*?)\}', self.html).group(1)))
        self.assertEqual({'sleep': MIN_SCALE['sleep_min'], 'rhr': MIN_SCALE['rhr'], 'hrv': MIN_SCALE['daily_hrv_rmssd'],
                          'sleep_hr': MIN_SCALE['sleep_hr']}, {k: float(v) for k, v in floor.items()})

    def test_page_is_labelled_synthetic_and_loads_nothing_but_fonts(self):
        self.assertIn('Synthetic prototype', self.html)
        self.assertIn('Every person, name and reading here is fictional', self.html)
        self.assertEqual(re.findall(r'<script[^>]+src=', self.html), [])
        self.assertEqual({h for h in re.findall(r'https://([\w.]+)/', self.html)
                          if not h.endswith('googleapis.com') and not h.endswith('gstatic.com')}, set())

    def test_live_check_summary_is_aggregate_only(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('live_check', ROOT / 'scripts' / 'reviewer_live_check.py')
        live = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live)
        board = {'built_at': '2026-11-26T13:00:00+00:00', 'data_through': '2026-11-24', 'people': [
            {'id': 'p71', 'device': 'Fitbit', 'days': [{'d': '2026-11-23', 'sleep': 401, 'rhr': 58, 'f': ['short_sleep']},
                                                     {'d': '2026-11-24', 'rhr': 57}]},
            {'id': 'p72', 'device': 'WHOOP', 'days': [{'d': '2026-10-30', 'rec': 81, 'hrv': 61.5}]}]}
        catalog = [{'participant_id': 'p71', 'provider': 'google_health', 'dataset': 'sleep', 'authorization_status': 'authorized',
                    'measurement_rows': 40, 'latest_civil_day': '2026-11-24'}]
        consents = [{'participant_id': 'p71', 'sharing': 'individual', 'withdrawn': False, 'membership_open': True,
                     'demonstration': True}, {'participant_id': 'p72', 'sharing': 'group_only', 'withdrawn': True,
                                              'membership_open': False, 'demonstration': False}]
        summary = live.summarize(board, catalog, consents, [], [], [])
        text = json.dumps(summary)
        for leaked in ('p71', 'p72', '401', '61.5', '"81"'):
            self.assertNotIn(leaked, text)
        self.assertEqual(summary['board']['people_by_device'], {'Fitbit': 1, 'WHOOP': 1})
        self.assertEqual(summary['board']['fields']['sleep']['Fitbit'], {'people': 1, 'share_of_days': 0.5})
        self.assertEqual(summary['consent'], {'current': 1, 'sharing': {'individual': 1}, 'demonstration': 1,
                                              'withdrawn_or_closed': 1})
        self.assertEqual(summary['datasets']['google_health sleep']['people_with_rows'], 1)

    def test_walkthrough_scenarios(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is not installed')
        run = subprocess.run([node, str(ROOT / 'tests' / 'reviewer_prototype_walkthrough.cjs'), str(PAGE)],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)


if __name__ == '__main__':
    unittest.main()
