# Sentra PR policy activation

Policy version 3 removes mandatory reviews and human approvals. The owner authorized
this change in [SEN-86](https://github.com/han33-dotcom/Sentra/issues/86).
Use [local delivery](local-delivery.md) for installation and protection migration.

## PR handoff

- Declare `Project: Sentra`, exactly one same-repository `Task URL:` and up to nine
  `Additional Task URL:` lines for other implemented tasks.
- Title the PR with all declared IDs in order, such as `[SEN-28, SEN-27] description`.
- Complete What & why, How tested, and Risks / limitations sections.
- Use Related to references. Acceptance evidence controls issue closure.
- Draft or `automation:hold` retains author ownership. Ready team PRs enter local delivery.

## Scoped exemptions

A configured team account, including the author or its local worker, may apply
`workflow-maintenance` for allowlisted workflow/docs paths or `release` for the
exact same-repository `develop` to `main` branch pair. The latest label event and
changed/renamed paths are validated. Scope restrictions remain enforced.

## Checks and execution

Required checks are `guard`, `test (ubuntu-24.04, py3.11)`,
`test (windows-2025, py3.11)`, `pr-policy`, and `local-acceptance`.
Strict up-to-date enforcement, force-push/deletion protection and PR routing remain.
The required-review rule is removed and the review-thread gate is disabled.

The read-only PR-policy checker executes the immutable target commit. For exact
same-repository `develop` to `main` releases, it executes the event's immutable
head commit already integrated into protected `develop`. This lets policy updates with passing checks reach main without obsolete human exemption gates. The isolated
policy-tests job also exercises proposed policy changes without injected credentials.
Local acceptance runs on the owner's computer using ChatGPT-authenticated Codex.

## Activation verification

Run `python -m scripts.team_workflow.configure_delivery` to preview. Apply with
`--apply` under the owner's existing authorization, then read back both protections.
Run the Python suite, data guard and browser regressions. Inspect the actual PR CI.
Record a local worker run, its subscription authentication and evidence on SEN-86.
Historical rollout checks from policy version 2 do not impose human review gates.
