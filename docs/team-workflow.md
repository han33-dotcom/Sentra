# Sentra team workflow

## Rollout status

Policy version 3 is authorized in [SEN-86](https://github.com/han33-dotcom/Sentra/issues/86).
Local subscription-authenticated Codex workers perform fixes, acceptance and
merging. Code reviews and human approvals are optional for every change.
See [local delivery](local-delivery.md) for installation, ownership, recovery and
activation evidence. Each machine's actual activation must be recorded separately.

Project synchronization and native Slack subscriptions remain configured.
Collection remains paused. Workspace is `nsquared` and channel is `#fyp-sentra`.
Implementation PRs target `develop`; releases go `develop` → `main`.

## Where work lives

| Place | Responsibility |
|---|---|
| GitHub Issues + Project | Scope, assignee, reviewer, acceptance criteria, priority, due date and progress |
| Repository `docs/` | Technical documentation, architecture, setup and API contracts |
| Root AGENTS.md / CLAUDE.md | Shared coding/review policy and Claude Code import |
| GitHub Wiki | Meeting notes, background and general references |
| Slack | Discussion and project-specific task/PR links |

Start with the [documentation index](README.md). Keep one authoritative copy of a
document. If Wiki decisions affect code, summarize the technical consequences in
the relevant repository document through a PR. Agents consult Wiki context when
needed; ordinary code clones do not include the separate Wiki repository.
Notion was retired from the project. Software tasks belong in GitHub.
Keep private attachments and participant material out of public Issues, Wiki pages
and repository documentation.

## Everyday handoff

1. Create a Team task with assignee, observable Acceptance criteria checkboxes,
   priority and due date. Add it to the Project.
2. Start a focused branch from current `develop` and load AGENTS.md. Keep one writer.
3. Implement scope and run the project checks. Open a PR into `develop` using
   `Project: Sentra`, one `Task URL:` and any `Additional Task URL:` declarations.
   Titles list every SEN ID in declaration order. Include what/why, tests and limits.
4. Use Related to references. The acceptance worker owns issue closure.
5. Keep a PR draft or apply `automation:hold` while editing. Making it ready hands
   the branch to the local worker, which fixes failures and verifies scoped acceptance.
6. Passing required CI and current acceptance evidence allow automatic squash merge.
   Reviews and review requests are optional and never gate the merge.
7. All implementation PRs merged means Implemented. The worker then verifies every
   task criterion. Complete evidence means Done and permits automatic closure.
8. Only inaccessible observations remain for humans. Record reason, exact steps,
   expected result and required evidence. The issue stays open for these items.
   Code can merge/release while those observations remain tracked.
9. Automatic release and ancestry synchronization PRs use merge commits. See
   [local delivery](local-delivery.md) for release timing and pause controls.

## Consistent task identity and multi-task PRs

The issue number is the authoritative task identity: `SEN-41` always means issue
#41. Issue titles use `[SEN-41] description`, which is also the board card title.
PR titles start with the same task identity; GitHub still assigns the PR its own
number. The native Slack app still prepends its own PR number before that title.
The [task-first Slack replacement](task-first-slack.md) puts the task ID first
and the PR link underneath, using one updated card per PR. It stays disabled until
the approved app setup and verified native-subscription cutover; do not run both
senders. Old Slack messages remain historical and are not reposted in bulk.

Declare only actual implementation scope:

```text
Title: [SEN-28, SEN-27] fix: retry joins and refresh participation permissions

Project: Sentra
Task URL: https://github.com/han33-dotcom/Sentra/issues/28
Additional Task URL: https://github.com/han33-dotcom/Sentra/issues/27
```

The required `pr-policy` check verifies every issue endpoint and every title ID.
Duplicate, invalid and foreign links fail validation. The board reconciler groups
the PR under every declared issue; each task reaches Implemented only when all
its remaining implementation PRs are merged. `Related to`, dependency links,
comments and fenced examples do not declare implementation scope. A release into
main does not duplicate implementation evidence from PRs into develop.

The issue prefix applies to every Sentra issue, including closed issues and issues
opened by outside contributors. This preserves the same issue identity in references
and board cards. Adding a prefix does not enroll an issue in the Project or change
its status.

The trusted default-branch job repairs generated issue prefixes and open team PR
title prefixes on issue/PR events and daily reconciliation. It preserves the human
description, reads current metadata before edits, and writes only changed titles
and Project Status. Manual Done and Blocked states are preserved. The local acceptance worker owns
evidence-based completion and closure. An API edit can still race after the final read; the next
reconciliation repairs prefixes, while humans restore any overwritten description.
Title edits made by the job's `GITHUB_TOKEN` do not trigger another Actions run.
Title reconciliation records sanitized errors per issue or PR and continues with
other items. A bad title, stale edit or item-level API failure cannot stop all
repairs; the job exits nonzero after processing the list if any item failed.
Inspect the reported item numbers and rerun after correction. Dry runs report the
same failures without writes; failure to fetch a list still stops the run.

If `pr-policy` already failed before an automatic title repair, rerun that check
against the current head/base (or have the author save the corrected title) before
merging. A repaired title is not itself a claim that checks passed.

SEN-66 introduced task identity and multi-task reconciliation. Task-first Slack
still requires the separate credential and subscription cutover in its guide.
Local delivery does not change that notification setup.

## Status meanings

| Status | Evidence |
|---|---|
| Not started | Scoped task, implementation not begun |
| In progress | Work underway or only draft PRs open |
| In review | At least one implementation PR ready for automated checks and acceptance |
| Changes requested | Legacy status; optional review requests do not block delivery |
| Implemented | All remaining implementation PRs merged into `develop` |
| Done | Every acceptance criterion has recorded verified evidence |
| Blocked | Human-recorded dependency or decision; include reason |

Complete current acceptance evidence permits automatic Done and issue closure.
The metadata reconciler preserves manual Done/Blocked states.
Closed-unmerged PRs are treated as abandoned attempts when open or merged PRs
remain for the same task. Only abandoned PRs still require triage and preserve the
current status. Humans must reconcile any removed scope before accepting the task.
A release PR does not mark every associated feature accepted.

## Activation and collaborator refresh

Follow [GitHub workspace activation](github-workspace-activation.md) and
[PR policy activation](pr-policy-activation.md). Each teammate still completes
[collaborator setup](collaborator-setup.md). After policy merges, pull `develop`,
update ongoing feature branches deliberately and refresh/restart the assistant.
Normal web chats need current repository instructions supplied explicitly when
automatic loading is unavailable.
