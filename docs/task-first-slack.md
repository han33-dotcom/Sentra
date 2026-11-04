# Task-first Slack notifications

Task: [SEN-66](https://github.com/han33-dotcom/Sentra/issues/66). Owner:
`han33-dotcom`; another configured teammate reviews the implementation and verifies
acceptance. This replaces the native Sentra PR/review messages only after the
reviewed implementation is released to `main` and the cutover below is verified.
Until then, native notifications stay on and custom delivery stays off.

## Message and delivery contract

The notification text and first visible block lead with the task identity:

```text
SEN-28, SEN-27 · Review requested
Refresh participation permissions

SEN-28 · SEN-27                   (links to the tasks)
Implementation: PR #63 · Head abc1234
```

The PR number is a secondary link. Every declared implementation task is included;
dependencies and incidental references do not become task labels. A scoped
maintenance/release PR without a task says `Sentra maintenance`, rather than
inventing an ID. Links do not unfurl into a second PR-first GitHub card.

There is one custom card per PR. Draft, review-requested, current-head approval,
changes-requested, merged and closed-unmerged states update that card. Title,
reviewer-request and head changes also update it. Updates edit the existing card;
they do not create a new channel post or promise a fresh push alert. Detailed
reviews stay on GitHub. A merged PR does not imply human task acceptance.

The default-branch `Team project sync` workflow owns the sole delivery writer,
under its existing repository-wide concurrency group. It never checks out or
executes PR code with tokens. The notification job uses a repository token with
contents/read, pull-requests/read and issues/write (delivery-state comments only).
It receives no collection or Project secret and adds no schedule.

Before the initial Slack send, one bot-authored GitHub PR comment records a
pending delivery claim. After success it stores Slack's message timestamp and a
payload fingerprint. Replays leave an unchanged card alone; changes use
`chat.update` at that timestamp. The ledger is durable GitHub metadata, independent
of Actions caches, artifacts, workstations or Slack retention.

No Slack POST or GitHub claim POST is automatically retried after an uncertain
response. A pending delivery is recovered from the same bot's Slack metadata. If
the card cannot be found conclusively, the worker fails and sends no second copy.
Only explicit permission/validation rejections can be attempted again, at most
three times. Ambiguous service errors remain pending. A crash while updating an
existing card can safely repeat the update. Multiple ledgers/cards and incomplete
API pagination fail closed.

## App setup

Use the reviewed [Slack app manifest](../.github/slack-app-manifest.json) for
**Sentra Task Updates** in **nsquared** (`T0C8YHJMXAN`). Its bot scopes are:

- `chat:write`: post and update its own task cards.
- `channels:history`: recover uncertain deliveries from public channels the bot
  has joined. Add the bot only to `#fyp-sentra` (`C0C92DZ9TN0`). Do not join other
  channels or grant private-channel/history, user-token or administrator scopes.

Store the installed bot token only as repository Actions secret
`TEAM_SLACK_BOT_TOKEN`, through masked secure credential entry. Never paste it into
chat, an issue, a PR, a command argument, logs or a committed file. The connected
Slack plugin can read/send on behalf of its account; it does not provide this
runtime credential to GitHub Actions. App creation/installation and new persistent
access require the owner's explicit action-time authorization.

The worker verifies the bot's workspace and access to the fixed target channel
before creating delivery claims. It cannot send to a channel supplied by PR text.

## Cutover without parallel notifications

Do all preparation while `TEAM_SLACK_MODE` is absent or `native`:

1. Independently review and merge the implementation into `develop`, then release
   to `main` through the normal reviewed process. Do not bypass branch protection.
2. Install the approved app, add it only to `#fyp-sentra`, and securely configure
   `TEAM_SLACK_BOT_TOKEN`. Keep custom delivery off.
3. Run `Team project sync` manually with `dry_run=true`. The notification preview
   renders current open PRs without calling Slack or writing delivery state.
   Verify task-first labels, all declared task IDs, the secondary PR link and
   suppressed unfurls. Dry runs do not prove live credentials or delivery.
4. In `#fyp-sentra`, run `/github subscribe list features` and record the actual subscription.
   Remove only Sentra's `pulls` and `reviews` events:

   ```text
   /github unsubscribe han33-dotcom/Sentra pulls reviews
   /github subscribe list features
   ```

   Verify the bot's confirmation and the resulting list before proceeding. Also
   verify Sentra's `comments` subscription is off: delivery-ledger comments must
   not themselves create native Slack messages. If it was on, include it in the
   recorded cutover and restore it only on rollback. Do not
   remove another repository's subscription or unrelated event types. This change
   is authorized by the task, but must not occur before the replacement is ready.
5. Record the verified disable time as UTC `YYYY-MM-DDTHH:MM:SSZ` in Actions
   variable `TEAM_SLACK_NATIVE_DISABLED_AT`. Then set `TEAM_SLACK_MODE=task-first`.
   `TEAM_SYNC_ENABLED` must already be true. The worker refuses live sends without
   an explicit nonfuture cutoff. It skips PRs last updated before that cutoff, so
   old native history is not reposted in bulk. Review and merge events after the
   cutoff are rendered from current GitHub metadata, rather than stale event text.
6. Exercise one agreed synthetic PR event. Inspect its single task-first card and
   its bot-authored delivery ledger. Verify no parallel native event. Repeat the
   reconciliation: no new message, no ledger write. Exercise review/merge updates
   against the same Slack timestamp and confirm task acceptance remains human-owned.
7. Record actual subscription evidence, cutoff, workflow run, Slack permalink and
   replay results on SEN-66. A teammate verifies acceptance before Done/closure.

Native subscriptions are managed by GitHub's Slack app; the worker cannot query
their configuration through Slack Web API. `TEAM_SLACK_MODE` and the verified
cutover record are operational guards, not an assertion that the native app is
incapable of being re-enabled. Do not re-enable native PR/review subscriptions while
custom delivery is active.

## Recovery and rollback

For rollback, set `TEAM_SLACK_MODE=native` **first** and let the current serialized
delivery run finish. Then restore exactly the previously recorded native events:

```text
/github subscribe han33-dotcom/Sentra pulls reviews
/github subscribe list features
```

Keep the custom cards and delivery ledgers; do not delete or recreate history.
No old messages are rewritten during either direction of cutover.

A pending ledger without a recovered card needs human triage: inspect the relevant
Actions error, the bot's target-channel history and the original delivery attempt.
Do not erase the claim and blindly replay. A deleted/retained-out card with a sent
ledger is not automatically recreated; authorize and record any replacement
explicitly after verifying it cannot duplicate an existing card. GitHub and Slack
do not offer a cross-service atomic transaction, so uncertainty deliberately stops
delivery instead of claiming exactly-once success or risking another post.

## Validation

```text
python -m unittest tests.team_workflow.test_slack_notify -v
python -m pytest -ra
python scripts/check_no_data.py
node --test tests/test_board_chart.cjs tests/test_enrollment_browser.cjs
```

Fixtures are synthetic. Ordinary tests never contact Slack or enable collection.
Live activation/replay evidence remains separate from local and CI results.

Primary API references: [GitHub subscription controls](https://docs.github.com/en/integrations/how-tos/slack/customize-notifications),
[Slack posting](https://docs.slack.dev/reference/methods/chat.postMessage/),
[Slack updating](https://docs.slack.dev/reference/methods/chat.update/),
[Slack history](https://docs.slack.dev/reference/methods/conversations.history/),
[Slack metadata](https://docs.slack.dev/messaging/message-metadata/).
