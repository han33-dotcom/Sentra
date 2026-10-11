"""Synthetic tiers -> canonical observations -> v0 wellness features; no participant data."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from sentra.processing import metric_map, pipeline
from sentra.processing.canonical import METRICS
from sentra.processing.observations import load
from sentra.tiers import hr_tables, measurements_table, parquet_bytes, sessions_table

UTC = timezone.utc
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


def m(pid, provider, dataset, key, metric, value, *, ts=None, end=None, civil=None):
    return (pid, provider, dataset, key, metric, None if value is None else Decimal(str(value)), None, 'vendor_summary',
            'available', None, ts, end, civil, None)


def write_tiers(folder, raw=(), vendor=(), rows=()):
    hot, warm = hr_tables(list(raw), list(vendor), NOW)
    for pid, table in hot.items():
        (Path(folder) / 'hr_raw').mkdir(exist_ok=True); (Path(folder) / 'hr_raw' / f'{pid}.parquet').write_bytes(parquet_bytes(table))
    for pid, table in warm.items():
        (Path(folder) / 'hr_minute').mkdir(exist_ok=True); (Path(folder) / 'hr_minute' / f'{pid}.parquet').write_bytes(parquet_bytes(table))
    (Path(folder) / 'measurements.parquet').write_bytes(parquet_bytes(measurements_table(list(rows))))
    (Path(folder) / 'sessions.parquet').write_bytes(parquet_bytes(sessions_table([])))


def civil(day):
    return {'date': {'year': day.year, 'month': day.month, 'day': day.day}}


class MappingTests(unittest.TestCase):
    def test_every_target_is_a_canonical_metric_and_paths_are_exact(self):
        self.assertTrue(all(t[0] in METRICS for t in metric_map.MAPPING.values()))
        self.assertEqual(metric_map.lookup('google_health', 'daily-resting-heart-rate', '/dailyRestingHeartRate/beatsPerMinute')[0],
                         'resting_heart_rate')
        self.assertEqual(metric_map.lookup('whoop', 'recovery', '/score/hrv_rmssd_milli')[0], 'daily_hrv_rmssd')
        self.assertIsNone(metric_map.lookup('whoop', 'sleep', '/score/hrv_rmssd_milli'))  # no suffix guessing
        self.assertIn(('google_health', 'daily_steps'), metric_map.UNMAPPED)

    def test_thresholds_are_marked_pending_sign_off_and_wording_is_wellness_only(self):
        self.assertEqual(pipeline.TH['_status'], 'v0 — pending medical expert sign-off')
        self.assertIn('not a medical assessment', pipeline.NOTICE)
        source = Path(pipeline.__file__).read_text(encoding='utf-8').lower()
        for word in ('fatigue', 'diagnose', 'disease', 'illness'):
            self.assertNotIn(word, source.replace('not a medical assessment or diagnosis', ''))


class ObservationTests(unittest.TestCase):
    def test_heart_rate_source_priority_whoop_asleep_and_day_placement(self):
        minute = int(datetime(2026, 10, 10, 6, 0, tzinfo=UTC).timestamp())
        raw = [('p01', 'google_health', datetime.fromtimestamp(minute + s, UTC), Decimal(70)) for s in (0, 10, 20)]
        vendor = [('p01', 'google_health', datetime.fromtimestamp(minute, UTC), '/heartRate/beatsPerMinuteAvg', Decimal(99)),
                  ('p01', 'google_health', datetime.fromtimestamp(minute + 60, UTC), '/heartRate/beatsPerMinuteAvg', Decimal(80))]
        sleep_start, sleep_end = datetime(2026, 10, 9, 20, tzinfo=UTC), datetime(2026, 10, 10, 3, tzinfo=UTC)
        parts = {'/score/stage_summary/total_light_sleep_time_milli': 14_400_000,
                 '/score/stage_summary/total_slow_wave_sleep_time_milli': 3_600_000,
                 '/score/stage_summary/total_rem_sleep_time_milli': 3_600_000}
        rows = [m('p02', 'whoop', 'sleep', 's1', path, value, ts=sleep_start, end=sleep_end) for path, value in parts.items()]
        rows.append(m('p01', 'google_health', 'daily-resting-heart-rate', 'r1', '/dailyRestingHeartRate/beatsPerMinute', 58,
                      civil=civil(date(2026, 10, 8))))
        rows.append(m('p01', 'google_health', 'daily_steps', 'd1', '/steps/countSum', 9000, civil=civil(date(2026, 10, 8))))
        with tempfile.TemporaryDirectory() as folder:
            write_tiers(folder, raw, vendor, rows)
            obs = load(folder)
        hr = obs[obs.metric == 'heart_rate']
        self.assertEqual(sorted(hr.value.tolist()), [70.0, 70.0, 70.0, 80.0])  # vendor 99 loses to raw in that minute
        asleep = obs[(obs.metric == 'daily_sleep_min') & (obs.subject_id == 'p02')].iloc[0]
        self.assertEqual(asleep.value, 360.0)
        self.assertEqual(asleep.t.date(), date(2026, 10, 10))  # Beirut wake day (06:00 local)
        deep = obs[obs.metric == 'daily_deep_sleep_min'].iloc[0]
        self.assertEqual(deep.value, 60.0)
        rhr = obs[obs.metric == 'resting_heart_rate'].iloc[0]
        self.assertEqual((rhr.t, rhr.value), (pd.Timestamp('2026-10-08'), 58.0))
        self.assertNotIn('daily_steps', set(obs.metric))


class PipelineTests(unittest.TestCase):
    def test_baseline_excludes_history_older_than_28_calendar_days(self):
        d = pd.DataFrame({'subject_id': 'p01', 'valid_day': True,
            'date': [*pd.date_range('2026-09-01', periods=7), pd.Timestamp('2026-10-09')],
            'rhr': [60.0] * 7 + [75.0], 'sustained_hr_max_run': 0, 'longest_still_in_shift': 0})
        d = pipeline.flags(pipeline.baselines(d))
        self.assertTrue(pd.isna(d.rhr_base.iloc[-1]))
        self.assertFalse(d.flag_rhr_above_baseline.iloc[-1])

    def test_missing_steps_do_not_imply_rest_or_inactivity(self):
        obs = pd.DataFrame({'subject_id': 'p01', 'metric': 'heart_rate',
            't': pd.date_range('2026-10-03 08:00', periods=120, freq='min'), 't_end': pd.NaT,
            'value': 60.0, 'resolution': 'minute', 'raw_ref': None})
        d = pipeline.flags(pipeline.baselines(pipeline.daily(pipeline.minute_grid(obs), obs)))
        self.assertTrue(d.rhr_est.isna().all())
        self.assertFalse(d.flag_long_inactivity_in_shift.any())

    def test_each_cohort_metric_needs_five_known_contributors(self):
        d = pd.DataFrame({'subject_id': ['p01', 'p02', 'p03', 'p04', 'p05'],
            'date': pd.Timestamp('2026-10-03'), 'usable_day': True,
            'sleep_min': [300.0, None, None, None, None], 'steps': [100.0, None, None, None, None],
            'hr_mean': [160.0, None, None, None, None], 'wellness_signals': [1, 0, 0, 0, 0],
            'flag_short_sleep': [True, False, False, False, False],
            'flag_sustained_high_hr': [True, False, False, False, False]})
        c = pipeline.cohort(d)
        metrics = ['pct_short_sleep', 'pct_wellness_amber_or_red', 'pct_sustained_high_hr',
                   'median_sleep_h', 'median_steps']
        self.assertTrue(c[metrics].isna().all().all())
        self.assertEqual(c.workers.iloc[0], 5)
        d['sleep_min'] = 300.0; d['steps'] = 100.0; d['hr_mean'] = 160.0
        c = pipeline.cohort(d)
        self.assertEqual(c.median_sleep_h.iloc[0], 5.0)
        self.assertEqual(c.median_steps.iloc[0], 100.0)
        self.assertAlmostEqual(c.pct_short_sleep.iloc[0], 0.2)
        self.assertAlmostEqual(c.pct_wellness_amber_or_red.iloc[0], 0.2)
        self.assertAlmostEqual(c.pct_sustained_high_hr.iloc[0], 0.2)

    def test_personal_baseline_flags_only_with_enough_history_and_cohort_is_k_anonymous(self):
        rows = []
        for i in range(36):
            day = date(2026, 9, 1) + timedelta(days=i)
            rhr = 75 if i == 35 else 60 + (i % 3) * 0.5
            rows.append(m('p01', 'google_health', 'daily-resting-heart-rate', f'r{i}', '/dailyRestingHeartRate/beatsPerMinute',
                          rhr, civil=civil(day)))
            rows.append(m('p02', 'whoop', 'recovery', f'w{i}', '/score/hrv_rmssd_milli', 50,
                          ts=datetime(2026, 9, 1, 4, tzinfo=UTC) + timedelta(days=i)))
        with tempfile.TemporaryDirectory() as folder:
            write_tiers(folder, rows=rows)
            out = Path(folder) / 'processed'
            _, d, c, _ = pipeline.run(load(folder), out, log=lambda *_: None)
            self.assertTrue((out / 'daily_features.parquet').is_file())
            meta = json.loads((out / 'metadata.json').read_text(encoding='utf-8'))
            self.assertIn('pending medical expert sign-off', meta['notice'])
        p01 = d[d.subject_id == 'p01'].reset_index(drop=True)
        self.assertTrue(p01.rhr_z.iloc[:7].isna().all())  # fewer than 7 previous days: no baseline, no flag
        self.assertFalse(p01.flag_rhr_above_baseline.iloc[:35].any())
        self.assertTrue(p01.flag_rhr_above_baseline.iloc[35])
        self.assertEqual(p01.wellness_level.iloc[35], 'amber')
        self.assertFalse(p01.flag_short_sleep.any())  # sleep never returned -> never flagged
        self.assertTrue(d.usable_day.all())
        self.assertTrue(c.suppressed.all())  # two people < k=5
        self.assertTrue(c.pct_short_sleep.isna().all())


if __name__ == '__main__':
    unittest.main()
