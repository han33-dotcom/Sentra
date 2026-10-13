# Sentra agent instructions

Policy version: 1. This is the canonical policy for coding and review agents.
Read [CONTRIBUTING.md](CONTRIBUTING.md) and the linked documents relevant to your task.
Follow applicable nested instructions if they are added later.

## Project and architecture

Sentra is the final-year wearable-data pipeline, private viewer, wellness processing
layer and read-only API. Keep the existing project structure.
- Runtime and collection: [docs/operating-guide.md](docs/operating-guide.md).
- Data meaning and provenance: [docs/data-dictionary.md](docs/data-dictionary.md).
- Database contracts: [docs/schema.md](docs/schema.md).
- Processing and API: [docs/processing.md](docs/processing.md), [docs/read-api.md](docs/read-api.md).
- Team handoff and rollout status: [docs/team-workflow.md](docs/team-workflow.md).

## Starting work

1. Read the current task and its acceptance criteria; identify the human owner/reviewer.
2. Check the repository, branch, working-tree changes and current instructions.
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

- Link the Notion task URL in the PR description, with its task ID when available.
  Explain what changed, why, validation and material limitations. For workflow
  maintenance or releases with no implementation task, explain the scope explicitly.
- Record lasting decisions in repository documentation or the linked task; private
  chat memory is not shared project context.
- Put actionable code-review findings on the PR, tied to files/lines and the reviewed
  commit. Read accepted PR findings directly when fixing them; verify the current head.
- A human teammate reviews and decides whether to approve. Agents do not approve
  on someone's behalf, merge automatically or dismiss unresolved findings.
- Implementation is complete only when accepted changes are merged into `develop`.
  A task is Done only when its acceptance criteria have been verified by a human;
  release/deployment requirements remain separate when applicable.
- Do not claim Slack notifications, shared AI review or Notion status sync occurred
  unless their actual results are available. See the rollout status in the team guide.

## Code Review Rules

- Flag exposure of participant data/credentials, unintended collection activation,
  removal of bounded-operation guards, and missing authorization checks.
- Flag regressions in data provenance, units, timestamp handling or missing values.
- Check database/API compatibility and project-specific documentation when contracts
  change. Distinguish demonstrated bugs from suggestions; include evidence and impact.
- CI handles mechanical checks. Review the latest commit and applicable task criteria.
