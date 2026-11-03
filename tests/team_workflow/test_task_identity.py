import copy
import unittest

from scripts.team_workflow.check_pr import check_pr_event
from scripts.team_workflow.identity import canonical_title, reconcile_identity
from scripts.team_workflow.policy import MAX_TASKS, declared_tasks, validate_pr_metadata
from scripts.team_workflow.sync_project import synchronize

try:
    from . import test_runner
except ImportError:
    import test_runner

REPO = "han33-dotcom/Sentra"
ROOT = f"https://github.com/{REPO}/issues/"
LINKS = f"Task URL: {ROOT}28\nAdditional Task URL: {ROOT}27\n"


class Client:
    def __init__(self):
        self.issues = {n: {"number": n, "node_id": str(n), "html_url": ROOT + str(n),
                          "state": "open", "title": "[Task] Example"} for n in [27, 28]}
        self.pulls = [{"number": 64, "state": "open", "draft": False, "merged_at": None,
                       "user": {"login": "han33-dotcom"}, "base": {"ref": "develop"},
                       "head": {"sha": "current"}, "body": LINKS, "title": "fix: retry joins"}]
        self.statuses = {27: "Not started", 28: "Not started"}
        self.writes = []
        self.review_state = "APPROVED"

    def list_issues(self):
        return copy.deepcopy(list(self.issues.values()))

    def list_pulls(self):
        return copy.deepcopy(self.pulls)

    def issue(self, number):
        return copy.deepcopy(self.issues[number])

    def pull(self, number):
        return copy.deepcopy(next(p for p in self.pulls if p["number"] == number))

    def set_issue_title(self, number, title):
        self.writes.append(("issue", number))
        self.issues[number]["title"] = title

    def set_pull_title(self, number, title):
        self.writes.append(("pull", number))
        next(p for p in self.pulls if p["number"] == number)["title"] = title

    def project(self, project_id):
        return {"owner": "han33-dotcom", "repositories": [REPO], "status_field": "status",
                "options": {s: s for s in ["Not started", "In progress", "In review",
                                           "Changes requested", "Implemented", "Blocked", "Done"]}}

    def item(self, issue_id, project_id):
        return {"id": issue_id, "status": self.statuses[int(issue_id)]}

    def set_status(self, project_id, item_id, field, option):
        self.writes.append(("status", int(item_id), option))
        self.statuses[int(item_id)] = option

    def reviews(self, number):
        return [{"id": 1, "state": self.review_state,
                 "user": {"login": "MohamadNasrallah", "type": "User"}}]


class DeclarationTests(unittest.TestCase):
    def test_primary_and_secondary_order_is_shared_with_title_policy(self):
        event, pr, files, fetch = test_runner.RunnerTests().snapshot()
        body = pr["body"].replace(f"Task URL: {ROOT}16\n", LINKS)
        self.assertEqual(declared_tasks(body, REPO), [28, 27])
        self.assertEqual(validate_pr_metadata(body, set(), REPO, "develop", "[SEN-28, SEN-27] fix: retry joins"), [])
        for title in ["fix: retry joins", "[SEN-64] fix: retry joins", "[SEN-28] fix: retry joins",
                      "[SEN-27, SEN-28] fix: retry joins", "[SEN-28, SEN-27] "]:
            with self.subTest(title=title):
                self.assertTrue(validate_pr_metadata(body, set(), REPO, "develop", title))

    def test_single_task_legacy_metadata_and_other_repo_are_supported(self):
        self.assertEqual(declared_tasks(f"Task URL: {ROOT}28", REPO), [28])
        self.assertEqual(declared_tasks("Task URL: https://github.com/han33-dotcom/TechScout/issues/6", "han33-dotcom/TechScout"), [6])

    def test_references_comments_and_examples_never_become_implementation_links(self):
        body = LINKS + f"Related to #49; depends on {ROOT}45.\n<!--\nAdditional Task URL: {ROOT}49\n-->\n```text\nAdditional Task URL: {ROOT}45\n```"
        self.assertEqual(declared_tasks(body, REPO), [28, 27])

    def test_bad_secondary_duplicate_missing_primary_and_excessive_links_fail(self):
        for links in [f"Task URL: {ROOT}28\nTask URL: {ROOT}27",
                      f"Task URL: {ROOT}28\nAdditional Task URL: {ROOT}28",
                      f"Additional Task URL: {ROOT}27",
                      f"Task URL: {ROOT}28\nAdditional Task URL:",
                      f"Task URL:\nAdditional Task URL: {ROOT}27",
                      f"Task URL: {ROOT}28\nAdditional Task URL: https://github.com/other/Sentra/issues/27",
                      "Task URL: " + ROOT + "1\n" + "\n".join(f"Additional Task URL: {ROOT}{n}" for n in range(2, MAX_TASKS + 2))]:
            with self.subTest(links=links):
                with self.assertRaises(ValueError):
                    declared_tasks(links, REPO)

    def test_checker_verifies_secondary_issue_endpoint_and_title(self):
        event, pr, files, fetch = test_runner.RunnerTests().snapshot()
        pr["body"] = pr["body"].replace(f"Task URL: {ROOT}16\n", f"Task URL: {ROOT}16\nAdditional Task URL: {ROOT}27\n")
        pr["title"] = "[SEN-16, SEN-27] Fix the filter"
        def wrapped(path):
            if path == "/issues/27":
                return {"number": 27, "pull_request": {"url": "synthetic"}}
            return fetch(path)
        self.assertIn("Task URL must reference an issue, not a pull request.", check_pr_event(event, REPO, wrapped))

    def test_title_changes_during_validation_fail(self):
        event, pr, files, fetch = test_runner.RunnerTests().snapshot()
        reads = 0
        def wrapped(path):
            nonlocal reads
            result = copy.deepcopy(fetch(path))
            if path == "/pulls/15":
                reads += 1
                if reads == 2:
                    result["title"] = "Wrong title"
            return result
        self.assertIn("PR changed during validation; use a fresh event.", check_pr_event(event, REPO, wrapped))


