"""Synthetic trends for #40; no participant data."""
from datetime import date
import unittest

from sentra.trends import group_trend, period_days, personal_trend, publishable_end
from sentra.processing.pipeline import ASSESSMENT_VERSION

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
        self.assertEqual((points['2026-11-01']['difference'], points['2026-11-01']['state']), (11, 'signal'))
        self.assertIsNone(points['2026-11-03']['difference'])
        s = trend['summary']
        self.assertEqual((s['days'], s['days_with_data'], s['days_compared'], s['signal_days']), (7, 3, 2, 1))
        self.assertEqual(points['2026-10-30']['state'], 'no_data')
        self.assertEqual((s['median'], s['median_baseline'], s['median_difference']), (60, 55, 8))

    def test_person_without_readings_has_no_summary_values(self):
        s = personal_trend({'id': 'p90', 'days': []}, 'steps', end=END, days=14)['summary']
        self.assertEqual((s['days_with_data'], s['median'], s['median_difference'], s['signal_days']), (0, None, None, None))


    def test_unassessed_days_are_never_counted_as_clear(self):
        building = [{'d': f'2026-11-0{i}', 'rhr': 60, 'a': 'partial', 'm': ['rhr:baseline_building']} for i in range(1, 5)]
        trend = personal_trend({'id': 'p90', 'days': building}, 'rhr', end=END, days=7)
        self.assertEqual({p['state'] for p in trend['points']}, {'not_assessed', 'no_data'})
        self.assertEqual((trend['summary']['assessed_days'], trend['summary']['signal_days']), (0, 0))
        mixed = building + [{'d': '2026-10-31', 'rhr': 58, 'lvl': 'green'}]
        s = personal_trend({'id': 'p90', 'days': mixed}, 'rhr', end=END, days=7)['summary']
        self.assertEqual((s['assessed_days'], s['signal_days']), (1, 0))

    def test_older_boards_and_measures_without_rules_give_no_rule_states(self):
        day = [{'d': '2026-11-04', 'rhr': 60, 'lvl': 'green', 'steps': 4000}]
        legacy = personal_trend({'id': 'p90', 'days': day}, 'rhr', end=END, days=7, assessment_version=None)
        self.assertEqual((legacy['summary']['assessed_days'], legacy['points'][-1]['state']), (None, 'unknown'))
        steps = personal_trend({'id': 'p90', 'days': day}, 'steps', end=END, days=7, assessment_version=ASSESSMENT_VERSION)
        self.assertEqual((steps['summary']['assessed_days'], steps['points'][-1]['state']), (None, None))


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
        self.assertEqual((whoop['2026-11-03']['status'], whoop['2026-11-03']['value'],
                          whoop['2026-11-03']['contributors']), ('suppressed', None, None))  # count not returned
        self.assertTrue(all(r['status'] == 'suppressed' for r in trend['devices']['Fitbit']))

    def test_only_eligible_contributors_count(self):
        people = self.people('WHOOP', 6, 50.0)
        trend = group_trend(people, {'p00', 'p01', 'p02', 'p03'}, 'hrv', end=END, days=1)
        self.assertEqual(trend['devices']['WHOOP'][0]['status'], 'suppressed')

    def test_unknown_devices_are_never_pooled(self):
        people = self.people('Unknown', 5, 50.0) + [{**p, 'device': None} for p in self.people('WHOOP', 5, 50.0, start=10)]
        self.assertEqual(group_trend(people, {p['id'] for p in people}, 'hrv', end=END, days=1)['devices'], {})

    def test_window_ends_on_the_latest_publishable_day_only(self):
        people = self.people('WHOOP', 5, 50.0) + [{'id': 'p50', 'device': 'Fitbit', 'days': [{'d': '2026-11-06', 'hrv': 1.0}]}]
        self.assertEqual(publishable_end(people, {p['id'] for p in people}), END)  # p50's later reading is suppressed
        self.assertIsNone(publishable_end(people[:4], {p['id'] for p in people}))

    def test_period_days_are_oldest_first(self):
        self.assertEqual(period_days(END, 3), ['2026-11-02', '2026-11-03', '2026-11-04'])


if __name__ == '__main__':
    unittest.main()
