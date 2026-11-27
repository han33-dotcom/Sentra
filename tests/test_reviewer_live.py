"""Reviewer page with real data: server-built payload, suppression and the page's live mode (synthetic rows)."""
from datetime import date
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from sentra.processing.board import FLAGS
from sentra.reviewer.live import DATA_TAG, PAGE, payload, render

ROOT = Path(__file__).resolve().parents[1]
DAYS = [f'2026-11-{d:02d}' for d in range(10, 25) if d != 20]  # 20 Nov has no published row


def fitbit_day(d, i, steps=False):
    row = {'d': d, 'lvl': 'green', 'sleep': 420 + i, 'sleep_b': 420, 'rhr': 57 + i, 'rhr_b': 58, 'hrv': 40.5, 'hrv_b': 41.0}
    if steps:
        row['steps'] = 8000 + i
    return row


def person(pid, device='Fitbit', steps=False, i=0):
    days = [fitbit_day(d, i, steps) for d in DAYS]
    return {'id': pid, 'name': pid, 'device': device, 'days': days}


P91 = person('p91', steps=True)
P91['days'][-1].update(sleep=300, f=['short_sleep'], lvl='amber')          # 24 Nov: a short night
P91['days'][0].update(sleep='abc', m='not-a-list')                          # malformed values are dropped
P101 = {'id': 'p101', 'name': 'p101', 'device': 'WHOOP',
        'days': [{'d': d, 'lvl': None, 'a': 'partial', 'm': ['hrv:baseline_building'], 'sleep': 410, 'rec': 70,
                  'rhr': 55, 'hrv': 60.2, 'strain': 11.5} for d in DAYS]}
GROUP = [P91, person('p92', steps=True, i=1), person('p93', i=2), person('p94', i=3), person('p95', i=4),
         person('p96', i=5), P101]
CONTRIBUTORS = {'p91', 'p92', 'p93', 'p94', 'p95', 'p101'}  # p96 belongs to another organization
BOARD = {'built_at': '2026-11-25T01:31:00+02:00', 'data_through': '2026-11-24', 'thresholds_status': 'v0',
         'assessment_version': 'assessment-v1', 'board_version': 'board-2', 'people': [P91, P101]}
CATALOG = [{'participant_id': 'p91', 'provider': 'google_health', 'dataset': 'sleep',
            'latest_interval_end': '2026-11-24T04:55:00+00:00'},
           {'participant_id': 'p101', 'provider': 'whoop', 'dataset': 'recovery', 'latest_civil_day': '2026-11-24'}]


def build(**changes):
    args = dict(board=BOARD, people=[P91, P101, {'id': '<script>', 'days': []}, {'id': 'x1', 'days': []}],
                group_people=GROUP, contributors=CONTRIBUTORS, catalog=CATALOG, today=date(2026, 11, 25),
                viewer='org-a · officer')
    args.update(changes)
    return payload(**args)


class ReviewerPayloadTests(unittest.TestCase):
    def test_rows_are_only_individually_visible_people(self):
        data = build()
        self.assertEqual([p['id'] for p in data['people']], ['p101', 'p91'])
        text = json.dumps(data)
        for hidden in ('p92', 'p93', 'p94', 'p95', 'p96', '<script>', '"x1"'):
            self.assertNotIn(hidden, text)

    def test_board_values_pass_through_and_malformed_values_are_dropped(self):
        p91 = next(p for p in build()['people'] if p['id'] == 'p91')
        first, last = p91['days'][0], p91['days'][-1]
        self.assertNotIn('sleep', first)
        self.assertNotIn('m', first)
        self.assertEqual((last['sleep'], last['sleep_b'], last['f'], last['lvl']), (300, 420, ['short_sleep'], 'amber'))
        self.assertNotIn('2026-11-20', {d['d'] for d in p91['days']})  # missing stays missing
        self.assertEqual(p91['latest'], {'Fitbit': '2026-11-24T04:55:00+00:00'})

    def test_group_figures_are_medians_suppressed_below_five_without_counts(self):
        group = build()['group']
        self.assertEqual(group['end'], '2026-11-24')
        tiles = {(t['key'], t['device']): t for t in group['tiles']}
        self.assertEqual(tiles['rhr', 'Fitbit'], {'key': 'rhr', 'device': 'Fitbit', 'value': 59, 'contributors': 5})
        self.assertNotIn(('steps', 'Fitbit'), tiles)
        self.assertNotIn(('rhr', 'WHOOP'), tiles)
        for key, devices in group['trends'].items():
            for rows in devices.values():
                self.assertTrue(all(set(r) == {'d', 'value'} for r in rows), key)  # values only, never counts
        self.assertNotIn('Fitbit', group['trends']['steps'])
        # The other organization's person never counts, even when its rows are passed in.
        self.assertEqual(tiles['sleep', 'Fitbit']['contributors'], 5)

    def test_no_group_window_without_a_publishable_statistic(self):
        self.assertEqual(build(contributors={'p91'})['group'], {'end': None, 'tiles': [], 'trends': {}})

    def test_unpublishable_device_and_global_cutoff_leave_payload_unchanged(self):
        fitbit = [p for p in GROUP if p['device'] == 'Fitbit']
        baseline = build(people=[], group_people=fitbit, contributors=CONTRIBUTORS - {'p101'})
        whoop = dict(P101, days=P101['days'] + [dict(P101['days'][-1], d='2026-11-25')])
        self.assertEqual(build(people=[], group_people=fitbit + [whoop],
                               board=dict(BOARD, data_through='2026-11-25')), baseline)

    def test_render_embeds_data_that_cannot_close_the_script(self):
        page = render(build(viewer='</script><b>x</b><!--'))
        self.assertEqual(page.count('<script id="reviewer-data" type="application/json">'), 1)
        self.assertNotIn('</script><b>', page)
        embedded = re.search(r'<script id="reviewer-data" type="application/json">(.*?)</script>', page, re.S).group(1)
        self.assertNotIn('<', embedded)
        self.assertEqual(json.loads(embedded)['viewer'], '</script><b>x</b><!--')
        self.assertIn(DATA_TAG, PAGE.read_text(encoding='utf-8'))  # the shipped page stays in demo mode

    def test_page_names_every_board_flag(self):
        text = PAGE.read_text(encoding='utf-8')
        flags = set(re.findall(r'(\w+):\[\'(?:sleep|rhr|hrv|sleep_hr)\',', re.search(r'const FLAG_TEXT=\{(.*?)\};', text).group(1)))
        self.assertEqual(flags, set(FLAGS.values()))

    def test_live_walkthrough(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is not installed')
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / 'reviewer.html'
            page.write_text(render(build()), encoding='utf-8')
            run = subprocess.run([node, str(ROOT / 'tests' / 'reviewer_live_walkthrough.cjs'), str(page)],
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)


if __name__ == '__main__':
    unittest.main()
