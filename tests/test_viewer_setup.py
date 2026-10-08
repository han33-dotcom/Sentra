from pathlib import Path
import tempfile
import unittest

from sentra.errors import SentraError


class ViewerSetupTests(unittest.TestCase):
    def module(self):
        try:
            from sentra import viewer_setup
            return viewer_setup
        except ImportError: self.fail('Viewer secret preparation not implemented')

    def test_only_viewer_credentials_and_separate_identity_client_are_exported(self):
        m=self.module()
        c={'db':{'user':'sentra_viewer.test','password':'synthetic','host':'synthetic.pooler.supabase.com',
                 'port':5432,'dbname':'postgres','sslmode':'verify-full','sslrootcert':'discard'},
           'url':'https://synthetic.supabase.co','publishable_key':'synthetic',
           'storage_email':'service@example.test','storage_password':'synthetic'}
        client={'web':{'client_id':'synthetic.apps.googleusercontent.com','client_secret':'synthetic',
                       'redirect_uris':['http://localhost:8501/oauth2callback']}}
        import tomllib
        from sentra.shared import Limits
        result=m.build_secrets(c,Limits(),'CERTIFICATE',client,['team@example.test'],
                               'http://localhost:8501')
        value=tomllib.loads(result)
        self.assertEqual(value['auth']['redirect_uri'],'http://localhost:8501/oauth2callback')
        self.assertEqual(value['auth']['client_kwargs']['scope'],'openid email profile')
        self.assertNotIn('refresh_token',result)
        self.assertNotIn('token_key',result)
        self.assertNotIn('sslrootcert',value['viewer']['db'])
        with self.assertRaises(SentraError):
            m.build_secrets({**c,'db':{**c['db'],'user':'sentra_collector.test'}},Limits(),
                             'CERT',client,['team@example.test'],'http://localhost:8501')
        with self.assertRaises(SentraError):
            m.build_secrets(c,Limits(),'CERT',{'installed':client['web']},['team@example.test'],'http://localhost:8501')
        with self.assertRaises(SentraError):
            m.build_secrets(c,Limits(),'CERT',client,['team@example.test'],'https://unregistered.streamlit.app')

    def test_hosted_runtime_rejects_collector_credentials_and_unknown_secret_fields(self):
        m=self.module()
        from sentra.viewer_config import runtime_settings
        with tempfile.TemporaryDirectory() as folder:
            from sentra.shared import Limits
            from dataclasses import asdict
            secrets={'viewer':{'db':{'user':'sentra_collector.test'},'limits':asdict(Limits()),
                               'confirmed_free_plan':True,'allowed_emails':['team@example.test'],
                               'certificate_pem':'synthetic'}}
            with self.assertRaises(SentraError): runtime_settings(secrets,Path(folder))


if __name__=='__main__': unittest.main()
