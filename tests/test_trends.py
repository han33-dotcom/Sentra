"""Synthetic trends for #40; no participant data."""
from datetime import date
import unittest

from sentra.trends import group_trend, period_days, personal_trend

END = date(2026, 11, 4)


class PersonalTrendTests(unittest.TestCase):
    def test_gaps_stay_gaps_and_baseline_comes_from_the_board(self):
        person = {'id': 'p90', 'days': [
            {'d': '2026-10-29', 'rhr': 60, 'rhr_b': 55.0},
            {'d': '2026-11-01', 'rhr': 66, 'rhr_b': 55.0, 'f': ['rhr_up']},
            {'d': '2026-11-03', 'rhr': 57},  # no baseline yet that day
            {'d': 'bad', 'rhr': 99}]}
        trend = personal_trend(person, 'rhr', end=END, days=7)
        points = {p['d']: p for p in trend['points']}
        self.assertEqual(len(points), 7)
        self.assertIsNone(points['2026-10-30']['value'])  # missing day is not filled
        self.assertEqual((points['2026-11-01']['difference'], points['2026-11-01']['signal']), (11, True))
        self.assertIsNone(points['2026-11-03']['difference'])
        s = trend['summary']
        self.assertEqual((s['days'], s['days_with_data'], s['days_compared'], s['signal_days']), (7, 3, 2, 1))
        self.assertEqual((s['median'], s['median_baseline'], s['median_difference']), (60, 55, 8))

    def test_person_without_readings_has_no_summary_values(self):
        s = personal_trend({'id': 'p90', 'days': []}, 'steps', end=END, days=14)['summary']
        self.assertEqual((s['days_with_data'], s['median'], s['median_difference'], s['signal_days']), (0, None, None, None))


class GroupTrendTests(unittest.TestCase):
    def people(self, device, n, value, *, start=0):
        return [{'id': f'p{start + i:02d}', 'device': device,
                 'days': [{'d': '2026-11-04', 'hrv': value + i}, {'d': '2026-11-03', 'hrv': value}]
                 if i < 4 else [{'d': '2026-11-04', 'hrv': value + i}]} for i in range(n)]

    def test_each_day_and_device_needs_k_contributors(self):
        people = self.people('WHOOP', 5, 50.0) + self.people('Fitbit', 3, 30.0, start=10)
        trend = group_trend(people, {p['id'] for p in people}, 'hrv', end=END, days=2)
        whoop = {r['d']: r for r in trend['devices']['WHOOP']}
        self.assertEqual((whoop['2026-11-04']['status'], whoop['2026-11-04']['value']), ('available', 52.0))
        self.assertEqual((whoop['2026-11-03']['status'], whoop['2026-11-03']['value']), ('suppressed', None))
        self.assertTrue(all(r['status'] == 'suppressed' for r in trend['devices']['Fitbit']))

    def test_only_eligible_contributors_count(self):
        people = self.people('WHOOP', 6, 50.0)
        trend = group_trend(people, {'p00', 'p01', 'p02', 'p03'}, 'hrv', end=END, days=1)
        self.assertEqual(trend['devices']['WHOOP'][0]['contributors'], 4)
        self.assertEqual(trend['devices']['WHOOP'][0]['status'], 'suppressed')

    def test_period_days_are_oldest_first(self):
        self.assertEqual(period_days(END, 3), ['2026-11-02', '2026-11-03', '2026-11-04'])


if __name__ == '__main__':
    unittest.main()
