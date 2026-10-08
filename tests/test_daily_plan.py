"""Synthetic daily recovery/observation boundaries; no participant fixtures."""
from datetime import date,datetime,timezone
import unittest

from sentra.errors import SentraError


class DailyPlanTests(unittest.TestCase):
    def module(self):
        try:
            from sentra import daily_plan
            return daily_plan
        except ImportError:
            self.fail('Daily planner not implemented')

    def test_missing_days_and_three_day_recheck_are_separate_per_dataset(self):
        m=self.module()
        ranges=[{'requested_civil_start':'2026-10-01','requested_civil_end':'2026-10-06'},
                {'requested_civil_start':'2026-10-07','requested_civil_end':'2026-10-08'}]
        self.assertEqual(m.request_days(ranges,date(2026,10,10)),[date(2026,10,d) for d in (6,7,8,9)])
        other=[{'requested_civil_start':'2026-10-01','requested_civil_end':'2026-10-10'}]
        self.assertEqual(m.request_days(other,date(2026,10,10)),[date(2026,10,d) for d in (7,8,9)])

    def test_daily_contracts_keep_selected_fields_and_exclude_original_hr_repeat(self):
        m=self.module()
        jobs=m.day_jobs('google_health',date(2026,10,7))
        self.assertEqual(len(jobs),19)
        self.assertNotIn('original_heart-rate',{j.dataset for j in jobs})
        self.assertEqual({j.dataset for j in m.day_jobs('whoop',date(2026,10,7))},{'cycle','recovery','sleep','workout'})

    def test_beirut_midnight_and_dst_calendar_boundaries(self):
        m=self.module()
        self.assertEqual(m.collection_day(datetime(2026,10,8,20,59,tzinfo=timezone.utc)),date(2026,10,8))
        self.assertEqual(m.collection_day(datetime(2026,10,8,21,0,tzinfo=timezone.utc)),date(2026,10,9))
        spring=m.day_jobs('whoop',date(2026,3,29))[0]
        duration=datetime.fromisoformat(spring.end.replace('Z','+00:00'))-datetime.fromisoformat(spring.start.replace('Z','+00:00'))
        self.assertEqual(duration.total_seconds(),23*3600)

    def test_window_stays_paused_without_dates_and_stops_at_end(self):
        m=self.module()
        self.assertEqual(m.window_status({},date(2026,10,10)),'paused')
        window={'enabled':True,'start':'2026-10-10','end':'2026-10-13'}
        self.assertEqual(m.window_status(window,date(2026,10,9)),'not_started')
        self.assertEqual(m.window_status(window,date(2026,10,10)),'active')
        self.assertEqual(m.window_status(window,date(2026,10,13)),'ended')
        with self.assertRaises(SentraError): m.window_status({**window,'end':'2026-10-24'},date(2026,10,10))

    def test_old_recovery_or_unknown_coverage_requires_bounded_manual_import(self):
        m=self.module()
        with self.assertRaises(SentraError): m.request_days([],date(2026,10,10))
        with self.assertRaises(SentraError): m.request_days([{'requested_civil_start':'2026-08-01','requested_civil_end':'2026-08-02'}],date(2026,10,10))
