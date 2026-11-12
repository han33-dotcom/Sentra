"""Transactional enrollment store, isolated from the dashboard's read-only role."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import hmac
import json
import secrets
import time

import psycopg

from .cloud_tokens import TokenRepository
from .enrollment import EnrollmentError, digest

FITBIT_LINK_CREDENTIAL_STATES = ('active', 'refresh_pending')
FITBIT_LINK_IDENTITY_PREFIX = 'fitbit-link:'


@contextmanager
def open_store(settings):
    try:
        db_config = dict(settings.db)
        local = not settings.secure and db_config.get('host') in ('localhost', '127.0.0.1')
        if (db_config.get('user', '').split('.')[0] != 'sentra_enrollment'
                or (not local and db_config.get('sslmode') != 'verify-full')):
            raise ValueError
        with psycopg.connect(**db_config, autocommit=True, connect_timeout=10,
                application_name='sentra-enrollment',
                options='-c statement_timeout=15000 -c lock_timeout=5000') as db:
            # Every database request consumes the existing conservative shared budget.
            db.execute('select collector_private.reserve_egress(65536,3500000000)')
            if db.execute('select pg_database_size(current_database())').fetchone()[0] + 65536 >= 380_000_000:
                raise EnrollmentError('Enrollment is temporarily unavailable. Please try later.', 503)
            yield EnrollmentStore(db, settings)
    except EnrollmentError:
        raise
    except Exception:
        raise EnrollmentError('Enrollment is temporarily unavailable. Please try later.', 503) from None


class EnrollmentStore:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def _encode(self, value):
        return self.settings.cipher.encrypt(json.dumps(value).encode())

    def _save(self, sid, value):
        self.db.execute('''insert into enrollment_private.sessions values (%s,%s,now()+interval '30 minutes')
            on conflict(session_hash) do update set encrypted_state=excluded.encrypted_state,
            expires_at=excluded.expires_at''', (digest(sid), self._encode(value)))

    def _lock_participant(self, pid):
        key = int.from_bytes(bytes.fromhex(digest('enrollment/' + pid))[:8], 'big', signed=True)
        self.db.execute('select pg_advisory_xact_lock(%s)', (key,))

    def session(self, sid, *, locked=False):
        if not sid or len(sid) > 100:
            raise EnrollmentError('Please open your invitation or sign in again.', 401)
        row = self.db.execute('''select encrypted_state from enrollment_private.sessions
            where session_hash=%s and expires_at>now()''' + (' for update' if locked else ''), (digest(sid),)).fetchone()
        if not row:
            raise EnrollmentError('Your session expired. Please open your invitation or sign in again.', 401)
        return json.loads(self.settings.cipher.decrypt(bytes(row[0])))

    def invite(self, hashed, org_id, seats, days):
        if not 1 <= seats <= 100 or not 1 <= days <= 30:
            raise EnrollmentError('Invalid invitation limits.')
        self.db.execute('insert into enrollment_private.invites values (%s,%s,%s,now()+%s)',
                        (hashed, org_id, seats, timedelta(days=days)))

    def _require_legacy_fitbit(self, pid):
        eligible = self.db.execute('''select exists (
            select 1 from collector_private.provider_credentials
            where participant_id=%s and provider='google_health' and refresh_status=any(%s) for share
        ) and not exists (
            select 1 from org.memberships where participant_id=%s
        ) and not exists (
            select 1 from enrollment_private.identities where participant_id=%s
        )''', (pid, list(FITBIT_LINK_CREDENTIAL_STATES), pid, pid)).fetchone()[0]
        if not eligible:
            raise EnrollmentError('This participant is no longer eligible for a Fitbit link.', 409)

    def operator_managed_fitbit(self, pid):
        return self.db.execute('''select exists (select 1 from enrollment_private.identities
            where participant_id=%s and provider='google_health' and starts_with(identity_hash,%s))''',
            (pid, FITBIT_LINK_IDENTITY_PREFIX)).fetchone()[0]

    def invite_fitbit_link(self, hashed, org_id, pid, email_hash, days):
        if not 1 <= days <= 30:
            raise EnrollmentError('Invalid invitation limits.')
        with self.db.transaction():
            self.db.execute('''delete from enrollment_private.fitbit_link_invites
                where participant_id=%s and expires_at<=now()''', (pid,))
            self._lock_participant(pid)
            self._require_legacy_fitbit(pid)
            self.db.execute('insert into enrollment_private.fitbit_link_invites values (%s,%s,%s,%s,now()+%s)',
                            (hashed, org_id, pid, email_hash, timedelta(days=days)))

    def start(self, invite, remote):
        with self.db.transaction():
            # Store an unlinkable ten-minute rate bucket, not the visitor's IP address.
            bucket = self.settings.identity('rate', f'{remote}/{int(time.time() // 600)}')
            count = self.db.execute('''insert into enrollment_private.rate_limits values (%s,1,now()+interval '10 minutes')
                on conflict(bucket_hash) do update set attempts=enrollment_private.rate_limits.attempts+1
                returning attempts''', (bucket,)).fetchone()[0]
            if count > 20:
                raise EnrollmentError('Too many attempts. Please try again in ten minutes.', 429)
            self.db.execute('delete from enrollment_private.sessions where expires_at<now()')
            self.db.execute('delete from enrollment_private.rate_limits where expires_at<now()')
            # Bound private session storage even if a public endpoint is abused.
            self.db.execute('select pg_advisory_xact_lock(280028)')
            if self.db.execute('select count(*) from enrollment_private.sessions').fetchone()[0] >= 500:
                raise EnrollmentError('Enrollment is busy. Please try again shortly.', 429)
            value = {'csrf': secrets.token_urlsafe(32)}
            if invite:
                if not 30 <= len(invite) <= 100:
                    raise EnrollmentError('This invitation is unavailable. Ask for a new link.', 410)
                hashed = digest(invite)
                row = self.db.execute('''select i.org_id,o.display_name from enrollment_private.invites i
                    join org.organizations o using(org_id) where i.invite_hash=%s
                    and i.expires_at>now() and i.remaining>0''', (hashed,)).fetchone()
                if not row:
                    row = self.db.execute('''select i.org_id,o.display_name,i.email_hash
                        from enrollment_private.fitbit_link_invites i join org.organizations o using(org_id)
                        where i.invite_hash=%s and i.expires_at>now()''', (hashed,)).fetchone()
                    if row:
                        value['fitbit_email_hash'] = row[2]
                if not row:
                    raise EnrollmentError('This invitation is full or expired. Ask for a new link.', 410)
                value.update(invite_hash=hashed, org_id=row[0], organization=row[1])
            sid = secrets.token_urlsafe(32)
            self._save(sid, value)
            return sid, value

    def pending(self, sid, csrf, provider, choices, pending):
        with self.db.transaction():
            value = self.session(sid, locked=True)
            self.check_csrf(value, csrf)
            if value.get('invite_hash') and not choices.get('accepted'):
                raise EnrollmentError('Please confirm your participation choices.')
            if value.get('fitbit_email_hash') and (
                provider != 'google_health' or pending.get('fitbit_email_hash') != value['fitbit_email_hash']
            ):
                raise EnrollmentError('Use the original Fitbit account for this link.', 403)
            value.pop('claim', None)  # A new attempt supersedes an already exchanging callback.
            value['pending'] = {**pending, 'choices': choices,
                'expected_pid': (value.get('account') or {}).get('participant_id')}
            self._save(sid, value)

    @staticmethod
    def check_csrf(value, csrf):
        if not csrf or not csrf.isascii() or not hmac.compare_digest(value['csrf'], csrf):
            raise EnrollmentError('Please refresh this page and try again.', 403)

    def consume(self, sid, provider, state):
        with self.db.transaction():
            value = self.session(sid, locked=True)
            pending = value.get('pending') or {}
            if (not state or not state.isascii() or pending.get('provider') != provider
                    or not hmac.compare_digest(pending.get('state', ''), state)
                    or time.time() - pending.get('started', 0) > 600):
                raise EnrollmentError('This connection attempt expired. Please connect again.')
            del value['pending']  # Persist consumption before contacting the provider.
            value['claim'] = digest(state)
            self._save(sid, value)
            return pending

    def finish(self, sid, pending, identity_hash, token, login):
        provider = pending['provider']
        with self.db.transaction():
            value = self.session(sid, locked=True)
            if value.get('claim') != digest(pending['state']):
                raise EnrollmentError('Another connection attempt has replaced this one. Please retry.')
            # Serializes duplicate callbacks in different browsers before identity creation.
            key = int.from_bytes(bytes.fromhex(digest(provider + identity_hash))[:8], 'big', signed=True)
            self.db.execute('select pg_advisory_xact_lock(%s)', (key,))
            identity_keys = [identity_hash]
            if provider == 'google_health':
                identity_keys.append(FITBIT_LINK_IDENTITY_PREFIX + identity_hash)
            row = self.db.execute('''select participant_id,identity_hash from enrollment_private.identities
                where provider=%s and identity_hash=any(%s)''', (provider, identity_keys)).fetchone()
            expected = pending.get('expected_pid')
            if expected and row and row[0] != expected:
                raise EnrollmentError('That wearable belongs to a different participation. Sign out and try again.', 409)
            pid = row[0] if row else expected
            if not pid and not value.get('invite_hash'):
                raise EnrollmentError('No participation found. Please use your invitation link.', 403)
            invite_org = seats = None
            fitbit_link = value.get('fitbit_email_hash') is not None
            if fitbit_link:
                # Deletion is rolled back if any later check or enrollment write fails.
                link = self.db.execute('''delete from enrollment_private.fitbit_link_invites
                    where invite_hash=%s and expires_at>clock_timestamp()
                    returning org_id,participant_id,email_hash''',
                    (value['invite_hash'],)).fetchone()
                if not link:
                    raise EnrollmentError('This Fitbit link was used or expired. Ask for a new link.', 410)
                if (provider != 'google_health' or row or expected
                        or not hmac.compare_digest(pending.get('fitbit_email_hash', ''), link[2])):
                    raise EnrollmentError('This Fitbit account cannot use the link.', 403)
                invite_org, pid, _ = link
            elif value.get('invite_hash'):
                invite = self.db.execute('''select org_id,remaining from enrollment_private.invites
                    where invite_hash=%s and expires_at>now() for update''', (value['invite_hash'],)).fetchone()
                if not invite:
                    raise EnrollmentError('Your invitation expired. Ask for a new link.', 410)
                invite_org, seats = invite
            if not pid:
                for _ in range(100):
                    pid = 'p' + str(self.db.execute("select nextval('enrollment_private.participant_number')").fetchone()[0])
                    if self.db.execute('insert into audit.participants(participant_id) values(%s) on conflict do nothing returning participant_id', (pid,)).fetchone():
                        break
                else:
                    raise EnrollmentError('Participant allocation unavailable.', 503)
            # Serializes consent changes, provider additions and withdrawal for this person.
            self._lock_participant(pid)
            if fitbit_link:
                self._require_legacy_fitbit(pid)
            consent = self._consent(pid)
            if invite_org is not None and consent and consent['withdrawn'] and consent['recorded_epoch'] > pending['started']:
                raise EnrollmentError('Participation changed during connection. Please open a new invitation.', 409)
            if invite_org is not None and consent and consent['open'] and consent['org_id'] != invite_org:
                raise EnrollmentError('You already belong to another organization. Withdraw there before joining.', 409)
            if invite_org is not None:
                if not pending['choices'].get('accepted'):
                    raise EnrollmentError('Please confirm your participation choices.')
                if not consent or not consent['open']:
                    if seats is not None:
                        if seats <= 0:
                            raise EnrollmentError('This invitation is full. Ask for a new link.', 410)
                        self.db.execute('update enrollment_private.invites set remaining=remaining-1 where invite_hash=%s',
                                        (value['invite_hash'],))
                    membership = self.db.execute('''insert into org.memberships(participant_id,org_id,joined_on)
                        values(%s,%s,(now() at time zone 'Asia/Beirut')::date) returning membership_id''',
                        (pid, invite_org)).fetchone()[0]
                    consent = {'membership_id': membership, 'org_id': invite_org}
                self._append(pid, consent, pending['choices'])
                consent = self._consent(pid)
            if not consent:
                raise EnrollmentError('Participation is unavailable. Contact the Sentra team.', 403)
            if not row:
                stored_identity = FITBIT_LINK_IDENTITY_PREFIX + identity_hash if fitbit_link else identity_hash
                self.db.execute('''insert into enrollment_private.identities
                    (provider,identity_hash,participant_id) values(%s,%s,%s)''', (provider, stored_identity, pid))
            # Linking and later sign-ins prove the hosted identity, not the source of the legacy token.
            operator_managed = fitbit_link or (row is not None and row[1].startswith(FITBIT_LINK_IDENTITY_PREFIX))
            # A login to a withdrawn account can view that state, but cannot restart it.
            if not operator_managed and consent['open'] and not consent['withdrawn']:
                repo = TokenRepository(self.db)
                with repo.lock(pid, provider):
                    previous = repo.read(pid, provider, required=False)
                    body = login.envelope(provider, pid, token)
                    if previous:
                        # CAS without touching unrelated collection-state tables.
                        result = self.db.execute('''update collector_private.provider_credentials set encrypted_token_bundle=%s,
                            refresh_status='active',version=version+1,updated_at=now()
                            where participant_id=%s and provider=%s and version=%s''', (body, pid, provider, previous['version']))
                        if result.rowcount != 1:
                            raise EnrollmentError('Connection changed. Please reconnect.', 409)
                    else:
                        repo.insert(pid, provider, body, 'active')
            new_sid = secrets.token_urlsafe(32)
            self._save(new_sid, {'csrf': secrets.token_urlsafe(32), 'account': {'participant_id': pid, 'org_id': consent['org_id']}})
            self.db.execute('delete from enrollment_private.sessions where session_hash=%s', (digest(sid),))
            return new_sid

    def _consent(self, pid):
        row = self.db.execute('''select membership_id,org_id,sharing,demonstration,withdrawn,membership_open,extract(epoch from recorded_at)
            from org.current_consent where participant_id=%s''', (pid,)).fetchone()
        return dict(zip(('membership_id', 'org_id', 'sharing', 'demonstration', 'withdrawn', 'open', 'recorded_epoch'), row)) if row else None

    def _append(self, pid, consent, choices, withdrawn=False):
        self.db.execute('''insert into org.consents(membership_id,participant_id,org_id,consent_version,sharing,demonstration,withdrawn,recorded_at)
            values(%s,%s,%s,%s,%s,%s,%s,clock_timestamp())''', (consent['membership_id'], pid, consent['org_id'],
                self.settings.consent_version, choices['sharing'], choices['demonstration'], withdrawn))

    def status(self, sid):
        value = self.session(sid)
        public = {k: value[k] for k in ('csrf', 'organization') if k in value}
        public.update(joining=bool(value.get('invite_hash')), signed_in=bool(value.get('account')))
        if value.get('fitbit_email_hash'):
            public['linking_fitbit'] = True
        if not value.get('account'):
            return public
        pid = value['account']['participant_id']
        c = self._consent(pid)
        if not c or c['org_id'] != value['account']['org_id']:
            raise EnrollmentError('Your participation changed. Please sign in again.', 401)
        public.update(self._participation(pid, c))
        if self.operator_managed_fitbit(pid):
            public['fitbit_operator_managed'] = True
        return public

    def _participation(self, pid, c):
        org = self.db.execute('select display_name from org.organizations where org_id=%s', (c['org_id'],)).fetchone()[0]
        providers = {}
        rows = self.db.execute('select provider,refresh_status,encrypted_token_bundle from collector_private.provider_credentials where participant_id=%s', (pid,)).fetchall()
        for provider, status, body in rows:
            token = json.loads(self.settings.cipher.decrypt(bytes(body)))['token']
            providers[provider] = status if token.get('refresh_expires_at', float('inf')) > time.time() else 'expired'
        metadata = self.db.execute('select enrollment_private.participation_status(%s)', (pid,)).fetchone()[0]
        active = c['open'] and not c['withdrawn']
        try:
            day = date.fromisoformat(metadata['latest_measurement_day'])
            recent = 0 <= (datetime.now(ZoneInfo('Asia/Beirut')).date() - day).days <= 3
        except (TypeError, ValueError):
            recent = False
        return dict(participant_id=pid, organization=org, sharing=c['sharing'], demonstration=c['demonstration'],
            enrolled=active, connected=active and any(s == 'active' for s in providers.values()),
            recently_contributing=active and recent,
            providers={p: ('connected' if s == 'active' else 'reconnect_required') for p, s in providers.items()},
            # Assessment needs actual eligibility results, not a count of arbitrary readings.
            assessable=None, **metadata)

    def summary(self, org_id):
        """Private operator counts, never identities, readings or credentials."""
        people = self.db.execute('''select participant_id from org.current_consent
            where org_id=%s order by participant_id limit 101''', (org_id,)).fetchall()
        if len(people) > 100:
            raise EnrollmentError('Select a smaller organization for this bounded pilot summary.')
        counts = dict(enrolled=0, connected=0, recently_contributing=0,
                      assessable=0, assessment_unknown=0, withdrawn=0)
        for (pid,) in people:
            # Credential envelopes/status queries get their own conservative allowance.
            self.db.execute('select collector_private.reserve_egress(65536,3500000000)')
            consent = self._consent(pid)
            if not consent or consent['org_id'] != org_id:
                continue
            status = self._participation(pid, consent)
            for key in ('enrolled', 'connected', 'recently_contributing'):
                counts[key] += int(status[key])
            counts['withdrawn'] += int(consent['withdrawn'])
            if status['enrolled']:
                if status['assessable'] is None:
                    counts['assessment_unknown'] += 1
                else:
                    counts['assessable'] += int(status['assessable'])
        if counts['assessment_unknown']:
            counts['assessable'] = None  # Unknown is not a verified zero eligible people.
        return counts

    def change(self, sid, csrf, choices=None, *, withdraw=False):
        with self.db.transaction():
            value = self.session(sid, locked=True)
            self.check_csrf(value, csrf)
            if not value.get('account'):
                raise EnrollmentError('Please sign in first.', 401)
            pid = value['account']['participant_id']
            self._lock_participant(pid)
            c = self._consent(pid)
            if not c or c['org_id'] != value['account']['org_id']:
                raise EnrollmentError('Please sign in again.', 401)
            if not c['open'] or c['withdrawn']:
                if withdraw:
                    return  # Repeated withdrawal is safe.
                raise EnrollmentError('Use a new invitation to join again.', 409)
            if withdraw:
                choices = c
            self._append(pid, c, choices, withdrawn=withdraw)
            if withdraw:
                self.db.execute("update org.memberships set left_on=(now() at time zone 'Asia/Beirut')::date where membership_id=%s", (c['membership_id'],))
                providers = self.db.execute('select provider from collector_private.provider_credentials where participant_id=%s order by provider', (pid,)).fetchall()
                for (provider,) in providers:
                    with TokenRepository(self.db).lock(pid, provider):
                        self.db.execute("update collector_private.provider_credentials set refresh_status='withdrawn',version=version+1,updated_at=now() where participant_id=%s and provider=%s", (pid, provider))

    def logout(self, sid, csrf):
        with self.db.transaction():
            self.check_csrf(self.session(sid, locked=True), csrf)
            self.db.execute('delete from enrollment_private.sessions where session_hash=%s', (digest(sid),))
