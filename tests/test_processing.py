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
from sentra.processing.board import payload
from sentra.processing.observations import devices, load
from sentra import organization
from sentra.tiers import hr_tables, measurements_table, parquet_bytes, sessions_table

UTC = timezone.utc


def FITBIT(d):
    return {pid: 'google_health' for pid in d.subject_id}
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

    def test_missing_inputs_or_history_never_produce_green(self):
        d = pd.DataFrame({'subject_id': 'p01', 'date': pd.date_range('2026-10-01', periods=4),
            'sleep_min': [None, 420.0, 420.0, 300.0], 'rhr': [None, 60.0, 60.0, None], 'rhr_base': [None, None, 60.0, None],
            'rhr_z': [None, None, 0.0, None], 'daily_hrv_rmssd': [None, 50.0, 50.0, None],
            'daily_hrv_rmssd_base': [None, 50.0, 50.0, None], 'daily_hrv_rmssd_z': [None, 0.0, 0.0, None],
            'sustained_hr_max_run': 0, 'longest_still_in_shift': 0})
        d = pipeline.flags(d)
        self.assertEqual(d.wellness_level.tolist(), ['insufficient', 'insufficient', 'green', 'amber'])
        self.assertEqual(d.assessment_state.tolist(), ['insufficient', 'partial', 'complete', 'partial'])
        self.assertEqual(d.assessment_reasons.iloc[1], 'rhr:baseline_building;sleep_hr:no_reading')
        self.assertIn('hrv:no_reading', d.assessment_reasons.iloc[3])  # a signal still shows, with its gaps

    def test_insufficient_days_are_not_counted_as_calm_in_the_cohort(self):
        d = pd.DataFrame({'subject_id': [f'p0{i}' for i in range(1, 7)], 'date': pd.Timestamp('2026-10-03'),
            'usable_day': True, 'sleep_min': 420.0, 'steps': 100.0, 'hr_mean': 70.0,
            'wellness_signals': [1, 0, 0, 0, 0, 0], 'wellness_level': ['amber', 'green', 'green', 'green', 'green', 'insufficient'],
            'flag_short_sleep': False, 'flag_sustained_high_hr': False})
        c = pipeline.cohort(d, FITBIT(d))
        self.assertAlmostEqual(c.pct_wellness_amber_or_red.iloc[0], 0.2)  # 1 of 5 assessed, not 1 of 6
        self.assertEqual(c.n_pct_wellness_amber_or_red.iloc[0], 5)
        self.assertEqual(c.n_median_sleep_h.iloc[0], 6)

    def test_each_cohort_metric_needs_five_known_contributors(self):
        d = pd.DataFrame({'subject_id': ['p01', 'p02', 'p03', 'p04', 'p05'],
            'date': pd.Timestamp('2026-10-03'), 'usable_day': True,
            'sleep_min': [300.0, None, None, None, None], 'steps': [100.0, None, None, None, None],
            'hr_mean': [160.0, None, None, None, None], 'wellness_signals': [1, 0, 0, 0, 0],
            'wellness_level': ['amber', 'insufficient', 'insufficient', 'insufficient', 'insufficient'],
            'flag_short_sleep': [True, False, False, False, False],
            'flag_sustained_high_hr': [True, False, False, False, False]})
        c = pipeline.cohort(d, FITBIT(d))
        metrics = ['pct_short_sleep', 'pct_wellness_amber_or_red', 'pct_sustained_high_hr',
                   'median_sleep_h', 'median_steps']
        self.assertTrue(c[metrics].isna().all().all())
        self.assertEqual(c.workers.iloc[0], 5)
        d['sleep_min'] = 300.0; d['steps'] = 100.0; d['hr_mean'] = 160.0
        d['wellness_level'] = ['amber', 'green', 'green', 'green', 'green']
        c = pipeline.cohort(d, FITBIT(d))
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
            _, d, c, _ = pipeline.run(load(folder), out, log=lambda *_: None, devices=devices(folder))
            self.assertTrue((out / 'daily_features.parquet').is_file())
            meta = json.loads((out / 'metadata.json').read_text(encoding='utf-8'))
            self.assertIn('pending medical expert sign-off', meta['notice'])
            self.assertEqual(meta['assessment_version'], pipeline.ASSESSMENT_VERSION)
        p01 = d[d.subject_id == 'p01'].reset_index(drop=True)
        self.assertTrue(p01.rhr_z.iloc[:7].isna().all())  # fewer than 7 previous days: no baseline, no flag
        self.assertFalse(p01.flag_rhr_above_baseline.iloc[:35].any())
        self.assertTrue(p01.flag_rhr_above_baseline.iloc[35])
        self.assertEqual(p01.wellness_level.iloc[35], 'amber')
        self.assertFalse(p01.flag_short_sleep.any())  # sleep never returned -> never flagged
        self.assertTrue(d.usable_day.all())
        self.assertEqual(set(c.device), {'Fitbit', 'WHOOP'})  # one row per date and device, never pooled
        self.assertTrue(c.suppressed.all())  # one person per device < k=5
        self.assertTrue(c.pct_short_sleep.isna().all())



def day_rows(day, people):
    """Synthetic usable day rows: (pid, sleep_min, steps, level, state) per person."""
    return pd.DataFrame([{'subject_id': pid, 'date': pd.Timestamp(day), 'usable_day': True, 'sleep_min': sleep,
        'steps': steps, 'hr_mean': 70.0, 'wellness_signals': 0 if level == 'green' else (1 if level == 'amber' else 0),
        'wellness_level': level, 'assessment_state': state,
        'assessment_reasons': None if state == 'complete' else 'rhr:baseline_building',
        'flag_short_sleep': False, 'flag_sustained_high_hr': False}
        for pid, sleep, steps, level, state in people])


