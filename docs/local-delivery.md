# Agent-owned delivery

Policy version 4, authorized in [SEN-90](https://github.com/han33-dotcom/Sentra/issues/90),
replaces the background worker from SEN-86. The same implementation agent owns
implementation, self-review, fixes, acceptance and delivery, using its existing
local coding session and subscription. No polling process, separate reviewer,
API-key service or `local-acceptance` status is required.

## From a feature to main

1. Read the task and its Acceptance criteria checklist. Start a focused branch
   from current develop; preserve other work and keep one writer on the branch.
2. Implement and test. Open a PR into develop with the task declarations and title
   format in CONTRIBUTING.md. Opening a PR does not transfer branch ownership.
3. Before merging, self-review the latest diff against the task and AGENTS.md:
   correctness, regressions, access, data handling and changed contracts. Fix
   demonstrated problems. Record the reviewed commit, findings/fixes and acceptance
   results in the PR description or a normal comment. Do not submit a formal GitHub
   approval on your own PR. Additional review is optional.
4. Verify all agent-accessible criteria within the PR scope. Run required tests
   and inspect actual CI. Missing dependencies and failing checks remain agent
   work. Integrate the latest target when needed and recheck affected behavior.
   Reuse valid evidence for an unchanged tree; do not repeat full suites without
   a reason. A local pass is not a claim that GitHub CI passed.
5. Recheck the current head/base, criteria, CI and pause state before merging.
   Squash-merge into develop with a head-SHA guard. Never bypass checks or push
   integration branches directly. Draft or `automation:hold` pauses delivery.
6. After all linked implementation PRs merge, verify the whole task on integrated
   develop. Publish the structured evidence below. Close the issue only when every
   criterion is verified. The existing Project reconciler then sets Done.
7. Open a develop-to-main release. Check the complete release diff, identify all
   included work and outstanding observations, wait for current required CI and
   merge with a merge commit. Coordinate with an existing release owner instead
   of opening a competing release. Fix release failures through a work PR.
8. Bring main history back into develop through `codex/release-sync` (or
   `codex/sync-main-into-develop`) and a merge-commit PR. Verify main is an ancestor
   of develop. Skip empty releases when code trees already match. Link bookkeeping
   to the relevant delivery task; it does not add feature implementation scope.

Stay with CI, fixes and merges until delivery completes or a concrete blocker is
reported. If the coding session stops, resume it: no background agent takes over.
Task Done and release completion are distinct; report both accurately. Merging
never authorizes deployment, collection, live tests or operational jobs.

## Human-only observations

Only criteria the agent cannot execute or observe may be `human_required`, such
as a separate physical device or inaccessible external account. For each record:

- Why the observation is unavailable and what verification was attempted.
- Exact numbered steps, prerequisites and the build/commit to use.
- Expected results and what constitutes failure.
- Sanitized evidence to record on the issue, such as device, time and result.

Keep that task open. Its verified code may merge and release with the outstanding
observations identified. When a human supplies evidence, the same agent verifies
it, updates the report and closes the fully accepted task. Never invent evidence,
call an unattempted check passed, or turn a fixable failure into a human request.
Never post participant data, private screenshots or credentials.

## Acceptance evidence and Project Done

Use the pure functions in `scripts/team_workflow/acceptance.py`; they do not launch
agents or perform network writes. `report_schema()` describes each criterion row.
`criteria(issue['body'])` supplies the exact ordered checklist. Each row contains
`criterion`, `status`, `evidence`, `reason`, `human_steps`, `expected_result` and
`record_evidence`. Status is `passed`, `failed` or `human_required`; the last four
fields may be empty for passed/failed rows.

Fetch the current issue, comments and all declared implementation PRs. Exclude
releases into main and `codex/release-sync` bookkeeping. Ensure no linked
implementation PR is still open and at least one is merged. Populate the report
from actual observations, then build its comment:

```python
from scripts.team_workflow.acceptance import (
    body_digest, criteria, evidence_comment, validate_report,
)

# issue: current GitHub issue; report: observed summary and criterion rows.
# tested_commit: exact integrated commit verified by this agent.
# merged_pulls: every merged implementation PR number (string) -> merge_commit_sha.
complete = validate_report(report, criteria(issue["body"]))
report.update(mode="task", issue=issue["number"],
              issue_digest=body_digest(issue["body"]), commit=tested_commit,
              merged_pulls=merged_pulls)
comment = evidence_comment(report)
```

Before publishing, reread the issue body, linked PRs and develop head. If they
changed during verification, discard stale conclusions and reverify affected
criteria. Publish/update the comment from a configured team account using the
agent's normal GitHub tools. Preserve the emitted marker and JSON. Only after the
current complete comment is recorded may the agent close the issue as completed.
Failed or human-required criteria leave it open. Project reconciliation checks
the author, task-content digest and merged PR mapping before using the report for
Done. Manual Done/Blocked states remain preserved. Inspect the actual reconciliation
result rather than claiming a board update.

## Retiring the worker

The scheduled task on the installation machine is stopped and disabled. Other
machines with the former installation must stop and disable it too:

```powershell
Stop-ScheduledTask -TaskName 'Sentra local delivery'
Disable-ScheduledTask -TaskName 'Sentra local delivery'
```

The repository no longer contains the installer, polling runtime or acceptance
status invalidation workflow. Do not run a saved older runtime. Preserve interrupted
changes, private logs and protection backups. Before removing a stranded
`codex/local-delivery-lease` ref, confirm its worker is stopped and its saved lease
SHA matches the remote ref. Credentials need not be removed.

## GitHub protections

`python -m scripts.team_workflow.configure_delivery` previews the migration;
`--apply` applies it under the owner's authorization. It removes `local-acceptance`
and required-review rules while preserving other checks, strict freshness,
admin enforcement and force-push/deletion protection. Repository auto-merge stays
available; the implementation agent still owns delivery.

Required checks are `guard`, `test (ubuntu-24.04, py3.11)`,
`test (windows-2025, py3.11)` and `pr-policy`. Self-review and acceptance are agent
responsibilities recorded on the PR/task, not a second approval gate.
