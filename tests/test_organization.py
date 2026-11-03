"""Synthetic organization overview and profile summaries; no participant data."""
from datetime import date, datetime, timezone
import unittest

from sentra.organization import group_summary, participation, profile

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
        self.assertEqual(rows['hrv']['status'], 'no_data')

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
            people.append({'id': f'p9{i}', 'days': days})
        people.append({'id': 'p99', 'days': [{'d': '2026-10-20', 'sleep': 900}]})  # outside the period
        rows = by_key(group_summary(people, {p['id'] for p in people}, end=END, days=3))
        self.assertEqual(rows['sleep']['contributors'], 5)
        self.assertEqual(rows['sleep']['value'], 400)  # median of each person's [300, 500]

    def test_malformed_values_are_ignored(self):
        people = [person(f'p9{i}', sleep=v) for i, v in enumerate([True, None, 'x', float('nan'), 420])]
        rows = by_key(group_summary(people, {p['id'] for p in people}, end=END))
        self.assertEqual(rows['sleep']['contributors'], 1)


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
        people = [{'id': 'p90', 'days': [{'d': '2026-11-02', 'rhr': 55, 'rhr_b': 54}]},
                  {'id': 'p91', 'days': [{'d': '2026-10-20', 'rhr': 60}]}]
        counts = participation({'p90', 'p91', 'p92', 'p93'}, catalog, people, today=END)
        self.assertEqual(counts, {'enrolled': 4, 'connected': 2, 'recently_contributing': 2, 'assessable': 1,
                                  'recent_days': 3})


class ProfileTests(unittest.TestCase):
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
