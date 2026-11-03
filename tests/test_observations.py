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
        self.assertEqual(obs[0]['readings'], [('This day', '64 bpm'), ('Usual (own baseline)', '55 bpm'),
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
        stale = observe({'d': '2026-10-20', 'lvl': 'green'})
        self.assertEqual([(o['kind'], o['title']) for o in stale],
                         [('collection', 'No recent data'), ('wellness', 'No change from usual pattern')])
        self.assertIn('15 days old', stale[0]['detail'])

    def test_board_from_older_rules_shows_no_levels(self):
        obs = observe({'d': '2026-11-04', 'lvl': 'green', 'f': ['rhr_up']}, version=None)
        self.assertEqual([(o['kind'], o['title']) for o in obs], [('collection', 'Published under older rules')])

    def test_a_level_is_never_left_unexplained(self):
        obs = observe({'d': '2026-11-03', 'lvl': 'amber', 'f': ['made_up']}, {'d': 'bad', 'lvl': 'red'})
        self.assertEqual([(o['kind'], o['title']) for o in obs], [('collection', 'Level without a recognised rule')])


if __name__ == '__main__':
    unittest.main()
