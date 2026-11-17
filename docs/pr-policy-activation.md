# Sentra PR policy activation

Policy version 4 assigns self-review and delivery to the implementation agent.
[SEN-90](https://github.com/han33-dotcom/Sentra/issues/90) supersedes the background
worker from SEN-86. Use [agent-owned delivery](local-delivery.md) for the procedure.

## PR handoff

- Declare `Project: Sentra`, exactly one same-repository `Task URL:` and up to nine
  `Additional Task URL:` lines for other implemented tasks.
- Title the PR with all declared IDs in order, such as `[SEN-28, SEN-27] description`.
- Complete What & why, How tested, and Risks / limitations sections.
- Use Related to references. Acceptance evidence controls issue closure.
- The author/agent retains branch ownership. Draft or `automation:hold` pauses delivery.

## Scoped exemptions

A configured team account, including the author or their coding agent, may apply
`workflow-maintenance` for allowlisted workflow/docs paths or `release` for the
exact same-repository `develop` to `main` branch pair. The latest label event and
changed/renamed paths are validated. Scope restrictions remain enforced.

## Checks and execution

Required checks are `guard`, `test (ubuntu-24.04, py3.11)`,
`test (windows-2025, py3.11)`, and `pr-policy`.
The retired `local-acceptance` status must not be required.
Strict up-to-date enforcement, force-push/deletion protection and PR routing remain.
The required-review rule is removed and the review-thread gate is disabled.

The read-only PR-policy checker executes the immutable target commit. For exact
same-repository `develop` to `main` releases, it executes the event's immutable
head commit already integrated into protected `develop`. This lets policy updates with passing checks reach main without obsolete human exemption gates. The isolated
policy-tests job also exercises proposed policy changes without injected credentials.
The implementation agent records self-review and acceptance in its existing coding session.

## Activation verification

Run `python -m scripts.team_workflow.configure_delivery` to preview. Apply with
`--apply` under the owner's existing authorization, then read back both protections.
Run the Python suite, data guard and browser regressions. Inspect the actual PR CI.
Record the disabled worker, protection readback, self-review and delivery evidence on SEN-90.
Historical rollout checks from policy version 2 do not impose human review gates.
