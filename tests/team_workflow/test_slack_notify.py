import copy
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts.team_workflow.slack_notify import (
    CHANNEL, EVENT_TYPE, LEDGER_ACTOR, REPO, WORKSPACE,
    SlackClient, card, ledger_body, notify, read_ledger, review_status,
)

CUTOVER = "2020-01-01T00:00:00Z"


class GitHub:
    repo = REPO

    def __init__(self):
        self.pulls = [{"number": 63, "state": "open", "draft": False, "merged_at": None,
                       "title": "[SEN-28, SEN-27] Refresh permissions",
                       "body": f"Task URL: https://github.com/{REPO}/issues/28\n"
                               f"Additional Task URL: https://github.com/{REPO}/issues/27\n",
                       "updated_at": "2026-11-04T00:00:00Z", "head": {"sha": "a" * 40},
                       "user": {"login": "han33-dotcom"}, "requested_reviewers": []}]
        self.thread = []
        self.reviews_list = []
        self.events = []
        self.fail_save = False

    def list_pulls(self):
        return copy.deepcopy(self.pulls)

    def issue(self, number):
        return {"number": number, "html_url": f"https://github.com/{REPO}/issues/{number}"}

    def reviews(self, number):
        return copy.deepcopy(self.reviews_list)

    def comments(self, number):
        return copy.deepcopy([c for c in self.thread if c["pr"] == number])

    def create_comment(self, number, body):
        self.events.append("claim")
        comment = {"id": len(self.thread) + 1, "pr": number, "body": body,
                   "user": {"login": LEDGER_ACTOR, "type": "Bot"}}
        self.thread.append(comment)
        return copy.deepcopy(comment)

    def update_comment(self, comment_id, body):
        self.events.append("save")
        if self.fail_save:
            self.fail_save = False
            raise TimeoutError("synthetic ledger save failure")
        next(c for c in self.thread if c["id"] == comment_id)["body"] = body


class Slack:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.messages = []
        self.post_error = None
        self.accept_then_timeout = False
        self.bad_ack = None
        self.workspace = WORKSPACE
        self.client = SlackClient("synthetic-token", self.transport)

    def transport(self, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))
        if method == "auth.test":
            return {"ok": True, "team_id": self.workspace, "user_id": "bot-user", "bot_id": "bot"}
        if method == "conversations.history":
            return {"ok": True, "messages": copy.deepcopy(self.messages)}
        if method == "chat.postMessage":
            self.events.append("post")
            if self.post_error:
                return self.post_error
            message = dict(payload, user="bot-user", ts=f"{len(self.messages)+1}.000001")
            self.messages.append(message)
            if self.accept_then_timeout:
                self.accept_then_timeout = False
                raise TimeoutError("synthetic uncertain Slack send")
            return self.bad_ack if self.bad_ack is not None else {"ok": True, "channel": CHANNEL, "ts": message["ts"]}
        if method == "chat.update":
            self.events.append("update")
            found = next(m for m in self.messages if m["ts"] == payload["ts"])
            found.update(payload)
            return {"ok": True, "channel": CHANNEL, "ts": payload["ts"]}
        raise AssertionError(method)

    def count(self, method):
        return sum(m == method for m, _ in self.calls)


def run(github, slack, **kwargs):
    return notify(github, slack.client, mode="task-first", cutover=CUTOVER,
                  dry_run=False, now=lambda: 100, **kwargs)


