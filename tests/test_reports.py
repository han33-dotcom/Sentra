"""Selected-period reports (#42) with synthetic identities and board rows.

Every test passes the builder more than the user may see (the whole board, every participant selected)
and checks that the report, and its Markdown, still contains only what that user is permitted.
"""
from datetime import date, datetime, timedelta, timezone
import unittest

from sentra.access import resolve
from sentra.processing.pipeline import ASSESSMENT_VERSION
from sentra import reports

TEAM = ['team@example.test']
USERS = [{'org_id': 'org-a', 'email': 'officer@a.test', 'role': 'officer', 'active': True},
         {'org_id': 'org-b', 'email': 'officer@b.test', 'role': 'officer', 'active': True}]
END = date(2026, 11, 10)
TODAY = date(2026, 11, 11)


def consent(pid, org='org-a', sharing='group_only', withdrawn=False):
    return {'participant_id': pid, 'org_id': org, 'sharing': sharing, 'withdrawn': withdrawn, 'membership_open': True}


# org-a: p91 individual, p92-p96 group-only (six Fitbit contributors); p97 individual in org-b.
CONSENTS = ([consent('p91', sharing='individual')] + [consent(f'p9{i}') for i in range(2, 7)]
            + [consent('p97', 'org-b', 'individual')])


def days(pid, n=7, *, skip=(), rhr=True):
    rows = []
    for offset in reversed(range(n)):
        if offset in skip:
            continue
        i = int(pid[1:])
        row = {'d': (END - timedelta(days=offset)).isoformat(), 'sleep': 400 + i, 'steps': 5000 + i,
               'sleep_b': 410, 'hrv': 60, 'hrv_b': 58, 'lvl': 'green', 'f': []}
        if rhr:
            row.update(rhr=55, rhr_b=54)
        rows.append(row)
    return rows


def person(pid, device='Fitbit', **kw):
    return {'id': pid, 'name': pid, 'device': device, 'days': days(pid, **kw)}


# Only four org-a people (p91-p94) supply resting heart rate, so that statistic stays below k.
PEOPLE = ([person('p91', skip=(2, 3))] + [person(f'p9{i}', rhr=i < 5) for i in range(2, 7)]
          + [person('p97')])
BOARD = {'people': PEOPLE, 'data_through': END.isoformat(), 'built_at': '2026-11-11T01:30:00Z',
         'assessment_version': ASSESSMENT_VERSION}
CATALOG = [{'participant_id': p['id'], 'provider': 'google_health', 'dataset': 'daily_steps',
            'authorization_status': 'authorized' if p['id'] != 'p96' else 'revoked',
            'latest_civil_day': END.isoformat()} for p in PEOPLE]
FOLLOW_UPS = [{'follow_up_id': 1, 'org_id': 'org-a', 'participant_id': 'p91', 'status': 'open',
               'note': 'Synthetic individual note marker.'},
              {'follow_up_id': 2, 'org_id': 'org-a', 'participant_id': None, 'status': 'resolved',
               'note': 'Synthetic group note marker.'},
              {'follow_up_id': 3, 'org_id': 'org-a', 'participant_id': 'p92', 'status': 'ongoing',
               'note': 'Synthetic restricted note marker.'},
              {'follow_up_id': 4, 'org_id': 'org-b', 'participant_id': 'p97', 'status': 'ongoing',
               'note': 'Synthetic other organization note marker.'}]
EVERYONE = {p['id'] for p in PEOPLE}


def decide(email, consents=CONSENTS):
    return resolve(email, team_emails=TEAM, org_users=USERS, consents=consents)


def build(email, consents=CONSENTS, *, board=BOARD, days=7, include=EVERYONE, demonstration=None):
    decision = decide(email, consents)
    scope = EVERYONE if decision.is_team else set(decision.contributors)
    report = reports.build(decision, board=board, group_people=board['people'], scope=scope, enrolled=set(scope),
                           catalog=CATALOG, include=include, days=days, today=TODAY,
                           generated_at=datetime(2026, 11, 11, 9, tzinfo=timezone.utc).isoformat(),
                           follow_ups=FOLLOW_UPS, demonstration=demonstration)
    return report, reports.markdown(report)


def agreed(*pids):
    """CONSENTS with `demonstration` set for the given people only."""
    return [dict(c, demonstration=c['participant_id'] in pids) for c in CONSENTS]


