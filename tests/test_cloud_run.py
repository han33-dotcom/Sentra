from datetime import date
import unittest
from sentra.daily_plan import day_jobs
from sentra.errors import SentraError

class CloudRunTests(unittest.TestCase):
    def test_attempt_run_ids_preserve_history_and_execution_identity(self):
        from sentra.cloud_run import attempt_run_id
        from unittest.mock import patch
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}):
            first=attempt_run_id('github-123')
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2'}):
            second=attempt_run_id('github-123')
        self.assertNotEqual(first,second)
        self.assertEqual(first,'github-123-attempt-1')

    def test_daily_plans_each_dataset_from_its_own_coverage(self):
        from sentra.cloud_run import jobs_for
        states={j.dataset:[{'requested_civil_start':'2026-10-01','requested_civil_end':'2026-10-08'}] for j in day_jobs('whoop',date(2026,10,7))}
        states['sleep'][0]['requested_civil_end']='2026-10-06'
        jobs,failures=jobs_for('whoop','daily',date(2026,10,10),states)
        self.assertFalse(failures)
        self.assertEqual([j.start_date for j in jobs if j.dataset=='sleep'],['2026-10-06','2026-10-07','2026-10-08','2026-10-09'])
        self.assertEqual([j.start_date for j in jobs if j.dataset=='cycle'],['2026-10-07','2026-10-08','2026-10-09'])

    def test_missing_dataset_is_reported_without_losing_other_work(self):
        from sentra.cloud_run import jobs_for
        jobs,errors=jobs_for('whoop','daily',date(2026,10,8),{'cycle':[{'requested_civil_start':'2026-10-01','requested_civil_end':'2026-10-08'}]})
        self.assertEqual(len(jobs),3); self.assertEqual(len(errors),3)
        with self.assertRaises(SentraError): jobs_for('whoop','recovery',date(2026,10,8),{},date(2026,10,1),date(2026,10,9))

    def test_recovery_omits_initial_only_hr_and_validates_datasets(self):
        from sentra.cloud_run import jobs_for
        jobs,_=jobs_for('google_health','recovery',date(2026,10,8),{},date(2026,10,7),date(2026,10,8))
        self.assertFalse(any(j.dataset=='original_heart-rate' for j in jobs))
        with self.assertRaises(SentraError): jobs_for('whoop','recovery',date(2026,10,8),{},date(2026,10,7),date(2026,10,8),'typo')
