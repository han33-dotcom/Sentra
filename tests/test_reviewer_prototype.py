"""Synthetic reviewer prototype: every displayed field traces to Sentra's contracts; no real data."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
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

    def test_sql_check_requires_the_column_on_the_named_table(self):
        check = lambda table, column: contracts.check(['sql', table, column], {}, ROOT)[0]
        self.assertTrue(check('audit.connection_state', 'covered_intervals'))
        self.assertTrue(check('org.current_consent', 'membership_open'))  # a view's output column
        # compressed_bytes is a real column of another table; it must not pass for connection_state.
        self.assertFalse(check('audit.connection_state', 'compressed_bytes'))
        self.assertFalse(check('org.consents', 'membership_open'))
        self.assertFalse(check('audit.no_such_table', 'details'))

    def test_sql_check_applies_later_migrations(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'sql').mkdir()
            (Path(folder) / 'sql' / '001_a.sql').write_text(
                "-- the table's first shape; a comment with a quote\n"
                "create table s.t (a text not null check (a ~ '^[a-z,]+$'), b int, primary key (a));\n"
                "create table s.old (x int);\ncreate table s.gone (y int);\n"
                "create function s.f() returns void language plpgsql as $$ begin create table s.fake (z int); end $$;\n",
                encoding='utf-8')
            (Path(folder) / 'sql' / '002_b.sql').write_text(
                "alter table s.t add column c jsonb, drop column b, rename column a to a2;\n"
                "alter table s.t add constraint t_c check (c is not null);\n"
                "alter table s.old rename to renamed;\ndrop table if exists s.gone;\n"
                "create view s.v with (security_invoker=true) as select t.a2, t.c as payload, now() as seen from s.t;\n",
                encoding='utf-8')
            found = contracts.schema(folder)
        self.assertEqual(found['s.t'], {'a2', 'c'})
        self.assertEqual(found['s.renamed'], {'x'})
        self.assertEqual(found['s.v'], {'a2', 'payload', 'seen'})
        for missing in ('s.old', 's.gone', 's.fake'):
            self.assertNotIn(missing, found)

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

    def test_walkthrough_scenarios(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is not installed')
        run = subprocess.run([node, str(ROOT / 'tests' / 'reviewer_prototype_walkthrough.cjs'), str(PAGE)],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('FAIL', run.stdout)


def _live_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location('reviewer_live_check', ROOT / 'scripts' / 'reviewer_live_check.py')
    live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live)
    return live


def _consent(pid, org='org-a', sharing='group_only', withdrawn=False, demonstration=False):
    return {'participant_id': pid, 'org_id': org, 'sharing': sharing, 'withdrawn': withdrawn,
            'membership_open': True, 'demonstration': demonstration}


class ReviewerLiveCheckTests(unittest.TestCase):
    """The operator check prints only small-group-suppressed aggregates for one organization."""

    def setUp(self):
        self.live = _live_check()
        fitbit = [f'p7{i}' for i in range(6)]  # six Fitbit contributors in org-a
        self.consents = ([_consent(p, sharing='individual' if i < 3 else 'group_only', demonstration=i == 0)
                          for i, p in enumerate(fitbit)]
                         + [_consent('p80'),                                    # the only WHOOP contributor
                            _consent('p81', withdrawn=True),                    # withdrawn: out of scope
                            _consent('p82', org='org-b', sharing='individual')])  # another organization

        def days(n, **values):
            return [{'d': f'2026-11-{20 + i:02d}', **values} for i in range(n)]
        self.board = {'built_at': '2026-11-26T01:30:00+02:00', 'data_through': '2026-11-25', 'people': (
            [{'id': p, 'device': 'Fitbit', 'days': days(4, sleep=400 + i, steps=0, lvl=None, rhr=None if i else 57)}
             for i, p in enumerate(fitbit)]
            + [{'id': 'p80', 'device': 'WHOOP', 'days': days(3, rec=81, hrv=61.5, lvl='green')},
               {'id': 'p81', 'device': 'WHOOP', 'days': days(3, rec=12)},
               {'id': 'p82', 'device': 'WHOOP', 'days': days(3, rec=13)}])}
        self.catalog = ([{'participant_id': p, 'provider': 'google_health', 'dataset': 'sleep',
                          'authorization_status': 'authorized', 'measurement_rows': 40,
                          'latest_civil_day': f'2026-11-{19 + i}'} for i, p in enumerate(fitbit)]
                        + [{'participant_id': 'p80', 'provider': 'whoop', 'dataset': 'sleep',
                            'authorization_status': 'revoked', 'measurement_rows': 9, 'latest_civil_day': '2026-11-02'}])
        self.detail = ([{'provider': 'google_health', 'dataset': 'sleep', 'participant_id': p, 'person_days': 10 + i,
                         'first_day': f'2026-10-0{1 + i}', 'last_day': f'2026-11-{19 + i}', 'unplaced_rows': 0,
                         'stage_rows': 30 if i == 0 else 0} for i, p in enumerate(fitbit)]
                       + [{'provider': 'whoop', 'dataset': 'sleep', 'participant_id': 'p80', 'person_days': 3,
                           'first_day': '2026-11-01', 'last_day': '2026-11-03', 'unplaced_rows': 2, 'stage_rows': 0}])

    def summary(self, **changes):
        args = dict(board=self.board, catalog=self.catalog, consents=self.consents, detail_rows=self.detail,
                    coverage_rows=[], failure_rows=[], org_id='org-a')
        args.update(changes)
        return self.live.summarize(**args)

    def test_output_has_no_ids_readings_or_out_of_scope_people(self):
        text = json.dumps(self.summary())
        for leaked in ('p7', 'p80', 'p81', 'p82', '61.5', '"81"', '400', '401', '2026-11-02', 'org-b'):
            self.assertNotIn(leaked, text)

    def test_one_person_device_group_is_withheld(self):
        s = self.summary()
        self.assertEqual(s['board']['by_device']['WHOOP'], {'people': 'fewer than 5'})
        self.assertEqual(s['datasets']['whoop sleep'],
                         {'people_with_rows': 'fewer than 5', 'authorization': {'revoked': 'fewer than 5'}})
        self.assertNotIn('whoop sleep', s['detail'])

    def test_undated_rows_count_distinct_people_and_hide_subthreshold_changes(self):
        baseline = self.summary()
        rows = [dict(row) for row in self.detail]
        for row in rows[:4]:
            row['unplaced_rows'] = 19
        self.assertEqual(self.summary(detail_rows=rows), baseline)
        rows[4]['unplaced_rows'] = 1
        self.assertEqual(self.summary(detail_rows=rows)['detail']['google_health sleep']['people_with_undated_rows'], 5)
        undated = dict(rows[0], dataset='daily_steps', person_days=0, stage_rows=0)
        self.assertEqual(self.summary(detail_rows=self.detail + [undated] * 5), baseline)

    def test_global_data_through_cannot_change_the_report(self):
        self.assertEqual(self.summary(), self.summary(board=dict(self.board, data_through='2099-01-01')))

    def test_null_values_are_not_counted_and_zero_is(self):
        fields = self.summary()['board']['by_device']['Fitbit']['fields']
        self.assertEqual(fields['lvl'], {'people': 'fewer than 5'})   # lvl: null on every day (unassessed)
        self.assertEqual(fields['rhr'], {'people': 'fewer than 5'})   # only one person has a value
        self.assertEqual(fields['steps'], {'people': 6, 'share_of_days': 1.0})  # zero is a reading
        self.assertEqual(fields['sleep'], {'people': 6, 'share_of_days': 1.0})

    def test_dates_are_reached_by_five_people(self):
        s = self.summary()
        self.assertEqual(s['datasets']['google_health sleep']['latest_day_reached_by_5'], '2026-11-20')
        sleep = s['detail']['google_health sleep']
        self.assertEqual((sleep['first_day_reached_by_5'], sleep['latest_day_reached_by_5']), ('2026-10-05', '2026-11-20'))
        self.assertEqual(sleep['person_days'], sum(range(10, 16)))
        self.assertEqual(s['board']['by_device']['Fitbit']['median_days_per_person'], 4)

    def test_consent_counts_are_scoped_and_suppressed(self):
        self.assertEqual(self.summary()['consent'], {'current': 7, 'individual': 'fewer than 5', 'group_only': 'fewer than 5',
                                                     'demonstration': 'fewer than 5', 'not_current': 'fewer than 5'})
        self.assertEqual(self.summary(org_id='org-b')['scope']['contributors'], 'fewer than 5')

    def test_hosted_configuration_is_refused(self):
        from sentra.errors import SentraError
        with tempfile.TemporaryDirectory() as folder:
            hosted = Path(folder) / 'secrets.toml'
            hosted.write_text('[viewer]\nurl = "x"\n[auth]\nredirect_uri = "x"\n', encoding='utf-8')
            with self.assertRaises(SentraError):
                self.live.load_operator_settings(hosted, folder)

    def test_transfer_cap_stops_before_reserving(self):
        from sentra.shared import CapacityStop
        reserved = []
        reader = type('Reader', (), {'reserve': lambda self, n: reserved.append(n)})()
        spent = self.live.budgeted(reader, 1000)
        reader.reserve(600)
        with self.assertRaises(CapacityStop):
            reader.reserve(500)
        self.assertEqual((reserved, spent[0]), ([600], 600))

    def test_day_basis_follows_processing(self):
        basis = self.live.dataset_basis()
        self.assertEqual((basis[('google_health', 'sleep')], basis[('whoop', 'sleep')]), ('end', 'end'))
        self.assertEqual((basis[('whoop', 'cycle')], basis[('whoop', 'recovery')]), ('start', 'start'))
        self.assertEqual(basis[('google_health', 'daily-resting-heart-rate')], 'civil')
        sql = self.live.day_sql()
        record = 'over (partition by m.participant_id,m.provider,m.dataset,m.record_key)'
        self.assertIn(f"when m.provider='google_health' and m.dataset='sleep' then to_char(max(m.interval_end) {record} at time zone 'Asia/Beirut'", sql)
        self.assertIn(f"when m.provider='whoop' and m.dataset='recovery' then to_char(min(m.interval_start) {record}", sql)
        self.assertIn('count(*) filter (where day is null) unplaced_rows', self.live.detail_sql('audit.measurements'))


URL = __import__('os').environ.get('SENTRA_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'set SENTRA_TEST_DATABASE_URL to a throwaway PostgreSQL server to run')
class ReviewerLiveCheckDatabaseTests(unittest.TestCase):
    """detail_sql on a real PostgreSQL server: documented day basis, unknown days excluded."""

    def test_person_days_use_the_documented_day(self):
        import psycopg
        from psycopg.rows import dict_row
        live = _live_check()
        with psycopg.connect(URL, autocommit=True) as db:
            db.execute('''create temporary table m (participant_id text, provider text, dataset text, record_key text,
                metric text, measured_at timestamptz, interval_start timestamptz, interval_end timestamptz, civil_date jsonb)''')
            db.execute('''insert into m values
              -- overnight sleep 23:10 -> 06:55 Beirut belongs to its wake day, 21 Nov; so does its
              -- first stage row, whose own interval ends before midnight
              ('p01','google_health','sleep','s1','/sleep/summary/minutesAsleep',null,'2026-11-20 21:10+00','2026-11-21 04:55+00',null),
              ('p01','google_health','sleep','s1','/sleep/stages/0/type',null,'2026-11-20 21:10+00','2026-11-20 21:40+00',null),
              -- civil-date-only daily summaries keep their civil date (object and string forms)
              ('p01','google_health','daily_steps','d1','/steps/countSum',null,null,null,'{"year":2026,"month":11,"day":3}'),
              ('p01','google_health','daily_steps','d2','/steps/countSum',null,null,null,'"2026-11-04"'),
              -- no placeable day: never a person-day
              ('p01','google_health','daily_steps','d3','/steps/countSum',null,null,null,null),
              -- WHOOP cycle starting 23:30 Beirut on 21 Nov belongs to its start day
              ('p01','whoop','cycle','c1','/score/strain',null,'2026-11-21 21:30+00','2026-11-22 19:00+00',null),
              -- an intraday point at 00:30 Beirut on 23 Nov (22:30 UTC on 22 Nov)
              ('p01','google_health','original_heart-rate','h1','/heartRate/beatsPerMinute','2026-11-22 22:30+00',null,null,null)''')
            with db.cursor(row_factory=dict_row) as cursor:
                cursor.execute(live.detail_sql('m'), (['sleep', 'daily_steps', 'cycle', 'original_heart-rate'], ['p01'], 100))
                rows = {(r['provider'], r['dataset']): r for r in cursor.fetchall()}
        self.assertEqual((rows['google_health', 'sleep']['first_day'], rows['google_health', 'sleep']['person_days'],
                          rows['google_health', 'sleep']['stage_rows']), ('2026-11-21', 1, 1))
        steps = rows['google_health', 'daily_steps']
        self.assertEqual((steps['person_days'], steps['first_day'], steps['last_day'], steps['unplaced_rows']),
                         (2, '2026-11-03', '2026-11-04', 1))
        self.assertEqual(rows['whoop', 'cycle']['first_day'], '2026-11-21')
        self.assertEqual(rows['google_health', 'original_heart-rate']['first_day'], '2026-11-23')


if __name__ == '__main__':
    unittest.main()