class ReportBoundaryTests(unittest.TestCase):
    def test_officer_report_names_only_individually_shared_people_of_their_organization(self):
        report, text = build('officer@a.test')
        self.assertEqual([p['id'] for p in report['individuals']], ['p91'])
        self.assertIn('### p91', text)
        for pid in EVERYONE - {'p91'}:
            self.assertNotIn(pid, text)

    def test_only_selected_people_get_individual_sections(self):
        report, text = build('officer@a.test', include=set())
        self.assertEqual(report['individuals'], [])
        self.assertNotIn('p91', text)
        self.assertIn('No individual section', text)

    def test_other_organization_sees_none_of_org_a(self):
        report, text = build('officer@b.test')
        self.assertEqual([p['id'] for p in report['individuals']], ['p97'])
        for pid in EVERYONE - {'p97'}:
            self.assertNotIn(pid, text)
        # One contributor: nothing at group level, and counts below k are not revealed.
        self.assertEqual(report['group_summary'], [])
        self.assertEqual(report['group_trends'], [])
        self.assertEqual(report['participation']['connected'], '<5')

    def test_withdrawn_and_downgraded_people_leave_new_reports(self):
        for change in (consent('p91', sharing='individual', withdrawn=True), consent('p91')):
            with self.subTest(change=change):
                report, text = build('officer@a.test', [change] + CONSENTS[1:])
                self.assertEqual(report['individuals'], [])
                self.assertNotIn('p91', text)
                self.assertEqual(report['follow_ups'], {'open': 0, 'ongoing': 0, 'resolved': 1})

    def test_group_statistics_need_k_contributors_and_small_counts_stay_hidden(self):
        report, text = build('officer@a.test')
        summary = {(r['key'], r['device']): r for r in report['group_summary']}
        self.assertEqual(summary[('sleep', 'Fitbit')]['status'], 'available')
        self.assertEqual(summary[('sleep', 'Fitbit')]['contributors'], 6)
        self.assertEqual(summary[('rhr', 'Fitbit')]['status'], 'suppressed')
        self.assertIn('| Resting heart rate | Fitbit | Not shown | <5 |', text)  # four contributors, never '4'
        self.assertEqual(report['participation'], {'enrolled': '6', 'connected': '5', 'recently_contributing': '6',
                                                   'assessable': '6'})

    def test_organization_group_trends_omit_devices_and_counts_below_k(self):
        report, _ = build('officer@a.test')
        trends = {(r['key'], r['device']): r for r in report['group_trends']}
        self.assertIn(('sleep', 'Fitbit'), trends)
        self.assertNotIn('days_hidden', trends[('sleep', 'Fitbit')])
        for row in report['group_trends']:
            self.assertGreaterEqual(row['days_shown'], 1)
            self.assertGreaterEqual(row['most_contributors'], 5)

    def test_team_report_shows_exact_counts_and_hidden_days(self):
        report, text = build('team@example.test')
        self.assertEqual(report['organization'], reports.TEAM_LABEL)
        self.assertEqual(report['participation']['connected'], '6')
        self.assertTrue(all('days_hidden' in r for r in report['group_trends']))
        self.assertIn('Days hidden', text)
        self.assertEqual(sorted(p['id'] for p in report['individuals']), sorted(EVERYONE))

    def test_group_window_ends_on_the_latest_publishable_day_for_organizations(self):
        newer = dict(person('p92'), days=days('p92') + [{'d': (END + timedelta(days=1)).isoformat(), 'sleep': 300}])
        board = {**BOARD, 'people': [newer if p['id'] == 'p92' else p for p in PEOPLE]}
        report, text = build('officer@a.test', board=board)
        self.assertEqual(report['group_end'], END)  # one person's newer reading does not move the window
        self.assertIn(f'days through {END.isoformat()}', text)

    def test_organization_reports_do_not_reveal_other_organizations_latest_day(self):
        later = (END + timedelta(days=2)).isoformat()
        board = {**BOARD, 'data_through': later,
                 'people': [dict(p, days=p['days'] + [{'d': later, 'sleep': 300}]) if p['id'] == 'p97' else p
                            for p in PEOPLE]}
        _, text = build('officer@a.test', board=board)
        self.assertNotIn(later, text)
        _, team_text = build('team@example.test', board=board)
        self.assertIn(f'Published data through: {later}', team_text)


