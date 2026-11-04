"""Synthetic organization overview and profile summaries; no participant data."""
from datetime import date, datetime, timezone
import unittest

from sentra.organization import group_summary, participation, profile, shown_count, team_scope
from sentra.processing.pipeline import ASSESSMENT_VERSION

END = date(2026, 11, 3)


def person(pid, **values):
    return {'id': pid, 'device': 'WHOOP', 'days': [{'d': END.isoformat(), **values}]}


def by_key(rows):
    return {r['key']: r for r in rows}


class GroupSummaryTests(unittest.TestCase):
    def test_each_statistic_needs_five_contributors_of_its_own(self):
        people = [person(f'p9{i}', sleep=400 + i, rhr=55 + i) for i in range(5)]
        people[4]['days'][0].pop('rhr')  # only four people supplied resting heart rate
        rows = by_key(group_summary(people, {p['id'] for p in people}, end=END))
        self.assertEqual((rows['sleep']['status'], rows['sleep']['contributors'], rows['sleep']['value']),
                         ('available', 5, 402))
        self.assertEqual((rows['rhr']['status'], rows['rhr']['contributors'], rows['rhr']['value']),
                         ('suppressed', 4, None))
        self.assertIn('Fewer than 5', rows['rhr']['reason'])
        self.assertNotIn('4', rows['rhr']['reason'])  # the exact small count is not repeated in the note
        self.assertEqual(rows['hrv']['status'], 'no_data')

    def test_devices_are_never_pooled(self):
        people = [person(f'p9{i}', hrv=50.0) for i in range(5)]
        people += [{**person(f'p8{i}', hrv=30.0), 'device': 'Fitbit'} for i in range(3)]
        rows = [r for r in group_summary(people, {p['id'] for p in people}, end=END) if r['key'] == 'hrv']
        self.assertEqual([(r['device'], r['status'], r['contributors'], r['value']) for r in rows],
                         [('Fitbit', 'suppressed', 3, None), ('WHOOP', 'available', 5, 50.0)])

    def test_small_counts_are_shown_only_as_below_k(self):
        self.assertEqual([shown_count(n) for n in (0, 1, 4, 5, 12)], ['0', '<5', '<5', '5', '12'])

    def test_only_eligible_contributors_count(self):
        people = [person(f'p9{i}', steps=1000 * i) for i in range(6)]
        eligible = {'p90', 'p91', 'p92', 'p93'}  # p94/p95: other organization or withdrawn
        rows = by_key(group_summary(people, eligible, end=END))
        self.assertEqual(rows['steps']['status'], 'suppressed')
        self.assertEqual(rows['steps']['contributors'], 4)

    def test_one_value_per_person_over_the_period_and_no_gap_filling(self):
        people = []
        for i in range(5):
            days = [{'d': '2026-11-01', 'sleep': 300}, {'d': '2026-11-02'}, {'d': END.isoformat(), 'sleep': 500}]
            people.append({'id': f'p9{i}', 'device': 'WHOOP', 'days': days})
        people.append({'id': 'p99', 'days': [{'d': '2026-10-20', 'sleep': 900}]})  # outside the period
        rows = by_key(group_summary(people, {p['id'] for p in people}, end=END, days=3))
        self.assertEqual(rows['sleep']['contributors'], 5)
        self.assertEqual(rows['sleep']['value'], 400)  # median of each person's [300, 500]

    def test_malformed_values_are_ignored(self):
        people = [person(f'p9{i}', sleep=v) for i, v in enumerate([True, None, 'x', float('nan'), 420])]
        rows = by_key(group_summary(people, {p['id'] for p in people}, end=END))
        self.assertEqual(rows['sleep']['contributors'], 1)


    def test_unknown_devices_are_left_out_of_group_statistics(self):
        people = [{**person(f'p9{i}', sleep=400), 'device': device} for i, device in enumerate(['Unknown'] * 5 + [None] * 5)]
        self.assertEqual(by_key(group_summary(people, {p['id'] for p in people}, end=END))['sleep']['status'], 'no_data')


