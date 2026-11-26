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


class ReviewerPrototypeTests(unittest.TestCase):
    def setUp(self):
        self.html = PAGE.read_text(encoding='utf-8')

    def test_every_field_reference_matches_the_repository(self):
        self.assertEqual(contracts.failures(), [])

    def test_a_broken_reference_is_reported(self):
        broken = [{'id': 'x', 'status': 'in_sentra',
                   'checks': [['mapping', 'google_health', 'sleep', '/sleep/summary/renamed', 'daily_sleep_min'],
                              ['board', 'no_such_key'], ['dataset', 'whoop', 'heart-rate']]}]
        self.assertEqual(len(contracts.failures(broken)), 3)

    def test_page_embeds_the_current_field_map(self):
        embedded = re.search(r'<script id="field-map" type="application/json">(.*?)</script>', self.html, re.S).group(1)
        self.assertEqual(json.loads(embedded), contracts.load(),
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
