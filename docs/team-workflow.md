# Sentra team workflow

## Current rollout

Shared policy and contributor guidance are introduced by this change. Existing CI,
PR review and contribution procedures continue to apply. Shared automatic AI review,
Slack notifications, Notion status sync and automated fixes are later rollout steps;
this document describes their target behavior, not an assertion that they are active.

Workspace: `nsquared`. Project channel: `#fyp-sentra`.
Implementation flow: work branch → `develop`; release flow: `develop` → `main`.

## Responsibilities

| Participant/tool | Responsibility |
|---|---|
| Task owner and their assistant | Implement scoped work, run checks, open the PR, address accepted findings |
| Human reviewer and their assistant | Inspect current code and criteria; leave findings on GitHub; human decides approval |
| Notion | Task scope, owner/reviewer, acceptance criteria, deadlines and completion evidence |
| GitHub | Code, test evidence, PR discussion, review and merge |
| Slack | Team discussion and links to tasks/PRs |
| Shared automation, when enabled | Run configured review jobs, send notifications and synchronize lifecycle evidence |

Teammates may use different assistants. All use the same versioned `AGENTS.md`.
Claude Code loads it through `CLAUDE.md`; other environments must explicitly load
the current file if they do not support automatic repository instruction discovery.

## Everyday handoff

1. Define a task in Notion with an owner, reviewer and observable acceptance criteria.
2. Start a work branch from updated `develop`. Give your assistant the task link
   and have it read the current instructions and relevant architecture documents.
3. Implement and validate the work. Open a focused PR into `develop`.
4. Put the task link, change explanation, check results and limitations in the PR.
5. Ask the human reviewer to inspect that PR. Their assistant reads the same PR and
   repository instructions; actionable findings stay on GitHub.
6. Decide which findings require changes. The author/assistant fixes accepted findings
   on the branch and reruns checks. Do not run two coding agents on that branch at once.
7. The human reviewer checks the latest head and approves when satisfied.
8. Merge according to the existing contribution flow; verify the task's acceptance
   criteria and record completion evidence. Releases remain a separate PR into `main`.

Before automation is activated, notify the reviewer with the PR link and update
Notion manually. After activation, use observed automation results; report failures
instead of assuming a task was updated.

## Simple example: date filter on the dashboard

Hasan owns a Notion task to add a date filter. The task specifies that the selected
range limits displayed records, empty ranges show an empty state, and access controls
remain intact. Mohammad Nasrallah is the human reviewer.

1. Hasan's assistant reads `AGENTS.md`, implements on `feat/dashboard-date-filter`,
   runs the checks and opens a PR into `develop` linked to the task.
2. GitHub runs existing CI. Hasan gives Mohammad the PR link. When enabled, the
   shared AI reviewer adds findings and Slack posts the review notification.
3. Mohammad asks Claude Code to review that PR against the task and shared rules.
   Claude records code findings on GitHub; Mohammad decides what requires correction.
4. Hasan asks his assistant to address accepted PR findings. It reads the comments
   directly, updates the branch and reruns validation.
5. Mohammad reviews the latest changes, approves and merges. The task is Implemented.
   Once acceptance is verified, a human records Done. When enabled, synchronization
   handles its configured status updates; it does not replace acceptance verification.

The PR is the durable handoff. Neither assistant needs the other person's private
conversation or a copied summary to inspect the implementation.

## Task status meanings

| Status | Evidence |
|---|---|
| Not started | Scoped task, work not begun |
| In progress | Implementation underway |
| In review | PR ready for review |
| Changes requested | Accepted review findings remain to address |
| Implemented | Required implementation PRs merged into develop |
| Blocked | A person records a dependency or decision and its reason |
| Done | Human verifies acceptance criteria and records evidence |

The current tracker may not yet contain every target status. Use existing fields
and a clear note until the tracker upgrade. One merged PR does not complete a task
with other required PRs or acceptance work remaining.

## Keeping shared instructions current

Policy changes are ordinary reviewed repository changes. After they merge:
- Update `develop` with `git pull --ff-only` when its worktree is clean.
- Update an ongoing feature branch deliberately with the latest `origin/develop`,
  preserving local work and resolving any conflicts.
- Restart or refresh the assistant session, then verify it can identify the active
  instruction files, target branch and checks.
- Ordinary web chats need current file contents/repository context supplied explicitly;
  connecting a service alone does not prove the assistant has loaded these files.

Each teammate configures their own tool/account. This repository does not alter
private machine settings or grant credentials. Local onboarding verification follows
in the collaborator-setup task.