class ParticipationTests(unittest.TestCase):
    def test_states_are_counted_separately(self):
        catalog = [
            {'participant_id': 'p90', 'provider': 'whoop', 'dataset': 'sleep', 'authorization_status': 'authorized',
             'latest_interval_end': datetime(2026, 11, 2, 5, tzinfo=timezone.utc)},
            {'participant_id': 'p91', 'provider': 'whoop', 'dataset': 'sleep', 'authorization_status': 'authorized',
             'latest_interval_end': datetime(2026, 10, 20, 5, tzinfo=timezone.utc)},
            {'participant_id': 'p92', 'provider': 'google_health', 'dataset': 'daily_steps',
             'authorization_status': 'reconnect_required', 'latest_civil_day': '2026-11-03'},
            {'participant_id': 'p77', 'provider': 'whoop', 'dataset': 'sleep', 'authorization_status': 'authorized',
             'latest_interval_end': datetime(2026, 11, 3, 5, tzinfo=timezone.utc)},  # outside scope
        ]
        people = [{'id': 'p90', 'days': [{'d': '2026-11-02', 'rhr': 55, 'rhr_b': 54, 'lvl': 'green'}]},
                  {'id': 'p91', 'days': [{'d': '2026-10-20', 'rhr': 60}]}]
        counts = participation({'p90', 'p91', 'p92', 'p93'}, catalog, people, today=END,
                               assessment_version=ASSESSMENT_VERSION)
        self.assertEqual(counts, {'enrolled': 4, 'connected': 2, 'recently_contributing': 2, 'assessable': 1,
                                  'recent_days': 3})

    def test_assessable_requires_a_recent_complete_current_version_day(self):
        people = [
            person('p90', lvl='green'),
            person('p91', lvl='amber', a='partial', rhr_b=54),
            person('p92', lvl='red', a='partial'),
            person('p93', lvl=None, a='insufficient', steps_b=6000),
            {'id': 'p94', 'days': [{'d': '2026-10-20', 'lvl': 'green', 'rhr_b': 54}]},
            {'id': 'p95', 'days': [{'d': '2026-11-04', 'lvl': 'green'}]},
            {'id': 'p96', 'days': [{'d': '2026-10-31', 'lvl': 'red'}]},
            {'id': 'p97', 'days': [{'d': '2026-11-03', 'a': 'partial', 'lvl': 'amber'},
                                 {'d': '2026-11-02', 'lvl': 'green'}]},  # latest day is incomplete
            person('p98', lvl='green'),  # outside scope
        ]
        scope = {f'p9{i}' for i in range(8)}
        result = lambda version: participation(scope, [], people, today=END, assessment_version=version)
        self.assertEqual(result(ASSESSMENT_VERSION)['assessable'], 2)
        for version in (None, 'old-version'):
            self.assertEqual(result(version)['assessable'], 0)


class TeamScopeTests(unittest.TestCase):
    def test_withdrawn_participants_leave_the_team_view(self):
        consents = [{'participant_id': 'p90', 'org_id': 'org-a', 'sharing': 'group_only', 'withdrawn': False,
                     'membership_open': True},
                    {'participant_id': 'p91', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': True,
                     'membership_open': True},
                    {'participant_id': 'p92', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': False,
                     'membership_open': False}]
        enrolled, included = team_scope({'p90', 'p91', 'p92', 'p93'}, consents)
        self.assertEqual(enrolled, {'p90'})
        self.assertEqual(included, {'p90', 'p93'})  # p93: pilot data, no consent record


class ProfileTests(unittest.TestCase):
    def test_malformed_dates_are_skipped_not_fatal(self):
        days = [{'d': '2026-11-01', 'sleep': 400}, {'d': '2026-11-1', 'sleep': 1}, {'d': ''}, {'d': '2026-13-02'}]
        p = profile({'id': 'p90', 'days': days}, today=END)
        self.assertEqual((p['data_through'], p['days_with_data_last_7']), (date(2026, 11, 1), 1))
        self.assertEqual(by_key(p['metrics'])['sleep']['value'], 400)
        people = [{'id': f'p9{i}', 'device': 'Fitbit', 'days': [{'d': END.isoformat(), 'sleep': 400}, {'d': 'x', 'sleep': 1}]}
                  for i in range(5)]
        self.assertEqual(by_key(group_summary(people, {p['id'] for p in people}, end=END))['sleep']['value'], 400)

    def test_latest_values_against_own_baseline_and_explicit_gaps(self):
        days = [{'d': '2026-10-30', 'sleep': 300},
                {'d': '2026-11-02', 'sleep': 420, 'sleep_b': 400, 'rhr': 58, 'steps': 5000, 'steps_b': 6000}]
        p = profile({'id': 'p90', 'device': 'Fitbit', 'days': days}, today=END)
        m = by_key(p['metrics'])
        self.assertEqual((p['data_through'], p['days_old'], p['days_with_data_last_7']), (date(2026, 11, 2), 1, 2))
        self.assertEqual((m['sleep']['value'], m['sleep']['baseline'], m['sleep']['difference']), (420, 400, 20))
        self.assertEqual(m['steps']['difference'], -1000)
        self.assertIn('Not enough history', m['rhr']['note'])
        self.assertIn('Not supplied', m['hrv']['note'])
        self.assertIsNone(m['hrv']['value'])

    def test_person_without_days_has_no_values(self):
        p = profile({'id': 'p90', 'days': []}, today=END)
        self.assertIsNone(p['data_through'])
        self.assertTrue(all(row['value'] is None for row in p['metrics']))


if __name__ == '__main__':
    unittest.main()