class IdentityTests(unittest.TestCase):
    def test_preview_writes_nothing_then_repair_is_idempotent(self):
        client = Client()
        preview = reconcile_identity(REPO, client)
        self.assertEqual(len(preview), 3)
        self.assertTrue(all(item["changed"] for item in preview))
        self.assertEqual(client.writes, [])
        reconcile_identity(REPO, client, dry_run=False)
        self.assertEqual(client.issues[28]["title"], "[SEN-28] Example")
        self.assertEqual(client.pulls[0]["title"], "[SEN-28, SEN-27] fix: retry joins")
        writes = client.writes[:]
        reconcile_identity(REPO, client, dry_run=False)
        self.assertEqual(client.writes, writes)
        self.assertTrue(all(i["state"] == "open" for i in client.issues.values()))

    def test_wrong_prefix_is_replaced_and_description_preserved(self):
        for title in ["[Task] Human description", "[SEN-99] Human description", "Human description"]:
            self.assertEqual(canonical_title(REPO, [28], title), "[SEN-28] Human description")

    def test_live_issue_edit_is_not_overwritten(self):
        client = Client()
        original = client.issue
        reads = 0
        def changed(number):
            nonlocal reads
            reads += 1
            issue = original(number)
            if reads == 2:
                issue["title"] = "Edited by teammate"
            return issue
        client.issue = changed
        with self.assertRaises(ValueError):
            reconcile_identity(REPO, client, dry_run=False)
        self.assertEqual(client.writes, [])

    def test_live_pr_scope_edit_is_not_overwritten(self):
        client = Client()
        for n, issue in client.issues.items():
            issue["title"] = f"[SEN-{n}] Example"
        original = client.pull
        def changed(number):
            pull = original(number)
            pull["body"] += f"Additional Task URL: {ROOT}49\n"
            return pull
        client.pull = changed
        with self.assertRaises(ValueError):
            reconcile_identity(REPO, client, dry_run=False)
        self.assertEqual(client.writes, [])

    def test_other_repo_and_unconfigured_pr_author_are_not_renamed(self):
        client = Client()
        self.assertEqual(reconcile_identity("han33-dotcom/TechScout", client, dry_run=False), [])
        client.pulls[0]["user"]["login"] = "outside-contributor"
        reconcile_identity(REPO, client, dry_run=False)
        self.assertFalse(any(w[0] == "pull" for w in client.writes))


class MultiTaskSyncTests(unittest.TestCase):
    def test_shared_pr_updates_both_tasks_and_secondary_waits_for_other_pr(self):
        client = Client()
        synchronize(REPO, "project", client, dry_run=False)
        self.assertEqual(client.statuses, {27: "In review", 28: "In review"})
        client.pulls[0].update(state="closed", merged_at="2026-11-04")
        client.pulls.append(dict(client.pulls[0], number=70, state="open", merged_at=None,
                                 body=f"Task URL: {ROOT}27\n"))
        synchronize(REPO, "project", client, dry_run=False)
        self.assertEqual(client.statuses, {27: "In review", 28: "Implemented"})
        client.pulls[1].update(state="closed", merged_at="2026-11-04")
        synchronize(REPO, "project", client, dry_run=False)
        self.assertEqual(client.statuses, {27: "Implemented", 28: "Implemented"})

    def test_preview_and_manual_acceptance_states_are_preserved_for_every_task(self):
        for status in ["Done", "Blocked"]:
            client = Client()
            client.statuses = {27: status, 28: status}
            synchronize(REPO, "project", client, dry_run=False)
            self.assertEqual(client.writes, [])
        client = Client()
        synchronize(REPO, "project", client)
        self.assertEqual(client.writes, [])
        client.issues[27]["state"] = "closed"
        synchronize(REPO, "project", client, dry_run=False)
        self.assertEqual(client.statuses[27], "Not started")

    def test_invalid_secondary_issue_or_url_prevents_all_status_writes(self):
        for invalid in ["pr", "identity", "foreign", "duplicate"]:
            client = Client()
            if invalid == "pr":
                client.issues[27]["pull_request"] = {}
            elif invalid == "identity":
                client.issues[27]["html_url"] = ROOT + "99"
            elif invalid == "foreign":
                client.pulls[0]["body"] = LINKS.replace(ROOT + "27", "https://github.com/other/Sentra/issues/27")
            else:
                client.pulls[0]["body"] += f"Additional Task URL: {ROOT}28\n"
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                synchronize(REPO, "project", client, dry_run=False)
            self.assertEqual(client.writes, [])

    def test_review_and_draft_states_apply_to_both_tasks(self):
        for draft, review, expected in [(True, "APPROVED", "In progress"),
                                         (False, "CHANGES_REQUESTED", "Changes requested")]:
            client = Client()
            client.pulls[0]["draft"] = draft
            client.review_state = review
            synchronize(REPO, "project", client, dry_run=False)
            self.assertEqual(client.statuses, {27: expected, 28: expected})

    def test_removed_secondary_link_during_recheck_is_not_written(self):
        client = Client()
        original = client.list_pulls
        reads = 0
        def changed():
            nonlocal reads
            reads += 1
            pulls = original()
            if reads >= 2:
                pulls[0]["body"] = f"Task URL: {ROOT}28\n"
            return pulls
        client.list_pulls = changed
        synchronize(REPO, "project", client, dry_run=False)
        self.assertEqual(client.statuses, {27: "Not started", 28: "In review"})
