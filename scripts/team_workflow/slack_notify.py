"""Task-first Slack cards with a durable, conservative delivery ledger.

Only trusted default-branch code runs with tokens. GitHub comments store delivery
state before the first Slack POST; uncertain sends are recovered, never reposted.
"""
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.request import Request, build_opener

from .check_pr import NoRedirect
from .identity import canonical_title
from .policy import APPROVERS, declared_tasks, verified_task

REPO = "han33-dotcom/Sentra"
WORKSPACE = "T0C8YHJMXAN"
CHANNEL = "C0C92DZ9TN0"
MARKER = "<!-- sentra-slack-card:v1 -->"
LEDGER_ACTOR = "github-actions[bot]"
EVENT_TYPE = "sentra_task_pr"
DEFINITE_REJECTIONS = {"invalid_auth", "account_inactive", "token_revoked", "missing_scope",
                       "not_in_channel", "channel_not_found", "is_archived", "invalid_blocks",
                       "msg_too_long", "no_text", "invalid_arguments"}


class SlackRejected(ValueError):
    """Slack explicitly rejected a request, as opposed to an uncertain send."""


class SlackClient:
    def __init__(self, token, transport=None):
        self.token = token
        self.transport = transport or self._network
        self.user_id = None

    def _network(self, method, payload):
        request = Request("https://slack.com/api/" + method,
                          data=json.dumps(payload).encode(),
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json; charset=utf-8"})
        # No automatic retry: a timed-out POST may have been accepted.
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)

    def call(self, method, payload):
        data = self.transport(method, payload)
        if (isinstance(data, dict) and data.get("ok") is False
                and data.get("error") in DEFINITE_REJECTIONS):
            raise SlackRejected("Slack rejected " + method + "; inspect app access and delivery state.")
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ValueError("Slack acknowledgement is uncertain; preserve the delivery claim.")
        return data

    def verify(self):
        data = self.call("auth.test", {})
        if data.get("team_id") != WORKSPACE or not data.get("bot_id") or not data.get("user_id"):
            raise ValueError("Slack token is not the expected workspace's bot token.")
        self.user_id = data["user_id"]
        # Verify channel membership/history before creating any delivery claim.
        self.call("conversations.history", {"channel": CHANNEL, "limit": 1})

    def recover(self, key, attempted_at):
        cursor, found = None, []
        for _ in range(30):
            payload = {"channel": CHANNEL, "limit": 100, "include_all_metadata": True,
                       "oldest": str(max(0, attempted_at - 120)), "inclusive": True}
            if cursor:
                payload["cursor"] = cursor
            data = self.call("conversations.history", payload)
            for message in data.get("messages", []):
                metadata = message.get("metadata") or {}
                if (message.get("user") == self.user_id and metadata.get("event_type") == EVENT_TYPE
                        and metadata.get("event_payload", {}).get("key") == key):
                    found.append(message["ts"])
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                if len(found) > 1:
                    raise ValueError("Multiple Slack cards found; manual reconciliation required.")
                return found[0] if found else None
        raise ValueError("Slack recovery history exceeds the pagination bound.")


def parse_time(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Provide an explicit UTC cutover timestamp ending in Z.")
    return datetime.fromisoformat(value[:-1] + "+00:00").timestamp()


def review_status(pull, reviews):
    if pull.get("merged_at"):
        return "Merged"
    if pull["state"] == "closed":
        return "Closed without merge"
    if pull.get("draft"):
        return "Draft"
    latest = {}
    for review in sorted(reviews, key=lambda r: r["id"]):
        actor = review.get("user") or {}
        if (actor.get("login") in APPROVERS[REPO] and actor.get("login") != pull["user"]["login"]
                and actor.get("type") == "User" and review["state"] in
                {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}):
            latest[actor["login"]] = review
    if any(r["state"] == "CHANGES_REQUESTED" for r in latest.values()):
        return "Changes requested"
    if any(r["state"] == "APPROVED" and r.get("commit_id") == pull["head"]["sha"]
           for r in latest.values()):
        return "Review approved"
    return "Review requested"


def card(pull, numbers, reviews):
    task_ids = ", ".join(f"SEN-{n}" for n in numbers)
    identity = task_ids or "Sentra maintenance"
    status = review_status(pull, reviews)
    title = pull["title"]
    if numbers:
        title = canonical_title(REPO, numbers, title).split("] ", 1)[1]
    description = html.escape(" ".join(title.split()), quote=False)
    key = f"{REPO}:{CHANNEL}:{pull['number']}"
    task_links = " · ".join(f"<https://github.com/{REPO}/issues/{n}|SEN-{n}>" for n in numbers)
    pr_link = f"<https://github.com/{REPO}/pull/{pull['number']}|PR #{pull['number']}>"
    heading = f"{identity} · {status}"
    details = f"Implementation: {pr_link} · Head {pull['head']['sha'][:7]}"
    reviewers = sorted(r["login"] for r in (pull.get("requested_reviewers") or []))
    if reviewers:
        details += " · Reviewers: " + html.escape(", ".join(reviewers), quote=False)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{heading}*\n{description}"}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": task_links or "No implementation task declared."}]},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": details}]}]
    payload = {"channel": CHANNEL, "text": f"{heading}\n{description}\n{details}",
               "blocks": blocks, "unfurl_links": False, "unfurl_media": False,
               "metadata": {"event_type": EVENT_TYPE, "event_payload": {"key": key}}}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload, fingerprint, key


def ledger_body(state):
    return MARKER + "\nAutomation delivery state for the task-first Slack card. Do not delete or edit.\n```json\n" + json.dumps(state, sort_keys=True) + "\n```"


