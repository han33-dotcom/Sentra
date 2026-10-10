"""Synthetic provider-specific display, grouping and exact export behavior."""
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sentra import viewer_data


def record(dataset, key, fields, **context):
    return dict(participant_id='p99',provider='whoop',dataset=dataset,record_key=key,
                source_response_id='a'*64,collected_at=datetime(2026,10,8,tzinfo=timezone.utc),
                record=dict(vendor_fields=fields,provisional=True,score_state='SCORED',
                            interval_start='2026-10-06T22:00:00Z',interval_end='2026-10-07T05:00:00Z',
                            timestamp_basis='vendor_interval',resolution_description='original API resolution',
                            **context))


class CuratedTests(unittest.TestCase):
    def module(self):
        from sentra import curated
        return curated

    def test_provider_dictionary_does_not_map_by_last_field_name(self):
        m=self.module()
        self.assertIsNone(m.definition('whoop','sleep','/metadata/recovery_score'))
        self.assertIsNone(m.definition('google_health','sleep','/score/recovery_score'))
        d=m.definition('whoop','recovery','/score/recovery_score')
        self.assertEqual((d.label,d.unit,d.kind),('WHOOP recovery','%','vendor_score'))
        self.assertEqual(m.definition('google_health','exercise','/exercise/activeDuration').unit,'s')

    def test_sessions_use_wake_day_exact_durations_and_sleep_id_recovery(self):
        m=self.module()
        sleep=record('sleep','sleep-one',{'nap':False,'score':{'stage_summary':{
            'total_light_sleep_time_milli':14400000,'total_slow_wave_sleep_time_milli':3600000,
            'total_rem_sleep_time_milli':3600000},'sleep_performance_percentage':80}})
        recovery=record('recovery','cycle-one',{'sleep_id':'sleep-one','score':{'recovery_score':61}})
        wrong=record('recovery','cycle-two',{'sleep_id':'other','score':{'recovery_score':99}})
        result=m.curate([sleep,recovery,wrong],date(2026,10,6),date(2026,10,9))
        table=result['Sleep']
        self.assertEqual(len(table),1)
        self.assertEqual(table[0]['Date'],'2026-10-07')
        self.assertEqual(table[0]['Asleep'],'6 h 00 min')
        self.assertEqual(table[0]['WHOOP recovery'],'61 %')
        self.assertTrue(any(r['Metric']=='Asleep' and r['Exact value']=='21600000' and
                            r['Classification']=='sentra_calculation' for r in result['export']))

    def test_explicit_null_unscored_missing_day_and_conflicting_sources(self):
        m=self.module()
        def daily(key,value,score='SCORED'):
            r=record('daily_steps',key,{'steps':{'countSum':value}},civil_date={'year':2026,'month':10,'day':7})
            r['provider']='google_health';r['record']['score_state']=score
            r['record']['interval_start']=None;r['record']['interval_end']=None
            return r
        result=m.curate([daily('a',None)],date(2026,10,7),date(2026,10,9))
        self.assertEqual(result['Daily activity'][0]['Steps'],'Missing (explicit null)')
        self.assertEqual(result['Daily activity'][1]['Steps'],'Not returned')
        self.assertEqual(result['points'],[])
        result=m.curate([daily('a','12'),daily('b','14')],date(2026,10,7),date(2026,10,8))
        self.assertIn('Multiple',result['Daily activity'][0]['Steps'])
        self.assertEqual(result['points'],[])
        s=record('sleep','s',{'score':{'sleep_performance_percentage':80}})
        s['record']['score_state']='UNSCORED'
        result=m.curate([s],date(2026,10,7),date(2026,10,8))
        self.assertEqual(result['Sleep'][0]['WHOOP sleep performance'],'Unscored')

    def test_duration_parser_rejects_bad_nonfinite_and_negative_values(self):
        m=self.module()
        d=m.definition('google_health','exercise','/exercise/activeDuration')
        self.assertEqual(m.number('123.450s',d),Decimal('123.450'))
        for value in ('NaN','Infinity','bad','-12s',True):
            self.assertIsNone(m.number(value,d))

    def test_workout_crossing_repeated_hour_uses_physical_duration(self):
        m=self.module()
        r=record('workout','w',{'sport_name':'Walking'})
        r['record'].update(interval_start='2026-10-24T20:50:00Z',interval_end='2026-10-24T21:10:00Z')
        result=m.curate([r],date(2026,10,24),date(2026,10,25))
        self.assertEqual(result['Workouts'][0]['Session duration'],'0 h 20 min')

    def test_provider_failure_without_dataset_is_visible_after_previous_success(self):
        from sentra import viewer_data as m
        self.assertTrue(hasattr(m,'fetch_status'),'Provider failure interpretation missing')
        success=datetime(2026,10,7,tzinfo=timezone.utc)
        failed=datetime(2026,10,8,tzinfo=timezone.utc)
        state={'connection':[{'last_success_at':success}],'runs':[{'status':'failed','started_at':failed,
                'failures':[{'message':'Reconnect required'}]}]}
        self.assertEqual(m.fetch_status(state,'sleep')[0],'Fetch failed / needs review')
        state['connection'][0]['last_success_at']=failed+__import__('datetime').timedelta(days=1)
        self.assertEqual(m.fetch_status(state,'sleep')[0],'Successful fetch recorded')

    def test_readable_csv_retains_precision_and_formula_safety(self):
        m=self.module()
        r=record('recovery','r',{'score':{'hrv_rmssd_milli':Decimal('31.81356200001')}})
        r['record']['civil_date']='2026-10-07'
        result=m.curate([r],date(2026,10,7),date(2026,10,8))
        payload=m.curated_csv(result['export'])
        self.assertIn(b'31.81356200001',payload)
        self.assertIn(b'WHOOP HRV',payload)
        self.assertEqual(result['Daily activity'][0]['WHOOP HRV'],'31.8 ms')
