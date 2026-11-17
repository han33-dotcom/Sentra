"""Preview or apply the owner-authorized Sentra branch protection migration."""
import argparse
import json
from pathlib import Path

import subprocess
from .github_client import GitHubClient

REPO = "han33-dotcom/Sentra"
CHECKS = {"guard", "test (ubuntu-24.04, py3.11)", "test (windows-2025, py3.11)", "pr-policy"}


def credential(root):
    result = subprocess.run(["git", "credential", "fill"], cwd=root,
                            input="protocol=https\nhost=github.com\n\n", text=True,
                            capture_output=True, check=True)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return fields["password"]


class Client(GitHubClient):
    def write(self, path, payload=None, method="POST"):
        return self.transport("https://api.github.com/repos/" + self.repo + path,
                              self.token, payload, method=method)


def protection_payload(current):
    checks = [check for check in current["required_status_checks"].get("checks", [])
              if check["context"] != "local-acceptance"]
    for name in sorted(CHECKS):
        if not any(check["context"] == name for check in checks):
            checks.append({"context": name, "app_id": 15368})
    restrictions = current.get("restrictions")
    if restrictions:
        restrictions = {"users": [u["login"] for u in restrictions.get("users", [])],
                        "teams": [t["slug"] for t in restrictions.get("teams", [])],
                        "apps": [a["slug"] for a in restrictions.get("apps", [])]}
    result = {"required_status_checks": {"strict": True, "checks": checks},
              "enforce_admins": current["enforce_admins"]["enabled"],
              "required_pull_request_reviews": None,
              "restrictions": restrictions, "required_conversation_resolution": False}
    for key in ["required_linear_history", "allow_force_pushes", "allow_deletions", "block_creations",
                "lock_branch", "allow_fork_syncing"]:
        result[key] = current.get(key, {}).get("enabled", False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path, default=Path(".private/agent-delivery-protections-before.json"))
    args = parser.parse_args()
    token = credential(Path.cwd())
    client = Client(REPO, token, token)
    current = {branch: client._rest(f"/branches/{branch}/protection") for branch in ["develop", "main"]}
    desired = {branch: protection_payload(value) for branch, value in current.items()}
    if args.apply:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        if not args.backup.exists():
            args.backup.write_text(json.dumps(current, indent=2))
        for branch, payload in desired.items():
            client.write(f"/branches/{branch}/protection", payload, method="PUT")
        client.write("", {"allow_auto_merge": True}, method="PATCH")
    print(json.dumps({"applied": args.apply, "protections": desired}, indent=2))


if __name__ == "__main__":
    main()
