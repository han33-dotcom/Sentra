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


def reconcile_identity(repo, client, dry_run=True):
    """Repair metadata prefixes; never send messages or change acceptance.

    Issue titles are the board card titles. PR titles flow through the existing
    GitHub Slack subscription. Events and daily reconciliation repair prefixes.
    """
    if repo != "han33-dotcom/Sentra":
        return []
    output = []
    for issue in client.list_issues():
        if "pull_request" in issue:
            continue
        number = issue["number"]
        verified_task(client, repo, number)
        title = canonical_title(repo, [number], issue["title"])
        changed = title != issue["title"]
        if changed and not dry_run:
            latest = verified_task(client, repo, number)
            if latest["title"] != issue["title"]:
                raise ValueError("Issue title changed during reconciliation; rerun.")
            client.set_issue_title(number, title)
        output.append({"kind": "issue", "number": number, "changed": changed, "dry_run": dry_run})
    for pull in client.list_pulls():
        if (pull["state"] != "open" or pull["user"]["login"] not in APPROVERS[repo]
                or pull["base"]["ref"] != PROJECTS[repo][2]):
            continue
        numbers = declared_tasks(pull.get("body") or "", repo)
        if not numbers:
            continue  # Approved exemptions have no task identity.
        for number in numbers:
            verified_task(client, repo, number)
        title = canonical_title(repo, numbers, pull["title"])
        changed = title != pull["title"]
        if changed and not dry_run:
            latest = client.pull(pull["number"])
            if any(latest.get(key) != pull.get(key) for key in ["title", "body", "state", "base", "head"]):
                raise ValueError("PR changed during title reconciliation; rerun.")
            client.set_pull_title(pull["number"], title)
        output.append({"kind": "pull", "number": pull["number"], "changed": changed, "dry_run": dry_run})
    return output


def main():
    from .github_client import GitHubClient
    repo = os.environ["GITHUB_REPOSITORY"]
    client = GitHubClient(repo, os.environ["GH_TOKEN"], "")
    result = reconcile_identity(repo, client, dry_run=os.environ.get("DRY_RUN", "true").lower() != "false")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("Task identity reconciliation failed; check metadata, permissions and API availability.")
        sys.exit(1)
