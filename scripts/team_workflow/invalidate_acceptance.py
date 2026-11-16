"""Invalidate local evidence after task/PR edits without executing proposed code."""
import json
import os

from .github_client import GitHubClient
from .policy import declared_tasks


def invalidate(event, client):
    if "pull_request" in event:
        pulls = [client.pull(event["pull_request"]["number"])]
    else:
        issue = event["issue"]["number"]
        pulls = [p for p in client.list_pulls() if p["state"] == "open"
                 and issue in declared_tasks(p.get("body") or "", client.repo)]
    for pr in pulls:
        if pr["state"] == "open" and (pr["head"].get("repo") or {}).get("full_name") == client.repo:
            client._call(f"https://api.github.com/repos/{client.repo}/statuses/{pr['head']['sha']}",
                         client.token, {"state": "pending", "context": "local-acceptance",
                         "description": "Task or PR changed; awaiting current local acceptance"}, method="POST")


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
        event = json.load(handle)
    client = GitHubClient(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"], "")
    invalidate(event, client)


if __name__ == "__main__":
    main()
