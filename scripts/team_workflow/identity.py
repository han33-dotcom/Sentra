"""Keep Sentra's issue identity visible in board cards and native Slack titles."""
import re
import json
import os
import sys

from .policy import APPROVERS, PROJECTS, declared_tasks, task_title_prefix, verified_task


def canonical_title(repo, numbers, title):
    prefix = PROJECTS[repo][1]
    # Replace a previous generated prefix, preserving the human description.
    pattern = r"^\[(?:Task|" + re.escape(prefix) + r"-[0-9]+(?:,\s*" + re.escape(prefix) + r"-[0-9]+)*)\]\s*"
    description = re.sub(pattern, "", title, count=1).strip()
    if not description:
        raise ValueError("A task or PR title needs a description.")
    return task_title_prefix(repo, numbers) + " " + description


def _issue_identity(repo, client, issue, dry_run):
    if "pull_request" in issue:
        return None
    number = issue["number"]
    verified_task(client, repo, number)
    title = canonical_title(repo, [number], issue["title"])
    changed = title != issue["title"]
    if changed and not dry_run:
        latest = verified_task(client, repo, number)
        if latest["title"] != issue["title"]:
            raise ValueError("Issue title changed during reconciliation; rerun.")
        client.set_issue_title(number, title)
    return {"kind": "issue", "number": number, "changed": changed, "dry_run": dry_run}


def _pull_identity(repo, client, pull, dry_run):
    if (pull["state"] != "open" or pull["user"]["login"] not in APPROVERS[repo]
            or pull["base"]["ref"] != PROJECTS[repo][2]):
        return None
    numbers = declared_tasks(pull.get("body") or "", repo)
    if not numbers:
        return None  # Approved exemptions have no task identity.
    for number in numbers:
        verified_task(client, repo, number)
    title = canonical_title(repo, numbers, pull["title"])
    changed = title != pull["title"]
    if changed and not dry_run:
        latest = client.pull(pull["number"])
        if any(latest.get(key) != pull.get(key) for key in ["title", "body", "state", "base", "head"]):
            raise ValueError("PR changed during title reconciliation; rerun.")
        client.set_pull_title(pull["number"], title)
    return {"kind": "pull", "number": pull["number"], "changed": changed, "dry_run": dry_run}


def reconcile_identity(repo, client, dry_run=True):
    """Repair metadata prefixes; report per-item failures without stopping other items.

    Issue titles are the board card titles. PR titles flow through the existing
    GitHub Slack subscription. Events and daily reconciliation repair prefixes.
    """
    if repo != "han33-dotcom/Sentra":
        return []
    output = []
    for kind, items, repair in [("issue", client.list_issues, _issue_identity),
                                ("pull", client.list_pulls, _pull_identity)]:
        for item in items():
            try:
                result = repair(repo, client, item, dry_run)
            except Exception:
                # Raw exceptions may contain HTTP bodies, titles or credentials.
                result = {"kind": kind, "number": item["number"], "dry_run": dry_run,
                          "errors": ["Identity repair failed; check metadata, freshness and API access."]}
            if result is not None:
                output.append(result)
    return output


def main():
    from .github_client import GitHubClient
    repo = os.environ["GITHUB_REPOSITORY"]
    client = GitHubClient(repo, os.environ["GH_TOKEN"], "")
    result = reconcile_identity(repo, client, dry_run=os.environ.get("DRY_RUN", "true").lower() != "false")
    print(json.dumps(result, indent=2))
    return 1 if any(r.get("errors") for r in result) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("Task identity reconciliation failed; check metadata, permissions and API availability.")
        sys.exit(1)
