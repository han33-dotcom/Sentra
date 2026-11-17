# Sentra agent instructions

Policy version: 4. This is the canonical policy for coding and acceptance agents.
Read [CONTRIBUTING.md](CONTRIBUTING.md) and the linked documents relevant to your task.
Follow applicable nested instructions if they are added later.

For code delivery, this policy and [agent-owned delivery](docs/local-delivery.md)
supersede historical stage plans, old review assignments and publication-approval
checklists. Those records remain evidence, not current merge gates. Operational,
consent, expert and destructive-data approvals still apply. Explicit current user
instructions and higher-priority environment rules retain their precedence.

## Project and architecture

Sentra is the final-year wearable-data pipeline, private viewer, wellness processing
layer and read-only API. Keep the existing project structure.
- Runtime and collection: [docs/operating-guide.md](docs/operating-guide.md).
- Data meaning and provenance: [docs/data-dictionary.md](docs/data-dictionary.md).
- Database contracts: [docs/schema.md](docs/schema.md).
- Processing and API: [docs/processing.md](docs/processing.md), [docs/read-api.md](docs/read-api.md).
- Team handoff and rollout status: [docs/team-workflow.md](docs/team-workflow.md).

Documentation index: [docs/README.md](docs/README.md). General references and meeting
notes live in the project Wiki after publication. Consult relevant Wiki decisions
when a task depends on them; summarize code-affecting decisions in reviewed docs.

## Starting work

1. Read the current task and its acceptance criteria; identify the task owner.
2. Check the repository, branch, working-tree changes and current instructions.
   Fetch `origin/develop` when access is available and compare its `AGENTS.md`,
   `CONTRIBUTING.md` and `docs/local-delivery.md` with this checkout. Read newer
   policy before continuing; integrate updates deliberately, preserving local work.
   Do not reset dirty branches or silently remove personal/managed instructions.
   If refresh fails, report the limitation instead of claiming current policy.
3. Work on a focused branch based on `develop`; implementation PRs target `develop`.
   Releases go from `develop` to `main`. Do not push directly to either integration branch.
4. Preserve other people's changes and keep one writer per work branch.
5. If task information or access is unavailable, state what is missing; do not invent
   requirements, task IDs, permissions or test results.

## Scope and data rules

- Collection remains paused. Merging or deploying never authorizes restarting it.
  Do not enable collection controls, live provider tests or operational jobs as a
  side effect of development. Follow existing explicitly authorized operator work
  and the operating guide when the task itself covers those actions.
- Never commit participant data, original responses, exports, backups, credentials,
  private configuration or real-data screenshots. Use synthetic test fixtures.
- Preserve capacity/egress guards and bounded requests. Activity-level collection
  is on request only; do not silently add it to automatic plans.
- Preserve provenance, units, timestamps and missingness. Do not invent readings,
  fill gaps or alter interpretation without an explicit task and documentation.
- Use wellness/fitness-for-shift language. Do not make diagnostic or medical-grade
  claims; threshold changes require the project's existing expert approval.
- Keep unrelated refactoring and new dependencies out of a focused task.

## Checks and evidence

Use Python 3.11 and the repository's documented dependencies.
Run from the repository root in the configured development environment:
```text
python -m pytest -ra
python scripts/check_no_data.py
node --test tests/test_board_chart.cjs
```
Windows virtual environments may use `.venv/Scripts/python.exe` instead of `python`.
Live-test opt-in variables stay unset for ordinary development.
Report the exact command, result and any skipped or unavailable validation.
CI runs the Python suite on Linux and Windows and the existing guard. Check the
actual PR results; a local success is not a claim that CI passed.

## Handoff and Definition of Done

- Link the same-repository GitHub issue URL in the PR description.
  Use `[SEN-NUMBER] description` for task/PR titles. Declare one primary `Task URL:`
  and one `Additional Task URL:` per other task implemented by that PR (maximum 10
  total); the PR title lists every ID in declaration order, for example
  `[SEN-28, SEN-27] fix: retry joins`. Dependencies stay in prose, not these fields.
  Explain what changed, why, validation and material limitations. For workflow
  maintenance or releases with no implementation task, explain the scope explicitly.
- Use Related to #NUMBER instead of automatic issue-closing keywords. The implementation
  agent closes tasks only after complete acceptance evidence is recorded.
- Record lasting decisions in repository documentation or the linked task; private
  chat memory is not shared project context.
- Put actionable code-review findings on the PR, tied to files/lines and the reviewed
  commit. Read accepted PR findings directly when fixing them; verify the current head.
- The implementation agent owns delivery end to end. Before merging, self-review
  the current diff against task criteria and project rules, fix demonstrated problems,
  and record the reviewed commit and outcome on the PR. Additional reviewers and
  formal GitHub approval are optional; do not wait for a teammate or separate agent.
- Use the same local coding session and existing subscription for implementation,
  self-review, fixes, acceptance and merging. There is no background delivery worker
  or required `local-acceptance` status. Keep branch ownership with the author/agent.
- Once current required CI and agent-verifiable acceptance pass, squash-merge work
  PRs into `develop`, then release `develop` to `main` and synchronize main ancestry
  back into develop through PRs using merge commits. No direct integration pushes.
- Implementation is complete when required implementation PRs merge into `develop`.
  Agents verify every observable acceptance criterion with recorded evidence.
  All criteria verified means Done and permits automatic issue closure.
- Only criteria the agent genuinely cannot execute or observe remain for a human.
  Record the reason, exact verification steps, expected result and evidence to record.
  Missing dependencies, failing tests and unfinished implementation require agent
  work. They must not be relabeled as human-only checks or passing outcomes.
- Keep tasks with human-only criteria open with those specific instructions.
  Their code may merge and release once machine checks and scoped PR acceptance pass.
- Follow [agent-owned delivery](docs/local-delivery.md) for the complete procedure
  and machine-readable task evidence. Do not finish at opening a PR: stay with CI,
  fixes, merges and release until delivered or a concrete external blocker remains.
  Draft PRs and `automation:hold` mean delivery is intentionally paused.
- Do not claim Slack notifications, shared AI review or Project status sync occurred
  unless their actual results are available. See the rollout status in the team guide.

## Self-review and Optional Additional Review

- Flag exposure of participant data/credentials, unintended collection activation,
  removal of bounded-operation guards, and missing authorization checks.
- Flag regressions in data provenance, units, timestamp handling or missing values.
- Check database/API compatibility and project-specific documentation when contracts
  change. Distinguish demonstrated bugs from suggestions; include evidence and impact.
- CI handles mechanical checks. Review the latest commit and applicable task criteria.