class DemonstrationCopyTests(unittest.TestCase):
    def test_only_people_who_agreed_appear_even_in_group_figures(self):
        rows = agreed('p92', 'p93', 'p94', 'p95', 'p96')  # five group-only people agreed; p91 did not
        decision = decide('officer@a.test', rows)
        report, text = build('officer@a.test', rows, demonstration=decision.demonstrators)
        self.assertTrue(report['demonstration'])
        self.assertIn('Demonstration copy', text)
        self.assertEqual(report['individuals'], [])  # p91 shares individually but did not agree
        self.assertNotIn('p91', text)
        sleep = next(r for r in report['group_summary'] if r['key'] == 'sleep')
        self.assertEqual(sleep['contributors'], 5)
        self.assertEqual(report['participation']['enrolled'], '5')
        self.assertEqual(report['follow_ups'], {'open': 0, 'ongoing': 0, 'resolved': 1})  # group follow-up only

    def test_fewer_than_k_who_agreed_shows_no_group_figure(self):
        rows = agreed('p91', 'p92')
        report, text = build('officer@a.test', rows, demonstration=decide('officer@a.test', rows).demonstrators)
        self.assertEqual([p['id'] for p in report['individuals']], ['p91'])
        self.assertEqual(report['group_summary'], [])
        self.assertEqual(report['group_trends'], [])
        self.assertEqual(report['participation']['connected'], '<5')
        self.assertNotIn('p92', text)

    def test_a_demonstration_set_cannot_widen_the_users_own_decision(self):
        rows = agreed('p91')
        report, text = build('officer@a.test', rows, demonstration=EVERYONE)  # caller passes too much
        self.assertEqual([p['id'] for p in report['individuals']], ['p91'])
        self.assertEqual(report['participation']['enrolled'], '1')
        for pid in EVERYONE - {'p91'}:
            self.assertNotIn(pid, text)

    def test_team_demonstration_copy_uses_the_agreed_consents(self):
        from sentra.access import demonstration_ids
        rows = agreed('p91', 'p97')
        report, text = build('team@example.test', rows, demonstration=demonstration_ids(rows))
        self.assertEqual(sorted(p['id'] for p in report['individuals']), ['p91', 'p97'])
        self.assertEqual(report['participation']['enrolled'], '2')
        for pid in EVERYONE - {'p91', 'p97'}:
            self.assertNotIn(pid, text)

    def test_normal_reports_are_not_marked(self):
        report, text = build('officer@a.test')
        self.assertFalse(report['demonstration'])
        self.assertNotIn('Demonstration copy', text)


class ReportContentTests(unittest.TestCase):
    def test_gaps_stay_gaps_in_individual_trends(self):
        report, text = build('officer@a.test')
        sleep = next(m for m in report['individuals'][0]['measures'] if m['key'] == 'sleep')
        self.assertEqual((sleep['days'], sleep['days_with_data']), (7, 5))
        self.assertIn('| Sleep | 5 of 7 |', text)

    def test_follow_ups_are_counts_only(self):
        report, text = build('officer@a.test')
        self.assertEqual(report['follow_ups'], {'open': 1, 'ongoing': 0, 'resolved': 1})
        self.assertNotIn('marker', text)
        team, team_text = build('team@example.test')
        self.assertEqual(team['follow_ups'], {'open': 1, 'ongoing': 2, 'resolved': 1})
        self.assertNotIn('marker', team_text)

    def test_limitations_and_wellness_wording(self):
        _, text = build('officer@a.test')
        for line in reports.LIMITATIONS:
            self.assertIn(line, text)
        self.assertIn('not a medical assessment or diagnosis', text)
        for word in ('disease', 'illness', 'sick', 'diagnosed'):
            self.assertNotIn(word, text.lower())

    def test_observations_explain_the_latest_day(self):
        report, text = build('officer@a.test')
        titles = [o['title'] for o in report['individuals'][0]['observations']]
        self.assertTrue(titles)
        self.assertIn(titles[0], text)

    def test_only_the_viewer_periods_are_accepted(self):
        with self.assertRaises(ValueError):
            build('officer@a.test', days=30)

    def test_table_cells_cannot_break_the_markdown(self):
        self.assertEqual(reports._cell('a|b\nc'), 'a\\|b c')


if __name__ == '__main__':
    unittest.main()
