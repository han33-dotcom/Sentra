"""Regression coverage for agent-authored acceptance evidence and protections."""
from copy import deepcopy
import unittest

from scripts.team_workflow.acceptance import (accepted_issue, body_digest, criteria,
    evidence_comment, validate_report)
from scripts.team_workflow.configure_delivery import REPO, protection_payload
from scripts.team_workflow.policy import approved_exemptions



def outcome(text="It works", status="passed"):
    return {"criterion": text, "status": status, "evidence": "Synthetic browser check observed the expected result.",
            "reason": "", "human_steps": "", "expected_result": "", "record_evidence": ""}


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


class ProtectionTests(unittest.TestCase):
    def test_remove_only_retired_acceptance_gate_and_keep_existing_checks(self):
        current = {"required_status_checks": {"checks": [
            {"context": "local-acceptance", "app_id": None},
            {"context": "custom", "app_id": 42}]},
            "enforce_admins": {"enabled": True}, "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False}}
        result = protection_payload(current)
        self.assertIsNone(result["required_pull_request_reviews"])
        self.assertTrue(result["required_status_checks"]["strict"])
        self.assertTrue(result["enforce_admins"])
        self.assertFalse(result["allow_force_pushes"])
        self.assertFalse(result["allow_deletions"])
        self.assertFalse(result["required_conversation_resolution"])
        checks = result["required_status_checks"]["checks"]
        self.assertNotIn("local-acceptance", [c["context"] for c in checks])
        self.assertIn({"context": "custom", "app_id": 42}, checks)
        self.assertEqual(len(checks), 5)
        self.assertEqual(protection_payload(current | {"required_status_checks": result["required_status_checks"]})
                         ["required_status_checks"], result["required_status_checks"])

    def test_sentra_author_exemption_does_not_change_techscout_policy(self):
        pr = {"user": {"login": "han33-dotcom"}, "labels": [{"name": "workflow-maintenance"}],
              "base": {"ref": "develop"}, "head": {"ref": "codex/work", "repo": {"full_name": REPO}}}
        timeline = [{"event": "labeled", "label": {"name": "workflow-maintenance"},
                     "actor": {"login": "han33-dotcom"}}]
        self.assertEqual(approved_exemptions(pr, ["AGENTS.md"], timeline, REPO),
                         ({"workflow-maintenance"}, []))
        self.assertTrue(approved_exemptions(pr, ["AGENTS.md"], timeline, "han33-dotcom/TechScout")[1])
