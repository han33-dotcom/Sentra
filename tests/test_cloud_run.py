from datetime import date
import unittest
from sentra.daily_plan import day_jobs
from sentra.errors import SentraError

class CloudRunTests(unittest.TestCase):
    def test_schedule_selects_only_approved_account_and_dataset_pairs(self):
        import json
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from sentra import cloud_run

        scope = [{'participant':'p01','provider':'google_health','datasets':['daily_steps','sleep']},
                 {'participant':'p03','provider':'whoop','datasets':['cycle','recovery']}]
        directory = {'google_health':['p01','p02'], 'whoop':['p01','p03']}
        with patch.dict('os.environ', {'GITHUB_EVENT_NAME':'schedule','SENTRA_SCHEDULE_SCOPE':json.dumps(scope)}), \
             patch.object(cloud_run,'runtime_config',return_value=({},None,directory,None)), \
             patch.object(cloud_run,'run_provider',return_value={'status':'succeeded'}) as run, \
             redirect_stdout(StringIO()):
            self.assertEqual(cloud_run.main([]),0)
        actual = [(c.args[2:4], c.kwargs['scheduled_datasets']) for c in run.call_args_list]
        self.assertEqual(actual,[(('p01','google_health'),{'sleep','daily_steps'}),(('p03','whoop'),{'cycle','recovery'})])

    def test_invalid_schedule_cannot_start_a_partial_run(self):
        import json
        from sentra.cloud_run import scheduled_scope
        pairs = [('p01','google_health')]
        row = {'participant':'p01','provider':'google_health','datasets':['daily_steps']}
        for raw in ('', '[]', '{}', json.dumps([row,row]), json.dumps([row,dict(row,participant='p02')]),
                    json.dumps([dict(row,datasets=['activity-level'])]), json.dumps([dict(row,datasets=[])])):
            with self.subTest(raw=raw), self.assertRaises(SentraError):
                scheduled_scope(raw,pairs,date(2026,11,20))

    def test_preview_uses_dated_schedule_without_dispatching(self):
        from unittest.mock import patch
        from sentra import cloud_run
        env = {'SENTRA_SCHEDULE_SCOPE':'[{"participant":"p01","provider":"whoop","datasets":["sleep"]}]'}
        with patch.dict('os.environ',env), \
             patch.object(cloud_run,'runtime_config',return_value=({},None,{'whoop':'p01'},None)), \
             patch.object(cloud_run,'preview_schedule',return_value=0) as preview, \
             patch.object(cloud_run,'run_provider') as run:
            self.assertEqual(cloud_run.main(['--preview-schedule','2026-11-20']),0)
        preview.assert_called_once_with({},None,{('p01','whoop'):{'sleep'}},date(2026,11,20))
        run.assert_not_called()

    def test_scoped_daily_planning_retains_gap_and_correction_rules(self):
        from sentra.cloud_run import jobs_for
        states = {'sleep':[{'requested_civil_start':'2026-10-01','requested_civil_end':'2026-11-19'}],
                  'cycle':[{'requested_civil_start':'2026-10-01','requested_civil_end':'2026-10-02'}]}
        jobs, failures = jobs_for('whoop','daily',date(2026,11,20),states,scheduled_datasets={'sleep','cycle'})
        self.assertEqual([(j.dataset,j.start_date) for j in jobs],
                         [('sleep','2026-11-17'),('sleep','2026-11-18'),('sleep','2026-11-19')])
        self.assertEqual([f['dataset'] for f in failures],['cycle'])

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

    def test_local_recovery_targets_one_participant_with_shared_provider(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from sentra import cli, cloud_cli, cloud_run

        def run_collector(command, *, env):
            self.assertEqual(command[1:3], ['-m', 'sentra.cloud_run'])
            return type('Run', (), {'returncode': cloud_run.main(command[3:])})()

        with patch.object(cloud_cli, 'local_cipher'), patch.object(cloud_cli, 'read_shared', return_value=({}, None, None)), \
             patch.object(cloud_cli, 'read_setup', return_value={'config': {}, 'token_key': 'synthetic'}), \
             patch.object(cloud_cli.subprocess, 'run', side_effect=run_collector), \
             patch.object(cloud_run, 'runtime_config', return_value=({}, None, {'google_health': ['p01', 'p02']}, None)), \
             patch.object(cloud_run, 'run_provider', return_value={'status': 'succeeded'}) as run_provider, \
             redirect_stdout(StringIO()):
            result = cli.main(['cloud-run-local', '--mode', 'recovery', '--provider', 'google_health',
                               '--participant', 'p02', '--start', '2026-10-07', '--end', '2026-10-08',
                               '--dataset', 'daily_steps'])
        self.assertEqual(result, 0)
        run_provider.assert_called_once()
        self.assertEqual(run_provider.call_args.args[2:4], ('p02', 'google_health'))
