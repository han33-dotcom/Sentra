"""Preview or apply the owner-authorized Sentra branch protection migration."""
import argparse
import json
from pathlib import Path

from .local_worker import CHECKS, CONTEXT, REPO, Client, credential


def protection_payload(current):
    checks = list(current["required_status_checks"].get("checks", []))
    for name in sorted(CHECKS | {CONTEXT}):
        if not any(check["context"] == name for check in checks):
            checks.append({"context": name, "app_id": -1 if name == CONTEXT else 15368})
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
    parser.add_argument("--backup", type=Path, default=Path(".private/delivery-protections-before.json"))
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
