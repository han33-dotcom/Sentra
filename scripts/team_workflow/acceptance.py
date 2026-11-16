"""Acceptance evidence shared by the local worker and Project reconciliation."""
import hashlib
import json
import re

MARKER = "<!-- sentra-acceptance-v1 -->"


def body_digest(body):
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def criteria(body):
    """Keep the issue's actual acceptance checklist, including already checked items."""
    result = []
    level = None
    for line in (body or "").splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            if "acceptance" in heading[2].lower():
                level = len(heading[1])
            elif level and len(heading[1]) <= level:
                level = None
        match = re.match(r"^\s*[-*]\s+\[[ xX]\]\s+(.+)$", line)
        if level and match:
            result.append(match[1].strip())
    if not result:
        raise ValueError("Task needs an Acceptance criteria section with observable checkboxes.")
    return result


def report_schema():
    item = {"type": "object", "additionalProperties": False,
            "properties": {key: {"type": "string"} for key in
                           ["criterion", "evidence", "reason", "human_steps", "expected_result", "record_evidence"]}}
    item["properties"]["status"] = {"type": "string", "enum": ["passed", "failed", "human_required"]}
    item["required"] = list(item["properties"])
    return {"type": "object", "additionalProperties": False,
            "properties": {"summary": {"type": "string"},
                           "criteria": {"type": "array", "items": item}},
            "required": ["summary", "criteria"]}


def validate_report(report, expected):
    rows = report.get("criteria", [])
    if [row.get("criterion") for row in rows] != expected:
        raise ValueError("Acceptance report must cover every criterion exactly once in order.")
    for row in rows:
        status = row.get("status")
        if status not in {"passed", "failed", "human_required"}:
            raise ValueError("Unknown acceptance outcome.")
        if not row.get("evidence", "").strip():
            raise ValueError("Every outcome needs observed evidence or the attempted verification.")
        if status == "human_required" and not all(row.get(key, "").strip() for key in
                ["reason", "human_steps", "expected_result", "record_evidence"]):
            raise ValueError("Human verification needs reason, steps, expected result and evidence instructions.")
    return all(row["status"] == "passed" for row in rows)


def evidence_comment(report):
    lines = [MARKER, "## Automated acceptance", "", report["summary"], "",
             f"Tested commit `{report['commit']}`.", ""]
    for row in report["criteria"]:
        lines.extend([f"- **{row['status']}** — {row['criterion']}", f"  Evidence — {row['evidence']}"])
        if row["status"] == "human_required":
            for key in ["reason", "human_steps", "expected_result", "record_evidence"]:
                lines.append(f"  {key.replace('_', ' ').capitalize()} — {row[key]}")
    lines.extend(["", "<details><summary>Machine-readable evidence</summary>", "",
                  "```json", json.dumps(report, ensure_ascii=True, indent=2), "```", "</details>"])
    return "\n".join(lines)


def accepted_issue(issue, comments, merged_pulls, actors):
    """Trust only current, complete evidence published by configured team accounts."""
    expected = criteria(issue.get("body"))
    for comment in reversed(comments):
        if comment.get("user", {}).get("login") not in actors:
            continue
        body = comment.get("body") or ""
        if not body.startswith(MARKER):
            continue
        match = re.search(r"```json\n(.*?)\n```", body, re.S)
        try:
            report = json.loads(match[1]) if match else {}
            return (report.get("mode") == "task"
                    and report.get("issue") == issue["number"]
                    and report.get("issue_digest") == body_digest(issue.get("body"))
                    and report.get("merged_pulls") == merged_pulls
                    and bool(report.get("commit"))
                    and validate_report(report, expected))
        except (ValueError, KeyError, TypeError):
            return False
    return False
