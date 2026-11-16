# Local automated delivery

The owner authorized this workflow in [SEN-86](https://github.com/han33-dotcom/Sentra/issues/86).
Code review and human approval are optional for every change. The local worker
uses ChatGPT-authenticated Codex sessions and the user's GitHub credential.
API-key variables are removed from child processes and ChatGPT login is enforced.
Usage draws from the user's subscription. The computer must stay awake and online.
Authentication and allowance failures pause work for retry.

## From a feature to main

1. Scope a Team task with an Acceptance criteria checkbox list. Implement it on
   a focused branch from `develop` using the team's normal local coding agent.
2. Open a PR into `develop` with SEN title and task declarations. Mark it ready
   when handing branch ownership to automation. Draft and `automation:hold` PRs
   are excluded. Workers handle same-repository PRs from configured team accounts.
3. The worker updates the feature branch from its target, runs Python/browser
   tests and the data guard, fixes failures, and waits for CI on the new commit.
4. A local acceptance session exercises the declared PR scope. It publishes
   evidence for the exact head and base. Failed acceptance triggers fixes.
   Required GitHub checks plus `local-acceptance` allow automatic squash merge.
5. After all linked implementation PRs merge, task acceptance verifies every
   issue criterion against integrated `develop`. Complete evidence permits
   automatic closure and Project Done. Multi-PR tasks stay open until complete.
6. Human-only observations remain open with the reason, exact steps, expected
   result and evidence to record. Post observed evidence on the issue to wake
   verification again. Missing dependencies and failures remain agent work.
7. The worker opens `develop` to `main` releases when code differs, verifies
   the integrated release, and uses a merge commit after CI. A
   `codex/release-sync` PR brings release ancestry back with a merge commit.
   Outstanding human-only observations stay on their tasks across releases.
   Failed release checks or acceptance create a repair PR into `develop`; the
   worker never repairs an integration branch by pushing directly to it.

Release/synchronization bookkeeping links SEN-86 and does not declare feature
issues as new implementation. Release acceptance identifies outstanding
verification and limitations. Merging never enables collection or operational jobs.

## Install on Windows

Use Git with Git Credential Manager, Node.js, Python 3.11 and Codex CLI.
Sign in with `codex login`; `codex login status` must report ChatGPT.
GitHub access must allow reading checks, posting evidence, pushing and merging.
Install from the merged implementation checkout using PowerShell.

```powershell
./scripts/team_workflow/install_local_worker.ps1 -Python python -Start
```

The installer creates `%LOCALAPPDATA%/SentraWorker` with a dedicated clone,
Python environment, trusted coordinator runtime and private logs/state.
The `Sentra local delivery` scheduled task starts at logon and runs hidden.
The coordinator runtime is copied from the installed revision and kept separate
from PR checkouts. Stop the task and reinstall from an updated integration
checkout to update it. Each teammate uses their own local sign-in.

```powershell
Stop-ScheduledTask -TaskName 'Sentra local delivery'
Start-ScheduledTask -TaskName 'Sentra local delivery'
Get-ScheduledTaskInfo -TaskName 'Sentra local delivery'
```

For macOS/Linux, configure a dedicated clone and Python 3.11 environment using
the collaborator guide. Copy `scripts/team_workflow` to a separate trusted
runtime directory, place it on `PYTHONPATH`, and use a user-owned scheduler.

```text
python -m scripts.team_workflow.local_worker --root /path/to/dedicated/clone --state-dir /path/to/private/state
```

Use `--once` for one cycle, `--pr NUMBER` for one PR, `--no-release` to pause
releases and `--interval 120` for idle polling seconds. A cycle takes longer
while Codex/tests run. Credentials and private logs stay on the owner's machine.

## Ownership and recovery

A local file lock prevents duplicate processes. The Git ref
`codex/local-delivery-lease` serializes worker machines. Its owner persists the
lease before claiming it and recovers it after restart. Workers never expire
another machine's lease while it may still write. Restart the owning worker
first. Stop it before manually deleting a stranded lease branch in GitHub.

Feature pushes use normal fast-forward checks. Concurrent edits invalidate
acceptance. Interrupted edits are preserved in Git stashes, and
`codex/local-worker-recovery` retains detached commits for recovery. Jobs stay
pending until current checks pass. Failed PRs back off for 15 minutes so other
PRs can progress. Human-only task evidence reruns when the issue changes.
Uncertain remote writes are reconciled from GitHub on the next cycle.

Pause a PR with draft or `automation:hold` before taking back branch ownership.
Wait for an active job to finish or stop the worker. The worker rechecks handoff
state before publishing fixes or merging.

## Protections and evidence

```text
python -m scripts.team_workflow.configure_delivery
python -m scripts.team_workflow.configure_delivery --apply
```

The first command previews settings. The second applies the owner-authorized
policy, preserving protection flags/checks and strict target freshness, removing
the required-review rule and disabling conversation gates.
It adds `local-acceptance` and enables repository auto-merge. Previous settings
are saved in `.private/delivery-protections-before.json`.
GitHub continues enforcing the guard, both Python matrix jobs and PR policy.

Acceptance comments include structured evidence tied to task content and merged
implementation commits. The Project reconciler accepts configured team authors'
current complete reports. Manual Blocked and Done states are preserved. Legacy
tasks need an Acceptance criteria checkbox section for automatic verification.
Optional review comments never become merge requirements.

Only public/synthetic evidence belongs on GitHub. Logs/state stay outside the
tracked checkout. Agents use workspace-write sandboxing. Configure additional
browser/environment access explicitly. A merge alone does not establish that a
teammate installed or started a worker.

## Activation evidence

Record the installed commit, ChatGPT login, checks, protection readback and worker
smoke result on SEN-86, including remaining limitations.
