"""Real Streamlit rendering with synthetic OIDC identities and synthetic rows."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from sentra.shared import Limits


class FakeUser:
    def __init__(self,**overrides):
        self.claims=dict(is_logged_in=True,email='team@example.test',email_verified=True,
                        iss='https://accounts.google.com',exp=time.time()+3600,**overrides)
    @property
    def is_logged_in(self): return self.claims['is_logged_in']
    def to_dict(self): return self.claims.copy()


class FakeReader:
    limits=Limits()
    def catalog(self): return [{'participant_id':'p99','provider':'whoop','dataset':'sleep'}]
    def metrics(self,selection):
        return [{'metric':'/synthetic','unit':'beats/min','value_kind':'vendor_summary'}]
    def records(self,selection):
        return [{'participant_id':'p99','provider':'whoop','dataset':'sleep','record_key':'synthetic',
                 'source_response_id':'a'*64,'collected_at':datetime(2026,10,8,tzinfo=timezone.utc),
                 'record':{'interval_start':'2026-10-06T22:00:00Z','interval_end':'2026-10-07T05:00:00Z',
                           'score_state':'SCORED','provisional':True,'vendor_fields':{
                               'score':{'sleep_performance_percentage':80,'stage_summary':{
                                   'total_light_sleep_time_milli':14400000,'total_rem_sleep_time_milli':3600000,
                                   'total_slow_wave_sleep_time_milli':3600000}}}}}]
    def recoveries(self,selection,records):return []
    def measurements(self,selection):
        return [{'participant_id':'p99','provider':'whoop','dataset':'sleep','record_key':'synthetic',
                 'metric':'/synthetic','value':Decimal('70.12345678901234'),'vendor_value':Decimal('70.12345678901234'),
                 'unit':'beats/min','vendor_unit':'beats/min','value_kind':'vendor_summary',
                 'availability':'available','measured_at':datetime(2026,10,7,12,tzinfo=timezone.utc),
                 'provisional':True,'score_state':'SCORED','resolution_seconds':60,'source_response_id':'a'*64,
                 'collected_at':datetime(2026,10,8,12,tzinfo=timezone.utc)}]
    def sessions(self,selection,rows): return []
    def manifests(self,selection,rows):
        return [{'response_id':'a'*64,'content_sha256':'b'*64,'requested_resolution':'synthetic session',
                 'collected_at':datetime(2026,10,8,12,tzinfo=timezone.utc)}]
    def status(self,selection): return {'connection':[],'runs':[]}
    def usage(self): return {'database_bytes':268_000_000,'object_bytes':1000,'egress_bytes':1_000_000,
                           'observation':{'enabled':False},'budget_verified_at':'synthetic'}
    def original(self,source,selection):
        import gzip
        return gzip.compress(b'{"synthetic":true}',mtime=0)


class ViewerAppTests(unittest.TestCase):
    def test_readable_chart_keeps_missing_dates_empty(self):
        from datetime import date
        from sentra.viewer_app import readable_chart
        from sentra.viewer_data import Selection
        selection=Selection('p99','whoop','sleep',date(2026,10,4),date(2026,10,7))
        chart=readable_chart([{'Date':'2026-10-05','Value':6}],selection,'Asleep','h',220).to_dict()
        self.assertEqual(chart['encoding']['x']['scale']['domain'],['2026-10-04','2026-10-05','2026-10-06'])
        self.assertEqual(chart['mark']['type'],'circle')
        self.assertEqual(sum(len(rows) for rows in chart['datasets'].values()),1)

    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(Path(__file__).resolve().parents[1]/'viewer'/'app.py',default_timeout=10)

    def test_readable_views_session_rows_and_private_curated_export(self):
        from sentra import viewer_app
        @contextmanager
        def reader():yield FakeReader()
        with patch.object(viewer_app.st,'user',FakeUser()),patch.object(viewer_app,'open_reader',reader):
            app=self.app();app.secrets['viewer']={'allowed_emails':['team@example.test']}
            app.run()
            # Keep the fixed synthetic October 7 rows inside an explicit seven-day range.
            app.date_input[0].set_value((date(2026,10,1),date(2026,10,7))).run()
            next(b for b in app.button if b.label=='Load selected data').click().run()
            self.assertFalse(app.exception);self.assertFalse(app.error)
            self.assertEqual(len(app.radio),1)
            nav=app.radio[0]
            self.assertEqual(nav.options,['Daily activity','Sleep','Workouts','Data availability','Wellness board'])
            nav.set_value('Sleep').run()
            self.assertFalse(app.exception);self.assertFalse(app.error)
            self.assertEqual(app.dataframe[0].value.iloc[0]['Asleep'],'6 h 00 min')
            self.assertEqual(list(app.dataframe[0].value.columns)[:2],['Date','Asleep'])
            self.assertEqual(app.dataframe[0].value.iloc[0]['Start'],'07 Oct 01:00 +0300')
            self.assertEqual(app.metric[0].value,'6 h 00 min')
            self.assertEqual(app.metric[1].value,'1 / 7')
            plot=next(s for s in app.selectbox if s.label=='Explore a metric')
            plot.set_value('WHOOP sleep performance').run()
            app.radio[0].set_value('Workouts').run()
            app.radio[0].set_value('Sleep').run()
            self.assertEqual(next(s for s in app.selectbox if s.label=='Explore a metric').value,'WHOOP sleep performance')
            next(b for b in app.button if b.label=='Prepare readable CSV').click().run()
            self.assertIn(b'sentra_calculation',app.session_state['audit_readable_csv'])
            self.assertEqual(len(app.get('iframe')),1)
            app.radio[0].set_value('Data availability').run()
            self.assertIn('audit_readable_csv',app.session_state)
            self.assertTrue(any('Dataset' in frame.value.columns for frame in app.dataframe))
            app.text_input[0].set_value('changed').run()
            self.assertNotIn('audit_readable_csv',app.session_state)
            self.assertNotIn('audit_chart_choice_Sleep',app.session_state)

    def test_session_times_distinguish_repeated_beirut_hour(self):
        from datetime import date
        from sentra import viewer_app
        class RepeatedHourReader(FakeReader):
            def records(self,selection):
                rows=super().records(selection)
                rows[0]['record'].update(interval_start='2026-10-24T20:50:00Z',interval_end='2026-10-24T21:10:00Z')
                return rows
        @contextmanager
        def reader():yield RepeatedHourReader()
        with patch.object(viewer_app.st,'user',FakeUser()),patch.object(viewer_app,'open_reader',reader):
            app=self.app();app.secrets['viewer']={'allowed_emails':['team@example.test']}
            app.run()
            app.date_input[0].set_value((date(2026,10,24),date(2026,10,24))).run()
            next(b for b in app.button if b.label=='Load selected data').click().run()
            app.radio[0].set_value('Sleep').run()
            row=app.dataframe[0].value.iloc[0]
            self.assertEqual(row['Start'],'24 Oct 23:50 +0300')
            self.assertEqual(row['End'],'24 Oct 23:10 +0200')

    def test_unlisted_logged_out_unverified_or_expired_identity_reads_nothing(self):
        for overrides in ({'is_logged_in':False},{'email':'unlisted@example.test'},
                          {'email_verified':False},{'exp':time.time()-1}):
            with self.subTest(overrides=overrides):
                from sentra import viewer_app
                read=Mock()
                user=FakeUser();user.claims.update(overrides)
                with patch.object(viewer_app.st,'user',user),patch.object(viewer_app,'open_reader',read):
                    app=self.app()
                    app.secrets['viewer']={'allowed_emails':['team@example.test']}
                    app.run()
                    self.assertFalse(app.exception)
                    read.assert_not_called()
                    self.assertEqual(len(app.dataframe),0)
                    self.assertEqual(len(app.get('iframe')),0)
                    if user.is_logged_in:
                        self.assertIn('Sign out',[b.label for b in app.button])

    def test_allowed_render_csv_original_and_filter_change_clears_downloads(self):
        from sentra import viewer_app
        @contextmanager
        def reader(): yield FakeReader()
        with patch.object(viewer_app.st,'user',FakeUser()),patch.object(viewer_app,'open_reader',reader):
            app=self.app()
            app.secrets['viewer']={'allowed_emails':['team@example.test']}
            app.run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label=='Load selected data').click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            next(b for b in app.button if b.label=='Load audit details').click().run()
            next(b for b in app.button if b.label=='Prepare filtered CSV').click().run()
            self.assertIn(b'70.12345678901234',app.session_state['audit_csv'])
            self.assertEqual(len(app.get('iframe')),1)
            next(b for b in app.button if b.label=='Prepare original response').click().run()
            self.assertEqual(len(app.get('iframe')),2)
            app.text_input[0].set_value('no match').run()
            self.assertNotIn('audit_csv',app.session_state)
            self.assertNotIn('audit_original',app.session_state)
            self.assertEqual(len(app.get('iframe')),0)

    def test_session_expiry_clears_prepared_data_before_render(self):
        from sentra import viewer_app
        user=FakeUser()
        @contextmanager
        def reader(): yield FakeReader()
        with patch.object(viewer_app.st,'user',user),patch.object(viewer_app,'open_reader',reader):
            app=self.app();app.secrets['viewer']={'allowed_emails':['team@example.test']}
            app.run()
            next(b for b in app.button if b.label=='Load selected data').click().run()
            next(b for b in app.button if b.label=='Load audit details').click().run()
            next(b for b in app.button if b.label=='Prepare filtered CSV').click().run()
            user.claims['exp']=time.time()-1
            app.run()
            self.assertNotIn('audit_result',app.session_state)
            self.assertEqual(len(app.get('iframe')),0)
            self.assertTrue(app.error)

    def test_incomplete_date_change_clears_results_and_prepared_downloads(self):
        from sentra import viewer_app
        @contextmanager
        def reader():yield FakeReader()
        with patch.object(viewer_app.st,'user',FakeUser()),patch.object(viewer_app,'open_reader',reader):
            app=self.app();app.secrets['viewer']={'allowed_emails':['team@example.test']}
            app.run()
            next(b for b in app.button if b.label=='Load selected data').click().run()
            next(b for b in app.button if b.label=='Load audit details').click().run()
            next(b for b in app.button if b.label=='Prepare filtered CSV').click().run()
            prior=app.date_input[0].value
            app.date_input[0].set_value((prior[0],)).run()
            self.assertNotIn('audit_csv',app.session_state)
            self.assertNotIn('audit_result',app.session_state)
            app.date_input[0].set_value(prior).run()
            self.assertEqual(len(app.get('iframe')),0)


if __name__=='__main__': unittest.main()
