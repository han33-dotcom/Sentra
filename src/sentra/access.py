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
ORG_ID = re.compile(r'[a-z0-9][a-z0-9-]{1,39}')  # same rule as org.organizations
ROLES = ('officer', 'reviewer')
SHARING = ('group_only', 'individual')
DENIED = 'Access restricted to authorized team or organization accounts.'


@dataclass(frozen=True)
class Access:
    email: str
    role: str  # 'team', 'officer' or 'reviewer'
    org_id: str | None
    individuals: frozenset = frozenset()
    contributors: frozenset = frozenset()
    demonstrators: frozenset = frozenset()  # contributors who also agreed to internal demonstrations (#42)

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


def current(c):
    """A consent row in force: valid pseudonym and sharing level, not withdrawn, membership still open."""
    pid = c.get('participant_id')
    return (isinstance(pid, str) and PSEUDONYM.fullmatch(pid) is not None and c.get('withdrawn') is False
            and c.get('membership_open') is True and c.get('sharing') in SHARING)


def demonstration_ids(consents, org_id=None):
    """Participants whose consent in force allows internal demonstrations; `demonstration` must be exactly True.

    Used for the team's demonstration copy; organization users get the same set, limited to their
    organization, as `Access.demonstrators` from the same consent read as their decision."""
    return {c['participant_id'] for c in consents if current(c) and c.get('demonstration') is True
            and (org_id is None or c.get('org_id') == org_id)}


def resolve(email, *, team_emails, org_users=(), consents=()):
    """Decide what `email` (from verified sign-in) may see; raise SentraError when nothing is allowed."""
    if not isinstance(email, str) or not email.strip():
        raise SentraError(DENIED)
    email = email.strip().lower()
    if email in {e.strip().lower() for e in team_emails}:
        return Access(email, 'team', None)
    memberships = {(u.get('org_id'), u.get('role')) for u in org_users
                   if u.get('email') == email and u.get('active') is True and u.get('role') in ROLES}
    # Missing or malformed organization evidence is never an organization scope.
    if any(not isinstance(org, str) or not ORG_ID.fullmatch(org) for org, _ in memberships):
        raise SentraError(DENIED)
    # One organization per account; an ambiguous account must not link organizations.
    if len({org for org, _ in memberships}) != 1:
        raise SentraError(DENIED)
    org_id = next(iter(memberships))[0]
    role = 'officer' if any(r == 'officer' for _, r in memberships) else 'reviewer'
    individuals, contributors = set(), set()
    for c in consents:
        if c.get('org_id') != org_id or not current(c):
            continue
        contributors.add(c['participant_id'])
        if c.get('sharing') == 'individual':
            individuals.add(c['participant_id'])
    return Access(email, role, org_id, frozenset(individuals), frozenset(contributors),
                  frozenset(demonstration_ids(consents, org_id) & contributors))
