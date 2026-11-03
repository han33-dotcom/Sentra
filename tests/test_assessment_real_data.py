"""Opt-in check of the assessment rules on real, locally held daily features (never committed).

Set SENTRA_REAL_DAILY_FEATURES to a private daily_features.parquet beneath an ignored folder.
Personal baselines and assessments are rebuilt from the per-day values with the current rules,
and only aggregate counts are printed. Skipped when the variable is unset (CI and ordinary runs).
"""
import os
from pathlib import Path
import unittest

import pandas as pd

from sentra.processing import pipeline

SOURCE = os.environ.get('SENTRA_REAL_DAILY_FEATURES')
DERIVED = ('_base', '_z')


@unittest.skipUnless(SOURCE, 'set SENTRA_REAL_DAILY_FEATURES to a private daily_features.parquet')
class RealDataAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = pd.read_parquet(Path(SOURCE))
        days = raw[[c for c in raw if not c.endswith(DERIVED) and not c.startswith(('flag_', 'wellness_', 'assess'))]]
        cls.d = pipeline.flags(pipeline.baselines(days))

    def test_no_green_day_lacks_a_core_input_or_baseline(self):
        green = self.d[self.d.wellness_level == 'green']
        for code in pipeline.CORE_RULES:
            self.assertTrue(green[f'assess_{code}'].isin(['signal', 'clear']).all(), code)

    def test_days_without_any_reading_are_insufficient(self):
        inputs = [value for _, value, _ in pipeline.RULES.values() if value in self.d]
        empty = self.d[inputs].isna().all(axis=1)
        self.assertTrue((self.d.loc[empty, 'wellness_level'] == 'insufficient').all())

    def test_print_aggregate_evidence(self):
        d = self.d[self.d.usable_day]
        print('\nsubjects', d.subject_id.nunique(), 'usable days', len(d))
        print('levels', d.wellness_level.value_counts().to_dict())
        print('states', d.assessment_state.value_counts().to_dict())
        for code in pipeline.RULES:
            print(code, d[f'assess_{code}'].value_counts().to_dict())


if __name__ == '__main__':
    unittest.main()
