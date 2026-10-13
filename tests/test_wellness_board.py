"""Synthetic wellness board: Fitbit sleep stages, sleeping HR, pseudonymous payload, refresh and viewer read."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pandas as pd

from sentra.errors import SentraError
from sentra.processing import board as board_mod
from sentra.processing.canonical import SLEEP_STAGE
from sentra.processing.observations import google_sleep, load
from sentra.processing.pipeline import run
from sentra.shared import Limits
from sentra.tiers import hr_tables, measurements_table, parquet_bytes, sessions_table

UTC = timezone.utc
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
NIGHT_START = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)   # 23:00 Beirut
NIGHT_END = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)     # 06:00 Beirut wake day Oct 10


def row(pid, provider, dataset, key, metric, value=None, vendor=None, start=NIGHT_START, end=NIGHT_END, civil=None):
    return (pid, provider, dataset, key, metric, None if value is None else Decimal(str(value)), None,
            'unknown' if value is None else 'vendor_calculation', 'available', None, start, end, civil, vendor)


def sleep_rows(pid='p01', key='s1'):
    stages = [('LIGHT', 0, 120), ('DEEP', 120, 210), ('REM', 210, 300), ('AWAKE', 300, 320), ('LIGHT', 320, 420)]
    rows = []
    for i, (kind, a, b) in enumerate(stages):
        rows += [row(pid, 'google_health', 'sleep', key, f'/sleep/stages/{i}/type', vendor=kind),
                 row(pid, 'google_health', 'sleep', key, f'/sleep/stages/{i}/startTime',
                     vendor=(NIGHT_START + timedelta(minutes=a)).isoformat().replace('+00:00', 'Z')),
                 row(pid, 'google_health', 'sleep', key, f'/sleep/stages/{i}/endTime',
                     vendor=(NIGHT_START + timedelta(minutes=b)).isoformat().replace('+00:00', 'Z'))]
    rows += [row(pid, 'google_health', 'sleep', key, '/sleep/stages/9/type', vendor='MYSTERY'),
             row(pid, 'google_health', 'sleep', key, '/sleep/summary/stagesSummary/0/type', vendor='DEEP'),
             row(pid, 'google_health', 'sleep', key, '/sleep/summary/stagesSummary/0/minutes', vendor='90'),
             row(pid, 'google_health', 'sleep', key, '/sleep/summary/stagesSummary/1/type', vendor='REM'),
             row(pid, 'google_health', 'sleep', key, '/sleep/summary/stagesSummary/1/minutes', vendor='90'),
             row(pid, 'google_health', 'sleep', key, '/sleep/summary/minutesAsleep', value=400)]
    return rows


def write(folder, rows, vendor_hr=()):
    hot, warm = hr_tables([], list(vendor_hr), NOW)
    for pid, table in warm.items():
        (Path(folder) / 'hr_minute').mkdir(exist_ok=True)
        (Path(folder) / 'hr_minute' / f'{pid}.parquet').write_bytes(parquet_bytes(table))
    (Path(folder) / 'measurements.parquet').write_bytes(parquet_bytes(measurements_table(list(rows))))
    (Path(folder) / 'sessions.parquet').write_bytes(parquet_bytes(sessions_table([])))


class SleepStageTests(unittest.TestCase):
    def test_partial_stage_timeline_preserves_vendor_sleep_total(self):
        rows = [r[:13] + ('SLEEP_STAGE_TYPE_UNSPECIFIED',) if r[4] == '/sleep/stages/1/type' else r
                for r in sleep_rows()]
        with tempfile.TemporaryDirectory() as folder:
            write(folder, rows)
            _, daily, _, _ = run(load(folder), Path(folder) / 'out', log=lambda *_: None)
        wake = daily[daily.date == pd.Timestamp('2026-10-10')].iloc[0]
        self.assertEqual(wake.sleep_min, 400)
        self.assertFalse(wake.flag_short_sleep)

    def test_stage_timeline_and_stage_minutes_are_mapped_unknown_types_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            write(folder, sleep_rows())
            m = pd.read_parquet(Path(folder) / 'measurements.parquet')
        obs = google_sleep(m)
        stages = obs[obs.metric == 'sleep_stage'].sort_values('t')
        self.assertEqual(len(stages), 5)  # MYSTERY stage without times is skipped
        self.assertEqual(stages.value.tolist(), [float(SLEEP_STAGE[k]) for k in ('light', 'deep', 'rem', 'awake', 'light')])
        self.assertEqual(stages.t.iloc[0], pd.Timestamp('2026-10-09 23:00'))  # Beirut local
        minutes = obs[obs.metric.isin(['daily_deep_sleep_min', 'daily_rem_sleep_min'])]
        self.assertEqual(sorted(minutes.value), [90.0, 90.0])
        self.assertTrue((minutes.t.dt.date == pd.Timestamp('2026-10-10').date()).all())

    def test_sleeping_heart_rate_comes_from_minute_hr_during_asleep_stages(self):
        hr = []
        for minute in range(-60, 480):
            asleep = 0 <= minute < 300 or 320 <= minute < 420
            hr.append(('p01', 'google_health', NIGHT_START + timedelta(minutes=minute), '/heartRate/beatsPerMinuteAvg',
                       Decimal(52 if asleep else 75)))
        with tempfile.TemporaryDirectory() as folder:
            write(folder, sleep_rows(), hr)
            _, daily, _, _ = run(load(folder), Path(folder) / 'out', log=lambda *_: None)
        wake = daily[daily.date == pd.Timestamp('2026-10-10')].iloc[0]
        self.assertEqual(wake.sleep_hr, 52.0)
        self.assertEqual(wake.sleep_min, 400)  # stage timeline: 300 + 100 asleep minutes
        self.assertEqual(wake.daily_deep_sleep_min, 90.0)


class BoardTests(unittest.TestCase):
    def test_payload_carries_existing_baselines_for_every_trend(self):
        daily = self.daily()
        columns = {'sleep_hr_b': 'sleep_hr_base', 'steps_b': 'steps_base',
                   'br_b': 'daily_respiratory_rate_base', 'temp_b': 'nightly_skin_temp_c_base'}
        for column in columns.values():
            daily[column] = 50.0
        result = board_mod.payload(daily, {}, built_at='synthetic')['people'][0]['days'][0]
        for key in columns:
            self.assertEqual(result[key], 50)

    def daily(self):
        return pd.DataFrame({'subject_id': ['p01', 'p01', 'p02'], 'date': pd.to_datetime(['2026-10-09', '2026-10-10', '2026-10-10']),
                             'usable_day': [True, True, False], 'wellness_level': ['green', 'amber', 'nan'],
                             'sleep_min': [420.0, 300.0, None], 'rhr': [60.0, None, 55.0], 'rhr_base': [None, 59.5, None],
                             'flag_short_sleep': [False, True, None], 'flag_rhr_above_baseline': [False, False, None],
                             'flag_hrv_below_baseline': [False, False, None], 'flag_sleep_hr_above_baseline': [False, False, None]})

    def test_payload_is_pseudonymous_omits_missing_and_skips_unusable_days(self):
        board = board_mod.payload(self.daily(), {'p01': 'google_health', 'p02': 'whoop'}, built_at='2026-10-11T01:30:00+00:00')
        self.assertEqual([p['id'] for p in board['people']], ['p01'])
        p01 = board['people'][0]
        self.assertEqual((p01['name'], p01['device']), ('p01', 'Fitbit'))
        self.assertEqual(p01['days'][1], {'d': '2026-10-10', 'lvl': 'amber', 'sleep': 300, 'rhr_b': 59.5, 'f': ['short_sleep']})
        self.assertNotIn('rhr', p01['days'][1])  # missing stays missing, never zero
        self.assertEqual(board['data_through'], '2026-10-10')
        self.assertIn('not a medical assessment', board['notice'])

    def test_render_embeds_data_and_neutralises_script_breakout(self):
        board = board_mod.payload(self.daily(), {'p01': 'google_health'}, built_at='x')
        board['people'][0]['device'] = '</script><script>alert(1)</script>'
        page = board_mod.render(board)
        self.assertNotIn('</script><script>alert(1)', page)
        self.assertIn('Data through 2026-10-10', page)
        self.assertNotIn('__SENTRA_', page)
        self.assertIn('"id":"p01"', page)


class RefreshTests(unittest.TestCase):
    def test_watermark_ignores_paused_and_unchanged_runs_but_keeps_changed_partial(self):
        from sentra import wellness_refresh as w
        with sqlite3.connect(':memory:') as db:
            db.execute("attach database ':memory:' as audit")
            db.execute('create table audit.collection_runs (finished_at text, status text, details text)')
            db.executemany('insert into audit.collection_runs values (?,?,?)', [
                ('2026-10-10T00:00:00+00:00', 'partial', '{"changed":3}'),
                ('2026-10-11T00:00:00+00:00', 'paused', '{"changed":0}'),
                ('2026-10-12T00:00:00+00:00', 'succeeded', '{"changed":0}'),
                ('2026-10-13T00:00:00+00:00', 'failed', '{}'),
            ])
            class DB:
                def execute(self, query):
                    value = db.execute(query).fetchone()[0]
                    return type('Result', (), {'fetchone': lambda _: (datetime.fromisoformat(value) if value else None,)})()
            reader = self.Reader(None)
            reader.db = DB()
            self.assertEqual(w.latest_run(reader), '2026-10-10T00:00:00+00:00')

    def test_no_changed_run_skips_without_reading_or_publishing_tiers(self):
        from sentra import wellness_refresh as w
        storage = self.Storage()
        with mock.patch.object(w, 'build', side_effect=AssertionError('No changes should not rebuild tiers')):
            result = w.refresh(self.Reader(None), Limits(), storage, log=lambda *_: None)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(storage.posts, {})

    class Reader:
        def __init__(self, finished):
            self.finished, self.reserved = finished, 0
            reader = self
            class DB:
                def execute(self, query, values=()):
                    return type('R', (), {'fetchone': lambda _s: (reader.finished,)})()
            self.db = DB()
        def reserve(self, amount): self.reserved += amount
        def usage(self): return {'database_bytes': 300_000_000, 'object_bytes': 4_000_000, 'egress_bytes': 1_000_000, 'audit_bytes': 1}

    class Storage:
        def __init__(self, previous=None): self.previous, self.posts = previous, {}
        def request(self, method, key, **kw):
            if method == 'GET':
                return (200, json.dumps(self.previous).encode()) if self.previous else (404, b'')
            self.posts[key] = (kw['data'], kw['upsert'], kw['content_type'])
            return 200, b''

    def test_skips_without_new_collection_run_and_reads_nothing(self):
        from sentra import wellness_refresh as w
        finished = datetime(2026, 10, 11, 0, 5, tzinfo=UTC)
        storage = self.Storage({'source_run': finished.isoformat()})
        with mock.patch.object(w, 'build') as build:
            result = w.refresh(self.Reader(finished), Limits(), storage, log=lambda *_: None)
        self.assertEqual(result['status'], 'skipped')
        build.assert_not_called()
        self.assertEqual(storage.posts, {})

    def test_publishes_tiers_then_board_with_capacity_check(self):
        from sentra import wellness_refresh as w
        with tempfile.TemporaryDirectory() as folder:
            write(folder, sleep_rows() + [row('p02', 'whoop', 'recovery', 'c1', '/score/recovery_score', value=70),
                                       row('p02', 'whoop', 'recovery', 'c1', '/score/hrv_rmssd_milli', value=61)])
            objects = {p.relative_to(folder).as_posix(): p.read_bytes() for p in Path(folder).rglob('*.parquet')}
        storage = self.Storage()
        with mock.patch.object(w, 'build', return_value=(objects, {})), mock.patch.object(w, 'publish') as publish:
            result = w.refresh(self.Reader(datetime(2026, 10, 11, tzinfo=UTC)), Limits(), storage, now=NOW, log=lambda *_: None)
        publish.assert_called_once()
        data, upsert, kind = storage.posts['board/board.json']
        board = json.loads(data)
        self.assertEqual((upsert, kind, result['status']), (True, 'application/json', 'published'))
        self.assertEqual({p['id']: p['device'] for p in board['people']}, {'p01': 'Fitbit', 'p02': 'WHOOP'})
        self.assertEqual(board['source_run'], '2026-10-11T00:00:00+00:00')
        tight = Limits(object_bytes=4_000_000 + 20_000_000 + 1, reserve_bytes=20_000_000)
        with mock.patch.object(w, 'build', return_value=(objects, {})), mock.patch.object(w, 'publish'):
            with self.assertRaises(Exception):
                w.refresh(self.Reader(datetime(2026, 10, 12, tzinfo=UTC)), tight, self.Storage(), now=NOW, log=lambda *_: None)

    def test_collector_storage_requires_complete_credentials(self):
        from sentra import wellness_refresh as w
        for env in ({}, {'SENTRA_COLLECTOR_CONFIG': json.dumps({'credentials': {'url': 'https://x.supabase.co'}})}):
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(SentraError):
                w.collector_storage()


class ViewerBoardTests(unittest.TestCase):
    def test_missing_board_is_an_empty_board_not_an_error(self):
        from sentra.viewer_reader import ViewerReader
        reader = ViewerReader.__new__(ViewerReader)
        reader.credentials, reader.principal, reader.reserve = {}, lambda: None, lambda amount: None
        with mock.patch('sentra.viewer_reader.PrivateStorage') as storage:
            storage.return_value.request.return_value = (400, b'{"error":"not_found"}')
            self.assertEqual(reader.board()['people'], [])
            storage.return_value.request.return_value = (200, b'{"people":[{"id":"p01","days":[]}]}')
            self.assertEqual(reader.board()['people'][0]['id'], 'p01')
            storage.return_value.request.return_value = (200, b'not json')
            with self.assertRaises(SentraError):
                reader.board()


if __name__ == '__main__':
    unittest.main()
