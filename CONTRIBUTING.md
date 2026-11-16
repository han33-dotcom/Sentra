# Working on Sentra

Use [docs/collaborator-setup.md](docs/collaborator-setup.md) for Windows/macOS setup,
assistant instruction-loading checks and individual onboarding evidence.

Use [docs/pr-policy-activation.md](docs/pr-policy-activation.md) for PR metadata,
scoped exemptions and the owner checklist for required-check activation.

## Setup (once)

Use Python **3.11**. From the repository root in Windows PowerShell:

```powershell
git clone https://github.com/han33-dotcom/Sentra.git
cd Sentra
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-windows.txt
.venv/Scripts/python.exe -m pip install --no-deps -e ".[dev,viewer]"
.venv/Scripts/python.exe -m pip install "streamlit[auth]==1.65.0" "Authlib==1.8.0" pytest pre-commit
.venv/Scripts/python.exe -m pip check
.venv/Scripts/pre-commit.exe install     # blocks data/secrets before they are committed
```

Cloning gives no access to participant data or tokens. Operator configuration
(`config/local.toml`, `.private/`, Streamlit secrets) and encryption keys are created
locally per the stage guides and are never committed.

## Branches

| Branch | Purpose | Who writes to it |
|---|---|---|
| `main` | Released, demo-ready state. | PRs from `develop` only |
| `develop` | Integration branch. | PRs from work branches |
| `feat/<short-name>` | New dataset, feature or module | You |
| `fix/<short-name>` | Bug fix | You |
| `chore/`, `ci/`, `docs/` | Tooling, pipelines, documentation | You |

`main` and `develop` require PRs, green `guard`, Linux/Windows `test`, `pr-policy`
and `local-acceptance` checks. Code review and human approval are optional.
The [local delivery worker](docs/local-delivery.md) runs on a team member's computer
using their existing ChatGPT-authenticated Codex subscription and merges eligible PRs.

Work branches are squash-merged. GitHub's **Automatically delete head branches**
setting is enabled: work branches are deleted after their PR merges, including PRs
into `develop`. Keep `main` and `develop` permanently; both are protected with branch
deletion disabled, so release and back-merge PRs preserve them. The setting applies
to future merges; historical branches need a separate check for merged work, later
commits and open PR dependencies before deletion.

Required checks use strict up-to-date enforcement. Bring the target branch into
work branches deliberately and rerun checks after integration changes. Releases
and back-merges follow the merge-commit procedure below.

## Flow

1. `git switch develop && git pull`, then `git switch -c feat/<short-name>`.
2. Commit in small steps with conventional messages: `feat: add sedentary-period dataset`,
   `fix: ...`, `ci: ...`, `docs: ...`, `chore: ...`.
3. `git push -u origin feat/<short-name>` and open a PR **into `develop`**. CI must be green.
4. The local worker fixes failures, verifies PR scope and squash-merges when checks pass.
5. The worker verifies integrated task acceptance, records evidence and closes fully
   accepted tasks. Human-only observations stay open with verification instructions.
6. The worker opens and merges a `develop` → `main` release when integrated changes
   are available, then synchronizes release ancestry. Use `--no-release` to pause releases.

Merging or deploying code never authorizes restarting collection. The daily
collector (`.github/workflows/collect.yml`) stays paused until the team agrees and
both controls described in the [operating guide](docs/operating-guide.md) are set.

## Keeping release branches current

Release from `develop` into `main`, using a **merge commit** rather than squash or
rebase. This preserves the integration ancestry. The `release` exemption accepts
only this exact same-repository branch pair and a label applied by a configured
team account, including the author or its local worker.

After a release, the worker brings `main` back into `develop` through a
`codex/release-sync` PR using a **merge commit**. Integration branches are updated
through PRs with passing checks.

If the branches have already diverged (as after release #14), start a focused
`codex/sync-main-into-develop` work branch from current `origin/develop`, merge
`origin/main` into it locally, resolve conflicts, run CI and open a PR into
`develop`. Link the same-repository release/synchronization issue and fill the
normal handoff sections; do not claim the release exemption for this PR. Merge
that synchronization PR with a **merge commit**, so `main` becomes an
ancestor of `develop`. Recheck this before the next release:

```text
git fetch origin
git merge-base --is-ancestor origin/main origin/develop
```

Exit code 0 confirms the ancestry. A nonzero result needs the
synchronization above, never a force push or branch-protection bypass.

## Tests

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe scripts/check_no_data.py
```

Tests use synthetic API responses and temporary folders. Live integration tests
(`tests/test_*_live.py`) run only when `SENTRA_LIVE_TESTS=1` or `SENTRA_TEST_CLOUD=1`
is set with operator configuration; CI never sets them. Never put real people's
data in a test; build synthetic responses in the test or under `tests/fixtures/`.

## Shared instructions and review handoff

[AGENTS.md](AGENTS.md) is the canonical policy for coding and review agents.
[CLAUDE.md](CLAUDE.md) imports it for Claude Code. The
[team workflow](docs/team-workflow.md) gives responsibilities, task status meanings
and a simple dashboard date-filter example.

Link the GitHub issue and acceptance criteria from the PR description. Explain what
changed, why, validation and limitations. Keep actionable review findings on GitHub;
the author's assistant reads accepted findings directly and updates the branch.
Reviews are optional. The worker's acceptance evidence and required CI gate merging.

Record lasting decisions in project documents or the task. Implemented means the
required implementation PRs merged into `develop`; Done requires verified acceptance
criteria. Agents perform every accessible check. Only inaccessible observations
remain for human verification, with steps and expected evidence on the issue.
Native Slack PR/review notifications and Project status synchronization are enabled;
see the current [team workflow](docs/team-workflow.md) for scope and limitations.
Use the issue number as the stable task ID: `[SEN-41] description` on tasks and
PRs. A PR implementing several tasks declares one `Task URL:` plus one
`Additional Task URL:` per other implemented task, and lists all IDs in its title
in that order: `[SEN-28, SEN-27] fix: retry joins`. References and dependencies
stay in prose. GitHub's own PR number is a secondary identifier.
For Slack's task-first presentation and the no-overlap cutover, follow
[task-first Slack notifications](docs/task-first-slack.md). Native and custom
PR/review delivery must not run together.

After shared policy changes merge, update clean local `develop` with
`git pull --ff-only` and bring `origin/develop` into ongoing feature branches
deliberately, preserving local changes. Restart or refresh the assistant and verify
it can identify the current instruction files, target branch and checks. Ordinary
web chats need current instruction contents and repository context supplied explicitly.

The configured environment must support the current application dependencies;
see the existing requirements files and CI install steps. In addition to Python
tests and the data guard, run `node --test tests/test_board_chart.cjs` for the board
regressions. Report commands actually run, failures, skips and unavailable checks.

## Where things go

| Change | Place |
|---|---|
| New provider dataset | `src/sentra/datasets.py` (job plan), `normalize.py` / `metric_dictionary.py`, `docs/data-dictionary.md` |
| Storage / schema | `sql/NNN_*.sql`, `src/sentra/cloud_store.py`, `docs/schema.md` |
| Collection / recovery | `src/sentra/cloud_collect.py`, `cloud_run.py`, `daily_plan.py`, `recovery.py` |
| Viewer | `src/sentra/viewer_*.py`, `viewer/app.py` |
| CI / repo rules | `.github/`, `scripts/check_no_data.py` |
