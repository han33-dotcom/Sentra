"""Participant-only web service. Never mount this on the read-only wellness API."""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .enrollment import EnrollmentError, EnrollmentSettings, ProviderLogin
from .enrollment_store import open_store

ASSETS = Path(__file__).with_name('enrollment')


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    invite: str | None = Field(default=None, max_length=100)


class Choices(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sharing: Literal['group_only', 'individual'] = 'group_only'
    demonstration: StrictBool = False
    accepted: StrictBool = False


class Connect(Choices):
    provider: Literal['google_health', 'whoop']


def create_app(settings=None, store_factory=None, provider_login=None):
    app = FastAPI(title='Sentra participation', docs_url=None, redoc_url=None, openapi_url=None)

    @lru_cache(maxsize=1)
    def configuration():
        return settings or EnrollmentSettings.from_env()

    def login():
        return provider_login or ProviderLogin(configuration())

    @contextmanager
    def store():
        with (store_factory or open_store)(configuration()) as repository:
            yield repository

    def sid(request):
        return request.cookies.get(configuration().cookie, '')

    def cookie(response, value):
        c = configuration()
        response.set_cookie(c.cookie, value, max_age=1800, secure=c.secure, httponly=True, samesite='lax', path='/')
        return response

    @app.exception_handler(EnrollmentError)
    async def expected_error(request, error):
        return JSONResponse({'message': str(error)}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default validation response echoes submitted inputs, including invitations.
        return JSONResponse({'message': 'Check your choices and try again.'}, status_code=422)

    @app.middleware('http')
    async def boundary(request, call_next):
        try:
            c = configuration()
            if request.url.netloc != c.origin.split('://', 1)[1] or (c.secure and request.url.scheme != 'https'):
                raise EnrollmentError('Use the original Sentra invitation address.', 400)
            if request.method not in ('GET', 'HEAD'):
                if request.headers.get('origin') != c.origin:
                    raise EnrollmentError('Please submit choices from the Sentra page.', 403)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 8192:
                        raise EnrollmentError('Request is too large.', 413)
                request._body = bytes(body)  # Starlette caches this for the downstream JSON reader.
            response = await call_next(request)
        except EnrollmentError as error:
            response = JSONResponse({'message': str(error)}, status_code=error.status)
        except Exception:
            response = JSONResponse({'message': 'Enrollment is temporarily unavailable. Please try later.'}, status_code=503)
        response.headers.update({
            'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        })
        if request.url.scheme == 'https':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/')
    def home():
        return RedirectResponse('/join', status_code=303)

    @app.get('/join')
    @app.get('/account')
    def page():
        return FileResponse(ASSETS / 'join.html')

    @app.get('/assets/join.css')
    def stylesheet():
        return FileResponse(ASSETS / 'join.css', media_type='text/css')

    @app.get('/assets/join.js')
    def javascript():
        return FileResponse(ASSETS / 'join.js', media_type='text/javascript')

    @app.get('/assets/favicon.svg')
    def favicon():
        return FileResponse(ASSETS / 'favicon.svg', media_type='image/svg+xml')

    @app.post('/api/session')
    def start(request: Request, data: Start):
        with store() as repository:
            new_sid, _ = repository.start(data.invite, request.client.host if request.client else 'unknown')
            result = repository.status(new_sid)
        result.update(providers_available=list(configuration().clients), consent_version=configuration().consent_version)
        return cookie(JSONResponse(result), new_sid)

    @app.get('/api/status')
    def status(request: Request):
        with store() as repository:
            result = repository.status(sid(request))
        result.update(providers_available=list(configuration().clients), consent_version=configuration().consent_version)
        return result

    @app.post('/api/connect')
    def connect(request: Request, data: Connect):
        if data.provider not in configuration().clients:
            raise EnrollmentError('This device provider is not available yet.')
        with store() as repository:
            value = repository.session(sid(request))
            repository.check_csrf(value, request.headers.get('x-csrf-token', ''))
            url, pending = login().begin(data.provider)
            repository.pending(sid(request), request.headers.get('x-csrf-token', ''), data.provider, data.model_dump(exclude={'provider'}), pending)
        return {'url': url}

    @app.get('/oauth/{provider}/callback')
    def callback(provider: str, request: Request):
        if provider not in configuration().clients:
            raise EnrollmentError('Unsupported connection.')
        query = request.query_params
        if len(query.getlist('state')) != 1 or len(query.get('state', '')) > 100:
            raise EnrollmentError('This connection attempt is invalid. Please connect again.')
        with store() as repository:
            pending = repository.consume(sid(request), provider, query['state'])
        if 'error' in query:
            return RedirectResponse('/join?connection=cancelled', status_code=303)
        if len(query.getlist('code')) != 1 or not 0 < len(query['code']) <= 4096:
            raise EnrollmentError('No connection code received. Please connect again.')
        try:
            identity, token = login().finish(pending, query['code'])
            with store() as repository:
                new_sid = repository.finish(sid(request), pending, identity, token, login())
        except EnrollmentError:
            return RedirectResponse('/join?connection=failed', status_code=303)
        return cookie(RedirectResponse('/account', status_code=303), new_sid)

    @app.post('/api/choices')
    def choices(request: Request, data: Choices):
        if not data.accepted:
            raise EnrollmentError('Please confirm your participation choices.')
        with store() as repository:
            repository.change(sid(request), request.headers.get('x-csrf-token', ''), data.model_dump())
        return {'message': 'Your sharing choices have been saved.'}

    @app.post('/api/withdraw')
    def withdraw(request: Request):
        with store() as repository:
            repository.change(sid(request), request.headers.get('x-csrf-token', ''), withdraw=True)
        return {'message': 'You have withdrawn. Sentra collection has stopped for your participation.'}

    @app.post('/api/logout')
    def logout(request: Request):
        with store() as repository:
            repository.logout(sid(request), request.headers.get('x-csrf-token', ''))
        result = JSONResponse({'message': 'Signed out.'})
        result.delete_cookie(configuration().cookie, path='/', secure=configuration().secure, httponly=True, samesite='lax')
        return result

    return app


app = create_app()
