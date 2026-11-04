"""Synthetic observation wording for #41; no participant data."""
from datetime import date
import unittest

from sentra.observations import observations
from sentra.processing.pipeline import ASSESSMENT_VERSION

TODAY = date(2026, 11, 4)


def observe(*days, today=TODAY, version=ASSESSMENT_VERSION):
    return observations({'id': 'p90', 'days': list(days)}, today=today, assessment_version=version)


class ObservationTests(unittest.TestCase):
    def test_signal_explains_what_changed_and_which_readings(self):
        obs = observe({'d': '2026-11-03', 'lvl': 'amber', 'f': ['rhr_up'], 'rhr': 64, 'rhr_b': 55.0, 'rhr_z': 2.4})
        self.assertEqual([(o['kind'], o['title']) for o in obs], [('wellness', 'Resting heart rate above your normal')])
        self.assertEqual(obs[0]['readings'], [('This day (rounded)', '64 bpm'), ('Usual (own baseline)', '55 bpm'),
                                              ('Difference from usual variation', '+2.4 × usual variation')])
        self.assertTrue(any('Provisional' in x for x in obs[0]['limitations']))
        self.assertTrue(any('not a medical conclusion' in x for x in obs[0]['limitations']))

    def test_partial_signal_keeps_its_limits_visible(self):
        obs = observe({'d': '2026-11-03', 'lvl': 'amber', 'a': 'partial', 'f': ['short_sleep'], 'sleep': 300,
                       'm': ['hrv:baseline_building', 'sleep_hr:no_reading']})
        self.assertEqual([o['kind'] for o in obs], ['wellness', 'assessment'])
        self.assertIn(('Rule', 'less than 360 min asleep'), obs[0]['readings'])
        self.assertIn('Not checked: Heart-rate variability: personal normal still building', obs[0]['limitations'][2])
        self.assertEqual(obs[1]['title'], 'Partial assessment')
        self.assertIn('Sleeping heart rate: no reading for this day', obs[1]['limitations'])

    def test_missing_data_is_never_a_calm_result(self):
        obs = observe({'d': '2026-11-03', 'a': 'insufficient', 'm': ['sleep:no_reading', 'rhr:no_reading']})
        self.assertEqual([(o['kind'], o['title']) for o in obs], [('assessment', 'Not enough information')])
        self.assertFalse(any(o['title'] == 'No change from usual pattern' for o in obs))

    def test_complete_green_says_which_rules_were_checked(self):
        obs = observe({'d': '2026-11-04', 'lvl': 'green'})
        self.assertEqual(obs[0]['title'], 'No change from usual pattern')
        self.assertIn('sleep, resting heart rate, heart-rate variability', obs[0]['detail'])

    def test_collection_problems_are_separate_from_wellness(self):
        self.assertEqual(observe()[0]['title'], 'No published days yet')

    def test_stale_or_future_days_get_no_calm_conclusion(self):
        for day, title in (({'d': '2026-10-20', 'lvl': 'green'}, 'No recent data'),
                           ({'d': '2026-10-20', 'lvl': 'amber', 'f': ['rhr_up']}, 'No recent data'),
                           ({'d': '2026-11-05', 'lvl': 'green'}, 'Date in the future'),
                           ({'d': '2026-11-05', 'lvl': 'red', 'f': ['rhr_up', 'hrv_down']}, 'Date in the future')):
            with self.subTest(day=day):
                obs = observe(day)
                self.assertEqual([(o['kind'], o['title']) for o in obs], [('collection', title)])
        self.assertIn('15 days old', observe({'d': '2026-10-20', 'lvl': 'green'})[0]['detail'])

    def test_rule_boundary_from_the_real_board_producer_is_labelled_rounded(self):
        import pandas as pd
        from sentra.processing.board import payload
        daily = pd.DataFrame([{'subject_id': 'p90', 'date': pd.Timestamp('2026-11-03'), 'usable_day': True,
                               'wellness_level': 'amber', 'assessment_state': 'complete', 'sleep_min': 359.6,
                               'flag_short_sleep': True}])
        board = payload(daily, {'p90': 'whoop'}, built_at='2026-11-04T00:00:00Z')
        obs = observations(board['people'][0], today=TODAY, assessment_version=board['assessment_version'])
        self.assertEqual(obs[0]['title'], 'Slept less than 6 hours')
        self.assertIn(('This day (rounded)', '360 min'), obs[0]['readings'])
        self.assertIn('the rule was checked on the unrounded value', ' '.join(obs[0]['limitations']))

    def test_sleeping_heart_rate_says_its_variation_is_not_published(self):
        obs = observe({'d': '2026-11-03', 'lvl': 'amber', 'f': ['sleep_hr_up'], 'sleep_hr': 61, 'sleep_hr_b': 54.0})
        self.assertIn('not published for sleeping heart rate', ' '.join(obs[0]['limitations']))

    def test_board_from_older_rules_shows_no_levels(self):
        obs = observe({'d': '2026-11-04', 'lvl': 'green', 'f': ['rhr_up']}, version=None)
        self.assertEqual([(o['kind'], o['title']) for o in obs], [('collection', 'Published under older rules')])

    def test_a_level_is_never_left_unexplained(self):
        obs = observe({'d': '2026-11-03', 'lvl': 'amber', 'f': ['made_up']}, {'d': 'bad', 'lvl': 'red'})
        self.assertEqual([(o['kind'], o['title']) for o in obs], [('collection', 'Level without a recognised rule')])


if __name__ == '__main__':
    unittest.main()