def read_ledger(comments, number):
    matches = [c for c in comments if c.get("user", {}).get("login") == LEDGER_ACTOR
               and c.get("user", {}).get("type") == "Bot" and c.get("body", "").startswith(MARKER)]
    if len(matches) > 1:
        raise ValueError("Multiple delivery ledgers; manual reconciliation required.")
    if not matches:
        return None, None
    comment = matches[0]
    match = re.search(r"```json\n(.*?)\n```", comment["body"], re.S)
    state = json.loads(match[1]) if match else {}
    if (state.get("repo") != REPO or state.get("channel") != CHANNEL
            or state.get("pr") != number or state.get("phase") not in {"pending", "sent", "rejected"}
            or not isinstance(state.get("attempted_at"), (int, float))
            or not re.fullmatch(r"[0-9a-f]{64}", state.get("fingerprint", ""))
            or (state.get("phase") == "sent" and not re.fullmatch(r"[0-9]+\.[0-9]+", state.get("ts", "")))):
        raise ValueError("Invalid delivery ledger; preserve it for manual reconciliation.")
    return comment["id"], state


def notify(github, slack, mode="native", cutover=None, dry_run=True, now=None):
    if github.repo != REPO:
        raise ValueError("Unsupported notification repository.")
    if not dry_run and mode != "task-first":
        return []
    cutoff = parse_time(cutover) if cutover else None
    if not dry_run:
        if cutoff is None or cutoff > time.time():
            raise ValueError("Verified native-subscription cutover time is required before sending.")
        slack.verify()
    output = []
    for pull in github.list_pulls():
        try:
            result = _notify_pull(github, slack, pull, cutoff, dry_run, now)
        except Exception:
            # Preserve this PR's ledger and never retry a possibly accepted POST.
            # Do not expose raw exceptions, HTTP bodies or channel history.
            result = {"pr": pull["number"], "action": "error",
                      "errors": ["Card reconciliation failed; inspect this PR's metadata, delivery ledger and access."]}
        if result is not None:
            output.append(result)
    return output


def _notify_pull(github, slack, pull, cutoff, dry_run, now):
    if pull["user"]["login"] not in APPROVERS[REPO]:
        return None
    reviews = github.reviews(pull["number"]) if pull["state"] == "open" else []
    changed_at = max([parse_time(pull["updated_at"])] +
                     [parse_time(r["submitted_at"]) for r in reviews if r.get("submitted_at")])
    # Old native messages are not reposted in bulk during cutover.
    if cutoff is not None and changed_at < cutoff:
        return None
    if dry_run and cutoff is None and pull["state"] != "open":
        return None
    numbers = declared_tasks(pull.get("body") or "", REPO)
    for number in numbers:
        verified_task(github, REPO, number)
    payload, fingerprint, key = card(pull, numbers, reviews)
    if dry_run:
        return {"pr": pull["number"], "action": "preview", "payload": payload}
    comment_id, state = read_ledger(github.comments(pull["number"]), pull["number"])
    if state and state["phase"] == "pending":
        timestamp = slack.recover(key, state["attempted_at"])
        if timestamp is None:
            raise ValueError("Prior Slack delivery is uncertain; refusing to send another copy.")
        state.update(phase="sent", ts=timestamp)
        github.update_comment(comment_id, ledger_body(state))
    if state and state["phase"] == "sent":
        if state["fingerprint"] == fingerprint:
            return {"pr": pull["number"], "action": "unchanged"}
        # Updating the same Slack timestamp is safe to repeat after a crash.
        update = dict(payload, ts=state["ts"])
        update.pop("unfurl_links")
        update.pop("unfurl_media")
        slack.call("chat.update", update)
        state["fingerprint"] = fingerprint
        github.update_comment(comment_id, ledger_body(state))
        return {"pr": pull["number"], "action": "updated"}
    if state and state.get("attempts", 1) >= 3:
        raise ValueError("Slack delivery was repeatedly rejected; manual reconciliation required.")
    attempts = state.get("attempts", 0) if state else 0
    state = {"repo": REPO, "channel": CHANNEL, "pr": pull["number"], "phase": "pending",
             "fingerprint": fingerprint, "attempted_at": (now or time.time)(), "attempts": attempts + 1}
    if comment_id is None:
        # A timed-out claim creates no Slack POST. A replay finds the claim.
        comment_id = github.create_comment(pull["number"], ledger_body(state))["id"]
    else:
        github.update_comment(comment_id, ledger_body(state))
    try:
        result = slack.call("chat.postMessage", payload)
    except SlackRejected:
        state["phase"] = "rejected"  # An explicit ok:false did not create a message.
        github.update_comment(comment_id, ledger_body(state))
        raise
    # Missing/invalid timestamp is uncertain too: preserve the pending claim.
    if result.get("channel") != CHANNEL or not re.fullmatch(r"[0-9]+\.[0-9]+", result.get("ts", "")):
        raise ValueError("Slack delivery acknowledgement is incomplete; preserve the pending claim.")
    state.update(phase="sent", ts=result["ts"])
    github.update_comment(comment_id, ledger_body(state))
    return {"pr": pull["number"], "action": "created"}


def main():
    from .github_client import GitHubClient
    github = GitHubClient(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"], "")
    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"
    result = notify(github, SlackClient(os.environ.get("TEAM_SLACK_BOT_TOKEN", "")),
                    mode=os.environ.get("TEAM_SLACK_MODE", "native"),
                    cutover=os.environ.get("TEAM_SLACK_NATIVE_DISABLED_AT"), dry_run=dry_run)
    print(json.dumps(result, indent=2))
    return 1 if any(r.get("errors") for r in result) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never print tokens, HTTP bodies or channel history.
        print("Task-first Slack delivery failed; inspect access, cutover and delivery ledgers before retrying.")
        sys.exit(1)
