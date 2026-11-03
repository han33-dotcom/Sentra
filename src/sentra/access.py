"""Organization access decisions: which participants and group statistics a signed-in user may see.

Pure and deny-by-default. Inputs are rows already read from `org.org_users` and `org.current_consent`
(sql/007_organization_access.sql); nothing here queries a database or trusts request parameters.
Rules follow docs/participation-permissions.md:
- team operators on the existing viewer allowlist keep full operator access;
- an organization user sees only their own organization's participants;
- individual details need a current, non-withdrawn `individual` consent in an open membership episode;
- any current, non-withdrawn consent in an open episode counts towards group statistics, which are
  published only with at least `cohort_k_anonymity` contributors per statistic.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .errors import SentraError

THRESHOLDS = Path(__file__).resolve().parent / 'processing' / 'thresholds.json'
K_ANONYMITY = json.loads(THRESHOLDS.read_text(encoding='utf-8'))['cohort_k_anonymity']
PSEUDONYM = re.compile(r'p[0-9]{2,4}')
ROLES = ('officer', 'reviewer')
DENIED = 'Access restricted to authorized team or organization accounts.'


@dataclass(frozen=True)
class Access:
    email: str
    role: str  # 'team', 'officer' or 'reviewer'
    org_id: str | None
    individuals: frozenset = frozenset()
    contributors: frozenset = frozenset()

    @property
    def is_team(self):
        return self.role == 'team'

    def can_view_individual(self, participant_id):
        return self.is_team or participant_id in self.individuals

    def visible(self, rows, key='participant_id'):
        """Rows this user may see individually; other participants are dropped, never masked."""
        return [r for r in rows if self.can_view_individual(r.get(key))]

    def group_contributors(self, participant_ids):
        """Participants allowed to count towards a group statistic for this user."""
        ids = {p for p in participant_ids if isinstance(p, str) and PSEUDONYM.fullmatch(p)}
        return ids if self.is_team else ids & self.contributors


def publishable(contributor_count, k=K_ANONYMITY):
    """A group statistic may be shown only with at least k eligible contributors."""
    return isinstance(contributor_count, int) and not isinstance(contributor_count, bool) and contributor_count >= k


def resolve(email, *, team_emails, org_users=(), consents=()):
    """Decide what `email` (from verified sign-in) may see; raise SentraError when nothing is allowed."""
    if not isinstance(email, str) or not email.strip():
        raise SentraError(DENIED)
    email = email.strip().lower()
    if email in {e.strip().lower() for e in team_emails}:
        return Access(email, 'team', None)
    memberships = {(u.get('org_id'), u.get('role')) for u in org_users
                   if u.get('email') == email and u.get('active') is True and u.get('role') in ROLES}
    # One organization per account; an ambiguous account must not link organizations.
    if len({org for org, _ in memberships}) != 1:
        raise SentraError(DENIED)
    org_id = next(iter(memberships))[0]
    role = 'officer' if any(r == 'officer' for _, r in memberships) else 'reviewer'
    individuals, contributors = set(), set()
    for c in consents:
        pid = c.get('participant_id')
        if (c.get('org_id') != org_id or not isinstance(pid, str) or not PSEUDONYM.fullmatch(pid)
                or c.get('withdrawn') is not False or c.get('membership_open') is not True):
            continue
        contributors.add(pid)
        if c.get('sharing') == 'individual':
            individuals.add(pid)
    return Access(email, role, org_id, frozenset(individuals), frozenset(contributors))
