# Sentra PR policy activation

## Prepared versus active

The foundation policy was reviewed by `MohamadNasrallah` and merged on October 15.
The owner required `pr-policy` on `develop` and, after release #18, on `main` on
October 21. Live policy failure/recovery tests on #20 passed. Isolating policy-based
merge blocking with other requirements satisfied and the human pilot remain pending.
Existing review protections remain active; follow-up fixes need their own review.
Individual collaborator onboarding can remain pending during this preparation.

## PR handoff

Use the PR template:
- Exactly one `Project: Sentra` line.
- Exactly one `Task URL:` line containing the canonical HTTPS GitHub issue URL from this repository.
- Optional `Task ID:` with SEN-number when assigned; never invent an ID.
- Completed `## What & why`, `## How tested` and `## Risks / limitations` sections.

HTML comments and fenced examples do not satisfy the fields. Use exactly
`https://github.com/han33-dotcom/PROJECT/issues/NUMBER`, substituting this
repository's name and positive issue number. No query, fragment, credentials,
port or PR URL is accepted. The read-only checker fetches that issue from this
repository and rejects GitHub issue endpoints that actually represent PRs.
Optional Task ID uses the matching issue number (SEN-NUMBER / TECH-NUMBER),
not a legacy imported Notion ID. Use Related to #NUMBER instead of automatic
issue-closing keywords; merging is Implemented, and acceptance controls Done.
The validator checks PR descriptions. Reviewers must also check closing keywords
in commit messages and GitHub Development links; those can close issues independently.

## Scoped exemptions

A `workflow-maintenance` label can exempt a task link only when every changed or
renamed path belongs to the workflow/docs allowlist in
[scripts/team_workflow/policy.py](../scripts/team_workflow/policy.py).
An application file cannot be hidden by renaming it into docs.

A different configured human teammate must apply the label. The PR author cannot
approve their own exemption; the latest label application controls authorization.
When using an approved exemption, remove the blank Task URL line from the template.
An exemption still requires the project declaration, meaningful handoff sections,
passing code checks and human PR approval.

The `release` label can exempt the task link only for a same-repository `develop` →
`main` release, applied by another configured teammate. Named release work branches
are intentionally ineligible. Follow [Keeping release branches current](../CONTRIBUTING.md#keeping-release-branches-current)
before opening a release; it is not an application-PR bypass.

Sentra exemption actors are `han33-dotcom`, `MohamadNasrallah` and
`mhmdaboulhoda`. The owner explicitly confirmed `mhmdaboulhoda` on October 15.
This authorizes independent exemption labels, not CODEOWNER approval; the author
still cannot exempt their own PR.

Labels must exist in GitHub before a teammate applies them. No author-created label
is treated as independently approved merely because its text matches an exemption.

## Trusted execution and bootstrap

`.github/workflows/pr-policy.yml` uses the ordinary `pull_request` event and only
read permissions; it does not use repository integration secrets.
- `policy-tests` runs proposed policy tests in an isolated job with no injected token.
- `pr-policy` checks out the event's immutable base commit under `trusted/`, then
  runs only that base's validator with a read-only GitHub token.
- It reads current PR metadata, files and label history; it never checks out or
  executes proposed application code in the token-bearing job.
- Stale events, metadata changes and API failures fail closed.

The first foundation PR's base does not contain the validator yet. Its `pr-policy`
job intentionally fails with **Bootstrap pending** rather than pretending enforcement
is active. A teammate must review the foundation changes, including the workflow,
and approve the bootstrap merge under existing protections. Do not make this new
check required before that bootstrap, and do not bypass existing required checks.
Activate on `develop` after that merge. Activate on `main` only after the reviewed release carries the validator into `main`; its first release has the same bootstrap dependency.

The Python validator checkout is trusted base code; the workflow definition is
still PR-controlled content on the ordinary `pull_request` event. A PR changing
`.github/workflows/pr-policy.yml` could change its steps. CODEOWNER review is the
security boundary for workflow/policy changes, not a guarantee from this check.
The existing wildcard CODEOWNERS rule covers these files. Sentra already requires
CODEOWNER approval on `develop` and `main`.

## Owner activation checklist

The owner authorized settings changes through the authenticated GitHub REST API.
Both branches now require resolved review threads; the existing review/code checks
are preserved. Main's `pr-policy` requirement was enabled after the bootstrap release.

1. Inspect the PR and verify code, policy regression tests and existing CI results.
   Confirm at least one other human approval before merge.
2. Merge the reviewed foundation PR through existing protections.
3. Open a small real test PR against the target branch and inspect the actual emitted
   check names. Its PR body must satisfy the template, or receive a valid exemption.
4. In Settings → Rules / Branches, require one approving review, dismiss stale
   approvals after new commits, require CODEOWNER review and resolve review threads.
   Keep force pushes/deletion blocked; avoid ordinary-user bypasses.
5. Require the actual code-check names and `pr-policy`, selecting GitHub Actions as
   the expected source when offered. Do not require job names guessed from a matrix.
6. With current human approval and other required checks passing, remove the task
   link without an exemption: verify the policy fails and GitHub blocks merge.
   Restore the link and verify fresh success. A blocked PR that also lacks approval
   does not isolate which requirement caused the block.
7. Confirm the author cannot supply their own required approval. A different teammate
   performs the approval and verifies approval becomes stale after a new commit.
8. Record settings and pilot evidence in the workflow task; delete/close only the
   synthetic test PR after verification.

Expected code jobs to verify in live results:
- `guard`
- `test (ubuntu-24.04, py3.11)`
- `test (windows-2025, py3.11)`
- `pr-policy`

## Verification available now

```text
python -m unittest discover -s tests/team_workflow -v
```

These regression tests exercise valid/invalid task metadata, independent label
authorization, scoped files, renamed files, release routing and stale-event/API
handling. Passing them is implementation evidence, not proof that remote merge
blocking or collaborators' machines have been verified.