class SlackNotificationTests(unittest.TestCase):
    def test_failed_pr_does_not_block_another_card_or_repost_uncertain_delivery(self):
        for failure in ["pending", "invalid", "rejected", "post-timeout", "claim-timeout", "save-timeout", "recovery-window"]:
            with self.subTest(failure=failure):
                github = GitHub(); slack = Slack(github.events)
                github.pulls.append(dict(copy.deepcopy(github.pulls[0]), number=64))
                _, fingerprint, _ = card(github.pulls[0], [28, 27], [])
                if failure in {"pending", "invalid", "rejected", "recovery-window"}:
                    state = {"repo": REPO, "channel": CHANNEL, "pr": 63, "phase": "pending",
                             "fingerprint": fingerprint, "attempted_at": 100}
                    if failure == "invalid":
                        state["fingerprint"] = "invalid"
                    if failure == "rejected":
                        state.update(phase="rejected", attempts=3)
                    github.create_comment(63, ledger_body(state))
                if failure == "recovery-window":
                    def unavailable(*args):
                        raise ValueError("synthetic-private-history")
                    slack.client.recover = unavailable
                if failure == "post-timeout":
                    slack.accept_then_timeout = True
                if failure == "save-timeout":
                    github.fail_save = True
                if failure == "claim-timeout":
                    original = github.create_comment
                    def uncertain(number, body):
                        comment = original(number, body)
                        if number == 63:
                            raise TimeoutError("synthetic-private-claim")
                        return comment
                    github.create_comment = uncertain
                result = run(github, slack)
                self.assertEqual(result[0]["pr"], 63)
                self.assertTrue(result[0]["errors"])
                self.assertEqual(result[1], {"pr": 64, "action": "created"})
                self.assertNotIn("synthetic-private", json.dumps(result))
                second_state = read_ledger(github.comments(64), 64)[1]
                self.assertEqual(second_state["phase"], "sent")
                posts = slack.count("chat.postMessage")
                replay = run(github, slack)
                self.assertEqual(replay[1], {"pr": 64, "action": "unchanged"})
                self.assertEqual(slack.count("chat.postMessage"), posts)
                self.assertEqual(len(github.comments(63)), 1)
                self.assertEqual(len(github.comments(64)), 1)

    def test_cli_reports_failed_pr_safely_and_returns_nonzero_after_other_cards(self):
        from scripts.team_workflow.slack_notify import main
        github = GitHub(); slack = Slack(github.events)
        github.pulls.append(dict(copy.deepcopy(github.pulls[0]), number=64))
        original = github.comments
        def unavailable(number):
            if number == 63:
                raise RuntimeError("synthetic-private-payload")
            return original(number)
        github.comments = unavailable
        output = io.StringIO()
        with patch("scripts.team_workflow.github_client.GitHubClient", return_value=github), \
                patch("scripts.team_workflow.slack_notify.SlackClient", return_value=slack.client), \
                patch.dict(os.environ, GITHUB_REPOSITORY=REPO, GH_TOKEN="synthetic", DRY_RUN="false",
                           TEAM_SLACK_MODE="task-first", TEAM_SLACK_NATIVE_DISABLED_AT=CUTOVER), \
                redirect_stdout(output):
            self.assertEqual(main(), 1)
        result = json.loads(output.getvalue())
        self.assertTrue(result[0]["errors"])
        self.assertEqual(result[1], {"pr": 64, "action": "created"})
        self.assertNotIn("synthetic-private-payload", output.getvalue())

    def test_task_ids_lead_visible_blocks_and_notification_text_pr_link_is_secondary(self):
        github = GitHub()
        payload, fingerprint, key = card(github.pulls[0], [28, 27], [])
        self.assertTrue(payload["text"].startswith("SEN-28, SEN-27 · Review requested"))
        self.assertTrue(payload["blocks"][0]["text"]["text"].startswith("*SEN-28, SEN-27 · Review requested*"))
        self.assertIn("|PR #63>", payload["blocks"][2]["elements"][0]["text"])
        self.assertFalse(payload["unfurl_links"])
        self.assertFalse(payload["unfurl_media"])

    def test_title_cannot_inject_slack_mentions(self):
        pull = GitHub().pulls[0]
        pull["title"] = "[SEN-28] <!channel> <https://example.test|click> & title"
        payload, _, _ = card(pull, [28], [])
        self.assertNotIn("<!channel>", json.dumps(payload))
        self.assertNotIn("<https://example.test", json.dumps(payload))

    def test_native_mode_is_disabled_and_preview_needs_no_slack_access(self):
        github = GitHub(); slack = Slack(github.events)
        self.assertEqual(notify(github, slack.client, dry_run=False), [])
        preview = notify(github, slack.client)
        self.assertEqual(preview[0]["action"], "preview")
        self.assertEqual(slack.calls, [])
        self.assertEqual(github.events, [])

    def test_cutover_and_workspace_are_required_before_any_delivery_claim(self):
        for cutover in [None, "not-a-date", "2999-01-01T00:00:00Z"]:
            github = GitHub(); slack = Slack(github.events)
            with self.subTest(cutover=cutover), self.assertRaises(ValueError):
                notify(github, slack.client, mode="task-first", cutover=cutover, dry_run=False)
            self.assertEqual(github.events, [])
        github = GitHub(); slack = Slack(github.events); slack.workspace = "other"
        with self.assertRaises(ValueError):
            run(github, slack)
        self.assertEqual(github.events, [])

    def test_old_native_history_is_not_bulk_reposted_and_outside_authors_are_skipped(self):
        github = GitHub(); slack = Slack(github.events)
        github.pulls[0]["updated_at"] = "2019-01-01T00:00:00Z"
        self.assertEqual(run(github, slack), [])
        github.pulls[0]["updated_at"] = "2026-11-04T00:00:00Z"
        github.pulls[0]["user"]["login"] = "outside-contributor"
        self.assertEqual(run(github, slack), [])
        self.assertEqual(github.events, [])

    def test_claim_precedes_post_and_replays_create_only_one_card(self):
        github = GitHub(); slack = Slack(github.events)
        self.assertEqual(run(github, slack)[0]["action"], "created")
        self.assertEqual(github.events[:2], ["claim", "post"])
        for _ in range(3):
            self.assertEqual(run(github, slack)[0]["action"], "unchanged")
        self.assertEqual(slack.count("chat.postMessage"), 1)
        self.assertEqual(len(github.thread), 1)

    def test_new_review_of_old_pr_is_not_lost_at_cutover(self):
        github = GitHub(); slack = Slack(github.events)
        github.pulls[0]["updated_at"] = "2019-01-01T00:00:00Z"
        github.reviews_list = [{"id": 1, "state": "CHANGES_REQUESTED", "commit_id": "a" * 40,
                                "submitted_at": "2026-11-04T00:00:00Z",
                                "user": {"login": "MohamadNasrallah", "type": "User"}}]
        self.assertEqual(run(github, slack)[0]["action"], "created")
        self.assertIn("Changes requested", slack.messages[0]["text"])

    def test_review_merge_and_head_changes_update_the_existing_card(self):
        github = GitHub(); slack = Slack(github.events)
        run(github, slack)
        github.reviews_list = [{"id": 1, "state": "CHANGES_REQUESTED", "commit_id": "a" * 40,
                                "user": {"login": "MohamadNasrallah", "type": "User"}}]
        self.assertEqual(run(github, slack)[0]["action"], "updated")
        self.assertIn("Changes requested", slack.messages[0]["text"])
        github.pulls[0]["head"]["sha"] = "b" * 40
        run(github, slack)
        github.pulls[0].update(state="closed", merged_at="2026-11-04T01:00:00Z")
        run(github, slack)
        self.assertIn("Merged", slack.messages[0]["text"])
        self.assertEqual(slack.count("chat.postMessage"), 1)
        self.assertEqual(slack.count("chat.update"), 3)

    def test_crash_after_accepted_post_recovers_without_reposting(self):
        github = GitHub(); slack = Slack(github.events); slack.accept_then_timeout = True
        self.assertTrue(run(github, slack)[0]["errors"])
        self.assertEqual(read_ledger(github.thread, 63)[1]["phase"], "pending")
        self.assertEqual(run(github, slack)[0]["action"], "unchanged")
        self.assertEqual(slack.count("chat.postMessage"), 1)

    def test_crash_before_ledger_save_recovers_the_accepted_message(self):
        github = GitHub(); slack = Slack(github.events); github.fail_save = True
        self.assertTrue(run(github, slack)[0]["errors"])
        run(github, slack)
        self.assertEqual(slack.count("chat.postMessage"), 1)

    def test_claim_creation_timeout_never_reaches_slack_post(self):
        github = GitHub(); slack = Slack(github.events)
        original = github.create_comment
        def uncertain(number, body):
            original(number, body)
            raise TimeoutError("synthetic uncertain claim creation")
        github.create_comment = uncertain
        self.assertTrue(run(github, slack)[0]["errors"])
        self.assertTrue(run(github, slack)[0]["errors"])
        self.assertEqual(slack.count("chat.postMessage"), 0)
        self.assertEqual(len(github.thread), 1)

    def test_permission_rejections_are_bounded_and_ambiguous_errors_never_repost(self):
        github = GitHub(); slack = Slack(github.events)
        slack.post_error = {"ok": False, "error": "missing_scope"}
        for _ in range(3):
            self.assertTrue(run(github, slack)[0]["errors"])
        self.assertTrue(run(github, slack)[0]["errors"])
        self.assertEqual(slack.count("chat.postMessage"), 3)
        self.assertEqual(slack.messages, [])
        github = GitHub(); slack = Slack(github.events)
        slack.post_error = {"ok": False, "error": "internal_error"}
        self.assertTrue(run(github, slack)[0]["errors"])
        self.assertTrue(run(github, slack)[0]["errors"])
        self.assertEqual(slack.count("chat.postMessage"), 1)

    def test_uncertain_delivery_without_recoverable_message_never_posts_again(self):
        github = GitHub(); slack = Slack(github.events)
        payload, fingerprint, key = card(github.pulls[0], [28, 27], [])
        github.create_comment(63, ledger_body({"repo": REPO, "channel": CHANNEL, "pr": 63,
                                              "phase": "pending", "fingerprint": fingerprint, "attempted_at": 100}))
        for _ in range(2):
            self.assertTrue(run(github, slack)[0]["errors"])
        self.assertEqual(slack.count("chat.postMessage"), 0)

    def test_malformed_slack_response_is_uncertain_not_permission_to_post_again(self):
        for acknowledgement in [{}, {"unexpected": "response"}, {"ok": True},
                                {"ok": True, "ts": "1.000001", "channel": "other"}]:
            github = GitHub(); slack = Slack(github.events); slack.bad_ack = acknowledgement
            with self.subTest(acknowledgement=acknowledgement):
                self.assertTrue(run(github, slack)[0]["errors"])
            run(github, slack)
            self.assertEqual(slack.count("chat.postMessage"), 1)

    def test_human_forged_and_duplicate_bot_ledgers_are_not_used_as_sent_state(self):
        github = GitHub(); slack = Slack(github.events)
        run(github, slack)
        forged = copy.deepcopy(github.thread[0]); forged["user"] = {"login": "outside", "type": "User"}
        self.assertEqual(read_ledger([forged], 63), (None, None))
        with self.assertRaises(ValueError):
            read_ledger(github.thread * 2, 63)

    def test_history_pagination_bound_and_multiple_recovered_cards_fail_closed(self):
        slack = SlackClient("synthetic", lambda *args: {"ok": True, "messages": [], "response_metadata": {"next_cursor": "more"}})
        slack.user_id = "bot-user"
        with self.assertRaises(ValueError):
            slack.recover("key", 100)
        slack = SlackClient("synthetic", lambda *args: {"ok": True, "messages": [
            {"user": "bot-user", "ts": str(n), "metadata": {"event_type": EVENT_TYPE, "event_payload": {"key": "key"}}} for n in [1, 2]]})
        slack.user_id = "bot-user"
        with self.assertRaises(ValueError):
            slack.recover("key", 100)

    def test_stale_approval_author_and_bot_do_not_claim_current_review_approval(self):
        pull = GitHub().pulls[0]
        for login, kind, sha in [("MohamadNasrallah", "User", "old"),
                                  ("han33-dotcom", "User", "a" * 40),
                                  ("MohamadNasrallah", "Bot", "a" * 40)]:
            reviews = [{"id": 1, "state": "APPROVED", "commit_id": sha,
                        "user": {"login": login, "type": kind}}]
            self.assertEqual(review_status(pull, reviews), "Review requested")
