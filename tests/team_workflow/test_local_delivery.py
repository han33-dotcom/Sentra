"""Regression coverage for autonomous merge and completion boundaries."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts.team_workflow.acceptance import (accepted_issue, body_digest, criteria,
    evidence_comment, validate_report)
from scripts.team_workflow.configure_delivery import protection_payload
from scripts.team_workflow.local_worker import (CHECKS, LEASE, REPO, PR_CRITERIA, Worker,
    ci_state, eligible, snapshot, subscription_env)
from scripts.team_workflow.policy import approved_exemptions


def outcome(text="It works", status="passed"):
    return {"criterion": text, "status": status, "evidence": "Synthetic browser check observed the expected result.",
            "reason": "", "human_steps": "", "expected_result": "", "record_evidence": ""}


def pull():
    return {"number": 1, "state": "open", "draft": False, "title": "[SEN-86] Feature",
            "body": f"Task URL: https://github.com/{REPO}/issues/86\n", "labels": [],
            "user": {"login": "han33-dotcom"}, "base": {"ref": "develop", "sha": "base"},
            "head": {"ref": "codex/feature", "sha": "head", "repo": {"full_name": REPO}}}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.issue = {"number": 86, "body": "## Acceptance criteria\n- [ ] It works\n## Other\n- [ ] Ignore"}
        self.report = {"summary": "Verified", "criteria": [outcome()], "mode": "task", "issue": 86,
                       "issue_digest": body_digest(self.issue["body"]), "commit": "commit",
                       "merged_pulls": {"1": "merge"}}

    def test_acceptance_section_includes_checked_items_and_excludes_other_checklists(self):
        self.assertEqual(criteria(self.issue["body"].replace("[ ] It", "[x] It")), ["It works"])
        with self.assertRaises(ValueError):
            criteria("## Outcome\n- [ ] A checkbox outside acceptance")

    def test_missing_duplicate_and_changed_criteria_cannot_pass(self):
        for rows in [[], [outcome(), outcome()], [outcome("Different requirement")]]:
            with self.assertRaises(ValueError):
                validate_report({"criteria": rows}, ["It works"])

    def test_human_observations_require_actionable_instructions_and_never_complete_task(self):
        row = outcome(status="human_required")
        with self.assertRaises(ValueError):
            validate_report({"criteria": [row]}, ["It works"])
        row.update(reason="Separate phone unavailable", human_steps="Open the filter on the phone",
                   expected_result="Date selector is usable", record_evidence="Record device and observed result")
        self.assertFalse(validate_report({"criteria": [row]}, ["It works"]))

    def test_failure_and_empty_evidence_never_complete(self):
        self.assertFalse(validate_report({"criteria": [outcome(status="failed")]}, ["It works"]))
        row = outcome(); row["evidence"] = ""
        with self.assertRaises(ValueError):
            validate_report({"criteria": [row]}, ["It works"])

    def test_report_identity_content_and_implementation_snapshot_must_match(self):
        def accepted(report, actor="han33-dotcom"):
            return accepted_issue(self.issue, [{"user": {"login": actor}, "body": evidence_comment(report)}],
                                  {"1": "merge"}, {"han33-dotcom"})
        self.assertTrue(accepted(self.report))
        self.assertFalse(accepted(self.report, "outsider"))
        for key, value in [("issue", 85), ("mode", "pr"), ("issue_digest", "old"),
                           ("merged_pulls", {"1": "old"})]:
            report = dict(self.report, **{key: value})
            self.assertFalse(accepted(report))

    def test_latest_failed_report_supersedes_earlier_success(self):
        comments = [{"user": {"login": "han33-dotcom"}, "body": evidence_comment(self.report)}]
        report = deepcopy(self.report); report["criteria"][0]["status"] = "failed"
        comments.append({"user": {"login": "han33-dotcom"}, "body": evidence_comment(report)})
        self.assertFalse(accepted_issue(self.issue, comments, {"1": "merge"}, {"han33-dotcom"}))


class WorkerTests(unittest.TestCase):
    def test_subscription_environment_excludes_api_credentials_and_live_test_optins(self):
        values = {"OPENAI_API_KEY": "synthetic", "CODEX_API_KEY": "synthetic", "SENTRA_LIVE_TESTS": "1",
                  "SENTRA_TEST_CLOUD": "1", "PATH": "keep"}
        with patch.dict(os.environ, values, clear=True):
            env = subscription_env()
        self.assertEqual(env, {"PATH": "keep", "PYTHONUNBUFFERED": "1"})

    def test_drafts_forks_untrusted_authors_and_holds_are_not_worker_jobs(self):
        self.assertTrue(eligible(pull()))
        for changed in [{"draft": True}, {"labels": [{"name": "automation:hold"}]},
                        {"user": {"login": "outsider"}}, {"state": "closed"}]:
            self.assertFalse(eligible(dict(pull(), **changed)))
        pr = pull(); pr["head"]["repo"]["full_name"] = "outside/Sentra"
        self.assertFalse(eligible(pr))

    def test_any_head_base_issue_or_metadata_change_invalidates_snapshot(self):
        pr = pull(); issues = {86: {"body": "acceptance"}}
        original = snapshot(pr, issues)
        for part in ["head", "base"]:
            changed = deepcopy(pr); changed[part]["sha"] = "changed"
            self.assertNotEqual(snapshot(changed, issues), original)
        self.assertNotEqual(snapshot(dict(pr, body="changed"), issues), original)
        self.assertNotEqual(snapshot(pr, {86: {"body": "changed"}}), original)

    def test_ci_requires_all_checks_from_github_actions_and_success_not_skip(self):
        checks = [{"id": n, "name": name, "app": {"id": 15368}, "status": "completed",
                   "conclusion": "success"} for n, name in enumerate(sorted(CHECKS))]
        client = Mock(); client._rest.return_value = {"total_count": len(checks), "check_runs": checks}
        self.assertEqual(ci_state(client, "head"), "passed")
        checks[0]["conclusion"] = "skipped"
        self.assertEqual(ci_state(client, "head"), "failed")
        checks[0]["app"]["id"] = 99
        self.assertEqual(ci_state(client, "head"), "pending")

    def test_another_machine_lease_is_never_stolen(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Worker.__new__(Worker); worker.state_dir = Path(directory); worker.client = Mock()
            worker.client._rest.return_value = {"object": {"sha": "other-worker"}}
            with self.assertRaises(RuntimeError), worker.lease():
                self.fail("Lease must not be acquired")
            worker.client.write.assert_not_called()

    def test_saved_lease_recovers_after_restart_and_releases_once(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Worker.__new__(Worker); worker.state_dir = Path(directory); worker.client = Mock()
            (Path(directory) / "lease.json").write_text(json.dumps({"sha": "owned"}))
            worker.client._rest.return_value = {"object": {"sha": "owned"}}
            with worker.lease():
                pass
            worker.client.write.assert_called_once_with(f"/git/refs/heads/{LEASE}", method="DELETE")
            self.assertFalse((Path(directory) / "lease.json").exists())

    def test_changed_head_during_fix_never_pushes(self):
        worker = Worker.__new__(Worker); worker.client = Mock(); worker.git = Mock()
        worker.root = Path.cwd(); worker.env = {}
        changed = pull(); changed["head"]["sha"] = "new"
        worker.client.pull.return_value = changed
        with patch("scripts.team_workflow.local_worker.run"), self.assertRaises(RuntimeError):
            worker.push_fixes(pull())
        self.assertFalse(any(call.args[0] == "push" for call in worker.git.call_args_list))

    def delivery_worker(self):
        worker = Worker.__new__(Worker)
        worker.client = Mock()
        worker.client.write.return_value = {"merged": True}
        worker.client.issue.return_value = {"number": 86, "body": "## Acceptance criteria\n- [ ] It works"}
        worker.client.pull.return_value = pull()
        worker.prepare = Mock(); worker.publish = Mock(); worker.prompt = lambda text: text
        worker.git = Mock(side_effect=lambda *args: "head" if args == ("rev-parse", "HEAD") else "")
        worker.tests = Mock(return_value=[{"returncode": 0}])
        worker.agent = Mock(return_value={"summary": "Verified synthetic behavior",
                                          "criteria": [outcome(text) for text in PR_CRITERIA]})
        return worker

    def test_normal_pr_entry_point_merges_only_after_ci_and_current_acceptance(self):
        worker = self.delivery_worker()
        with patch("scripts.team_workflow.local_worker.ci_state", return_value="passed"):
            worker.process_pr(pull())
        worker.client.write.assert_called_once_with("/pulls/1/merge",
            {"sha": "head", "merge_method": "squash"}, method="PUT")
        self.assertEqual(worker.client.status.call_args.args[1], "success")

    def test_pending_ci_failed_acceptance_and_concurrent_head_never_merge(self):
        worker = self.delivery_worker()
        with patch("scripts.team_workflow.local_worker.ci_state", return_value="pending"):
            worker.process_pr(pull())
        worker.prepare.assert_not_called()
        worker.client.write.assert_not_called()
        worker = self.delivery_worker()
        worker.agent.return_value["criteria"][0]["status"] = "failed"
        with patch("scripts.team_workflow.local_worker.ci_state", return_value="passed"):
            worker.process_pr(pull())
        worker.client.write.assert_not_called()
        self.assertEqual(worker.client.status.call_args.args[1], "failure")
        worker = self.delivery_worker()
        changed = pull(); changed["head"]["sha"] = "new"
        worker.client.pull.return_value = changed
        with patch("scripts.team_workflow.local_worker.ci_state", return_value="passed"):
            worker.process_pr(pull())
        worker.client.write.assert_not_called()
        worker.publish.assert_not_called()

    def test_failed_release_opens_a_fix_pr_without_pushing_the_integration_branch(self):
        worker = self.delivery_worker()
        worker.create_fix_pr = Mock()
        pr = pull(); pr["base"]["ref"] = "main"; pr["head"]["ref"] = "develop"
        worker.tests.return_value = [{"returncode": 1, "output": "Synthetic failure"}]
        with patch("scripts.team_workflow.local_worker.ci_state", return_value="passed"):
            worker.process_pr(pr)
        worker.create_fix_pr.assert_called_once()
        worker.client.write.assert_not_called()
        self.assertFalse(any(call.args[0] == "push" for call in worker.git.call_args_list))

    def test_unsuccessful_merge_response_is_not_reported_as_complete(self):
        worker = self.delivery_worker()
        worker.client.write.return_value = {"merged": False}
        with patch("scripts.team_workflow.local_worker.ci_state", return_value="passed"), self.assertRaises(RuntimeError):
            worker.process_pr(pull())

    def test_protection_migration_keeps_ci_sources_and_protection_flags(self):
        current = {"required_status_checks": {"checks": [{"context": "custom", "app_id": 42}]},
                   "enforce_admins": {"enabled": True}, "allow_force_pushes": {"enabled": False},
                   "allow_deletions": {"enabled": False}}
        result = protection_payload(current)
        self.assertIsNone(result["required_pull_request_reviews"])
        self.assertFalse(result["required_conversation_resolution"])
        self.assertTrue(result["enforce_admins"])
        self.assertFalse(result["allow_force_pushes"])
        self.assertTrue(result["required_status_checks"]["strict"])
        self.assertIn({"context": "custom", "app_id": 42}, result["required_status_checks"]["checks"])

    def test_author_can_apply_sentra_exemption_while_techscout_keeps_existing_rule(self):
        pr = pull(); pr["labels"] = [{"name": "workflow-maintenance"}]
        timeline = [{"event": "labeled", "label": {"name": "workflow-maintenance"},
                     "actor": {"login": "han33-dotcom"}}]
        self.assertEqual(approved_exemptions(pr, ["AGENTS.md"], timeline, REPO), ({"workflow-maintenance"}, []))
        self.assertTrue(approved_exemptions(pr, ["AGENTS.md"], timeline, "han33-dotcom/TechScout")[1])
