# Sentra team workflow

## Rollout status

The reviewed workflow is on `main`; metadata-only Project synchronization is enabled
and live writes were verified on October 21, 2026. The private board, Wiki, approved
access and native Slack subscriptions are configured. The owner confirmed the
listed teammates' own-account board access. The human pilot (issue #21),
acceptance reconciliation and local agent onboarding remain unverified; rollout
issue #16 stays open. Merging all of a task's remaining linked implementation PRs
gives Implemented; only a human sets Done.
Release #18 and reviewed merge-commit back-merge #22 are merged.
Collection remains paused. Shared cloud AI review is optional and deferred.

Workspace: `nsquared` (`T0C8YHJMXAN`). Channel: `#fyp-sentra`.
Implementation PRs target `develop`. Sentra releases go `develop` → `main`.

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
Existing Notion reports and original tasks remain available as historical records;
new software tasks belong in GitHub. Private attachments and participant material
must not be published in public Issues, Wiki pages or repository documentation.

## Everyday handoff

1. Create an issue using **Team task**; set its native Assignees field, **Human reviewer** (a teammate's GitHub handle),
   acceptance checklist, Priority and Due date. Add it to this project's board.
2. Pull current `develop`, refresh the assistant's instructions and create a focused
   work branch. One writer works on the branch at a time.
3. Implement the issue scope and run the checks in AGENTS.md.
4. Open a PR into `develop` with `Project: Sentra` and one full primary `Task URL:`
   pointing to this repository's issue. For each other task this PR implements,
   add an `Additional Task URL:` line (maximum 10 total tasks). Title the PR
   `[SEN-28, SEN-27] description`, listing every declared issue in order. A single
   task uses `[SEN-28] description`. Optional `Task ID:` matches the primary issue.
   Include what/why, test evidence and risks. Dependencies remain prose references.
5. Use **Related to #NUMBER**, not Closes/Fixes/Resolves. Automatic closing keywords
   would bypass the separate human acceptance step.
6. The teammate opens the PR from GitHub or Slack and asks their own assistant to
   review its current head and issue criteria. Findings stay on the PR.
7. The author's assistant reads the findings directly, fixes accepted issues and
   reruns checks. The human reviewer decides approval; agents do not approve or merge
   on someone's behalf.
8. Keep the branch up to date with `develop` and rerun required checks after
   integration changes. Merge through the existing review rules. All required
   implementation PRs merged means **Implemented**. A teammate records acceptance
   evidence, sets **Done** and then closes the issue. Status synchronization is
   active; humans still own acceptance.

The tracking issue for this rollout is [#16](https://github.com/han33-dotcom/Sentra/issues/16).
Task ownership does not require buying a cloud AI reviewer. Personal assistants run
when their human starts them; a Slack notification does not start a teammate's chat.

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

The trusted default-branch job repairs generated issue prefixes and open team PR
title prefixes on issue/PR events and daily reconciliation. It preserves the human
description, reads current metadata before edits, and writes only changed titles
and Project Status. Done, Blocked, closed-issue status, acceptance and closure
remain human-owned. An API edit can still race after the final read; the next
reconciliation repairs prefixes, while humans restore any overwritten description.
Title edits made by the job's `GITHUB_TOKEN` do not trigger another Actions run.
If `pr-policy` already failed before an automatic title repair, rerun that check
against the current head/base (or have the author save the corrected title) before
merging. A repaired title is not itself a claim that checks passed.

Rollout for [SEN-66](https://github.com/han33-dotcom/Sentra/issues/66): the title
check becomes active after independent review and merge into develop. Automatic
title repair and multi-task Project reconciliation become active only after the
normal reviewed release carries these changes to main. Preview the updated job
with `dry_run=true`, inspect task mappings, then verify a write run and a second
no-change run. Do not claim the permanent automation is live before that release.
Task-first Slack delivery additionally requires the separate credential and
cutover in the linked guide; title prefixes alone do not change native formatting.

## Status meanings

| Status | Evidence |
|---|---|
| Not started | Scoped task, implementation not begun |
| In progress | Work underway or only draft PRs open |
| In review | At least one implementation PR ready for review |
| Changes requested | Outstanding change request from an independent configured human reviewer |
| Implemented | All remaining implementation PRs merged into `develop` |
| Done | Teammate verifies acceptance and records evidence |
| Blocked | Human-recorded dependency or decision; include reason |

Automation never sets Done, closes issues or overwrites manual Done/Blocked.
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
