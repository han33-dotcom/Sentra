"""Synthetic organization access decisions; no participant data or credentials."""
import unittest

from sentra.access import K_ANONYMITY, publishable, resolve
from sentra.errors import SentraError

TEAM = ['Team@Example.test']
USERS = [
    {'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True},
    {'org_id': 'org-a', 'email': 'reviewer@a.test', 'role': 'reviewer', 'active': True},
    {'org_id': 'org-a', 'email': 'former@a.test', 'role': 'officer', 'active': False},
    {'org_id': 'org-b', 'email': 'officer@b.test', 'role': 'officer', 'active': True},
]


def consent(pid, org, sharing='group_only', withdrawn=False, open_=True):
    return {'participant_id': pid, 'org_id': org, 'sharing': sharing, 'withdrawn': withdrawn, 'membership_open': open_}


CONSENTS = [
    consent('p901', 'org-a', 'individual'),
    consent('p902', 'org-a'),
    consent('p903', 'org-a', 'individual', withdrawn=True),
    consent('p904', 'org-a', 'individual', open_=False),
    consent('p905', 'org-b', 'individual'),
]


def access(email):
    return resolve(email, team_emails=TEAM, org_users=USERS, consents=CONSENTS)


class AccessDecisionTests(unittest.TestCase):
    def test_team_operator_keeps_full_access(self):
        a = access(' team@example.TEST ')
        self.assertTrue(a.is_team)
        self.assertTrue(a.can_view_individual('p903'))
        self.assertEqual(len(a.visible([{'participant_id': 'p903'}, {'participant_id': 'p905'}])), 2)

    def test_officer_sees_only_individual_consent_in_own_organization(self):
        a = access('officer@a.test')
        self.assertEqual((a.role, a.org_id), ('officer', 'org-a'))
        self.assertEqual(a.individuals, {'p901'})
        rows = [{'participant_id': p} for p in ('p901', 'p902', 'p903', 'p904', 'p905', 'p999')]
        self.assertEqual([r['participant_id'] for r in a.visible(rows)], ['p901'])

    def test_group_only_counts_for_groups_but_is_not_shown_individually(self):
        a = access('reviewer@a.test')
        self.assertEqual(a.role, 'reviewer')
        self.assertFalse(a.can_view_individual('p902'))
        self.assertEqual(a.group_contributors(['p901', 'p902', 'p903', 'p904', 'p905']), {'p901', 'p902'})

    def test_withdrawn_or_closed_membership_is_excluded_everywhere(self):
        a = access('officer@a.test')
        for pid in ('p903', 'p904'):
            with self.subTest(pid=pid):
                self.assertFalse(a.can_view_individual(pid))
                self.assertNotIn(pid, a.group_contributors([pid]))

    def test_other_organization_is_never_visible(self):
        a = access('officer@a.test')
        self.assertFalse(a.can_view_individual('p905'))
        self.assertEqual(access('officer@b.test').individuals, {'p905'})

    def test_unknown_inactive_ambiguous_or_missing_identity_is_denied(self):
        both = USERS + [{'org_id': 'org-b', 'email': 'officer@a.test', 'role': 'officer', 'active': True}]
        cases = [lambda: access('stranger@x.test'), lambda: access('former@a.test'), lambda: access(''),
                 lambda: access(None), lambda: resolve('officer@a.test', team_emails=TEAM, org_users=both,
                                                       consents=CONSENTS)]
        for case in cases:
            with self.assertRaises(SentraError):
                case()

    def test_without_org_tables_only_team_operators_get_access(self):
        self.assertTrue(resolve('team@example.test', team_emails=TEAM).is_team)
        with self.assertRaises(SentraError):
            resolve('officer@a.test', team_emails=TEAM)

    def test_malformed_or_unknown_consent_values_grant_nothing(self):
        odd = [{'participant_id': 'p950', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': None,
                'membership_open': True},
               {'participant_id': 'p951', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': False,
                'membership_open': 'yes'},
               {'participant_id': 'Alice', 'org_id': 'org-a', 'sharing': 'individual', 'withdrawn': False,
                'membership_open': True},
               consent('p952', 'org-a', 'everyone')]
        a = resolve('officer@a.test', team_emails=TEAM, org_users=USERS, consents=odd)
        self.assertEqual(a.individuals, frozenset())
        self.assertEqual(a.contributors, {'p952'})

    def test_group_statistics_need_k_contributors(self):
        self.assertEqual(K_ANONYMITY, 5)
        self.assertFalse(publishable(4))
        self.assertTrue(publishable(5))
        for value in (None, True, 5.0, '5'):
            self.assertFalse(publishable(value))


if __name__ == '__main__':
    unittest.main()
