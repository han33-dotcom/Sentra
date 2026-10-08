"""Operator-only secret setup through GitHub REST; never creates commits/runs."""
import base64,json,os,subprocess
import requests
from .errors import SentraError

REPOSITORY='han33-dotcom/Sentra'


def configure(setup):
    try:
        from nacl.public import PublicKey,SealedBox
    except ImportError:
        raise SentraError('Install operator-only PyNaCl==1.6.2 before configuring GitHub secrets.') from None
    result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
        text=True,capture_output=True,timeout=30,env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never'))
    credential=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or not credential.get('password'):
        raise SentraError('Existing Git credential unavailable; sign in with Git Credential Manager. Do not paste tokens into chat.')
    session=requests.Session()
    session.headers.update({'Authorization':'Bearer '+credential['password'],'Accept':'application/vnd.github+json',
                            'X-GitHub-Api-Version':'2026-03-10'})
    def api(method,path,*,body=None,expected=(200,)):
        response=session.request(method,'https://api.github.com'+path,json=body,timeout=(10,30),allow_redirects=False)
        if response.status_code not in expected:
            raise SentraError(f'GitHub setup failed (HTTP {response.status_code}); check repository/admin permissions. No credentials displayed.')
        return response.json() if response.content else None
    base='/repos/'+REPOSITORY
    try:
        repo=api('GET',base)
        if repo.get('private') is not True or not repo.get('permissions',{}).get('admin'):
            raise SentraError('A private repository and repository admin permission are required before secret setup.')
        # Pause the schedule before placing collector credentials in repository secrets.
        for name in ('SENTRA_COLLECTION_ENABLED','SENTRA_ZERO_SPEND_CONFIRMED'):
            path=base+'/actions/variables/'+name
            variable=api('GET',path,expected=(200,404))
            if variable and variable.get('name')==name:
                api('PATCH',path,body={'name':name,'value':'false'},expected=(204,))
            else:
                api('POST',base+'/actions/variables',body={'name':name,'value':'false'},expected=(201,))
        public=api('GET',base+'/actions/secrets/public-key')
        box=SealedBox(PublicKey(base64.b64decode(public['key'])))
        for name,value in {'SENTRA_COLLECTOR_CONFIG':json.dumps(setup['config']),'SENTRA_TOKEN_KEY':setup['token_key']}.items():
            encrypted=base64.b64encode(box.encrypt(value.encode())).decode()
            api('PUT',base+'/actions/secrets/'+name,body={'encrypted_value':encrypted,'key_id':public['key_id']},expected=(201,204))
            check=api('GET',base+'/actions/secrets/'+name)
            if check.get('name')!=name: raise SentraError('GitHub secret metadata verification failed.')
        for name in ('SENTRA_COLLECTION_ENABLED','SENTRA_ZERO_SPEND_CONFIRMED'):
            variable=api('GET',base+'/actions/variables/'+name)
            if variable['value']!='false': raise SentraError('GitHub execution gates could not be verified.')
        user=api('GET','/user')
        return {'repository':REPOSITORY,'private':True,'default_branch':repo['default_branch'],
                'account_plan':user.get('plan',{}).get('name','unavailable'),
                'secrets_configured':2,'schedule_enabled':False,'zero_spend_confirmed':False,'workflow_published':False}
    finally: session.close()
