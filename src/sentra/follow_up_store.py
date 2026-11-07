"""The only write path for follow-ups (#31): a separate `sentra_followups` role that can execute two
database functions and nothing else (sql/010_follow_ups.sql). The viewer role stays read-only."""
import psycopg

from .errors import SentraError
from .shared_backend import connect_db

# Messages raised by the database functions themselves; anything else is reported generically.
EXPLAINED = {'42501', '22023'}


def follow_up_credentials(secrets, viewer_credentials):
    """Viewer connection details with the follow-up role's user and password; None when not configured."""
    try:
        section = dict(secrets['followups'])
    except Exception:
        return None
    if set(section) != {'user', 'password'} or str(section['user']).split('.')[0] != 'sentra_followups':
        raise SentraError('Follow-up writing is misconfigured. Ask the operator to check the followups secret.')
    db = dict(viewer_credentials['db'])
    db.update(user=section['user'], password=section['password'])
    return {'db': db}


class FollowUpWriter:
    def __init__(self, credentials, *, db=None):
        self.db = db if db is not None else connect_db(credentials)

    def close(self):
        self.db.close()

    def _call(self, sql, params):
        try:
            return self.db.execute(sql, params).fetchone()[0]
        except psycopg.Error as error:
            if error.sqlstate in EXPLAINED and error.diag.message_primary:
                raise SentraError(error.diag.message_primary) from None
            raise SentraError('Follow-up could not be saved; nothing was changed. Try again later.') from None

    def open(self, actor, org_id, participant_id, assignee, note):
        return self._call('select org.open_follow_up(%s,%s,%s,%s,%s)', (actor, org_id, participant_id, assignee, note))

    def update(self, actor, follow_up_id, status, assignee, note):
        self._call('select org.update_follow_up(%s,%s,%s,%s,%s)', (actor, follow_up_id, status, assignee, note))