class GroupStatisticConsistencyTests(unittest.TestCase):
    """#45: processing, the read API's cohort and the organization overview count the same people."""

    def setUp(self):
        fitbit = [(f'p0{i}', 420.0 + i, 5000.0 + i, 'green', 'complete') for i in range(1, 6)]
        whoop = [('p11', 400.0, 4000.0, 'amber', 'complete'), ('p12', 410.0, None, 'insufficient', 'insufficient')]
        unknown = [('p21', 300.0, 100.0, 'green', 'complete')]
        self.daily = day_rows('2026-10-03', fitbit + whoop + unknown)
        self.devices = {**{p[0]: 'google_health' for p in fitbit}, **{p[0]: 'whoop' for p in whoop}}

    def test_devices_are_never_pooled_and_unknown_devices_never_contribute(self):
        c = pipeline.cohort(self.daily, self.devices).set_index('device')
        self.assertEqual(sorted(c.index), ['Fitbit', 'WHOOP'])  # no pooled row, no row for p21
        self.assertFalse(c.loc['Fitbit', 'suppressed'])
        self.assertEqual(c.loc['Fitbit', 'n_median_sleep_h'], 5)
        self.assertAlmostEqual(c.loc['Fitbit', 'median_sleep_h'], 423 / 60)
        self.assertTrue(c.loc['WHOOP', 'suppressed'])  # 2 WHOOP people: not 7 pooled with Fitbit
        self.assertTrue(pd.isna(c.loc['WHOOP', 'median_sleep_h']))
        self.assertEqual(c.loc['WHOOP', 'n_median_steps'], 1)  # p12 supplied no steps
        self.assertEqual(c.loc['WHOOP', 'n_pct_wellness_amber_or_red'], 1)  # p12 is insufficient, not calm

    def test_without_known_devices_no_group_statistic_is_published(self):
        c = pipeline.cohort(self.daily)
        self.assertEqual(len(c), 0)
        self.assertIn('n_median_sleep_h', c.columns)

    def test_cohort_counts_match_the_organization_overview_built_from_the_board(self):
        board = payload(self.daily, self.devices, built_at='2026-10-04T00:00:00+00:00')
        people = board['people']
        everyone = {p['id'] for p in people}
        summary = organization.group_summary(people, everyone, end=date(2026, 10, 3))
        c = pipeline.cohort(self.daily, self.devices).set_index('device')
        for key, column in (('sleep', 'median_sleep_h'), ('steps', 'median_steps')):
            for row in (r for r in summary if r['key'] == key):
                self.assertEqual(row['contributors'], c.loc[row['device'], f'n_{column}'], (key, row['device']))
                self.assertEqual(row['status'] == 'available', pd.notna(c.loc[row['device'], column]), (key, row['device']))
        self.assertEqual({r['device'] for r in summary if r['key'] == 'sleep'}, {'Fitbit', 'WHOOP'})

    def test_a_participant_with_two_providers_never_enters_a_device_statistic(self):
        start, end = datetime(2026, 10, 9, 20, tzinfo=UTC), datetime(2026, 10, 10, 3, tzinfo=UTC)
        rows = [m(f'p0{i}', 'google_health', 'sleep', f'p0{i}-s', '/sleep/summary/minutesAsleep', minutes, ts=start, end=end)
                for i, minutes in enumerate([360, 370, 380, 390, 400, 410], 1)]
        # p01 also has WHOOP sleep; processing merges a person's day without keeping its provider.
        rows += [m('p01', 'whoop', 'sleep', 'p01-w', metric, 160 * 60000, ts=start, end=end)
                 for metric in ('/score/stage_summary/total_light_sleep_time_milli',
                                '/score/stage_summary/total_slow_wave_sleep_time_milli',
                                '/score/stage_summary/total_rem_sleep_time_milli')]
        with tempfile.TemporaryDirectory() as folder:
            write_tiers(folder, rows=rows)
            mapping = devices(folder)
            _, d, c, _ = pipeline.run(load(folder), Path(folder) / 'out', log=lambda *_: None, devices=mapping)
        self.assertNotIn('p01', mapping)
        self.assertEqual(c.device.tolist(), ['Fitbit'])  # no WHOOP row from p01's WHOOP sleep either
        self.assertEqual((c.workers.iloc[0], c.n_median_sleep_h.iloc[0]), (5, 5))
        self.assertAlmostEqual(c.median_sleep_h.iloc[0], 390 / 60)  # p02-p06 Fitbit sleep only
        board = payload(d, mapping, built_at='2026-10-11T00:00:00+00:00')
        self.assertEqual(next(p['device'] for p in board['people'] if p['id'] == 'p01'), 'Unknown')

    def test_heart_rate_tiers_also_identify_a_participants_provider(self):
        raw = [('p07', 'whoop', datetime(2026, 10, 10, 8, tzinfo=UTC), Decimal('61'))]
        with tempfile.TemporaryDirectory() as folder:
            write_tiers(folder, raw=raw)
            self.assertEqual(devices(folder), {'p07': 'whoop'})

    def test_only_complete_assessments_count_as_assessable_everywhere(self):
        board = payload(self.daily, self.devices, built_at='2026-10-04T00:00:00+00:00')
        counts = organization.participation(set(self.devices) | {'p21'}, [], board['people'], today=date(2026, 10, 3),
                                            assessment_version=board['assessment_version'])
        complete = int((self.daily.assessment_state == 'complete').sum())
        self.assertEqual(counts['assessable'], complete)
        insufficient = next(d for p in board['people'] if p['id'] == 'p12' for d in p['days'])
        self.assertIsNone(insufficient['lvl'])
        self.assertEqual(insufficient['a'], 'insufficient')


if __name__ == '__main__':
    unittest.main()
