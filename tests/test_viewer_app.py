"""Real Streamlit rendering with synthetic OIDC identities and synthetic rows."""
from contextlib import contextmanager
from datetime import datetime, timezone
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
    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(Path(__file__).resolve().parents[1]/'viewer'/'app.py',default_timeout=10)

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
            next(b for b in app.button if b.label=='Prepare filtered CSV').click().run()
            prior=app.date_input[0].value
            app.date_input[0].set_value((prior[0],)).run()
            self.assertNotIn('audit_csv',app.session_state)
            self.assertNotIn('audit_result',app.session_state)
            app.date_input[0].set_value(prior).run()
            self.assertEqual(len(app.get('iframe')),0)


if __name__=='__main__': unittest.main()
