# Synthetic workflow acceptance fixture

This documentation-only fixture exercises the Sentra team workflow in issue #21.
It changes no application behavior, collection controls or participant data.

The reviewer should request a concrete wording improvement on PR #23. The author
will implement that request, run checks and request a real latest-head re-review.
An approval, a later small documentation commit and a fresh approval exercise
stale-review dismissal before the human-controlled merge.
An outstanding Changes requested review remains active after a fix or re-review
request; its reviewer must submit Approve on the latest head to clear it.

Record observed board transitions, check runs, native Slack notifications and
human acceptance evidence in issue #21. This fixture is not acceptance evidence
by itself. Sentra collection remains paused.

## Verified review checkpoints

On November 2, Aboulhoda approved head `5b3ac4c` with all required checks passing.
With that approval valid, the branch up to date and no unresolved review threads,
removing only the task link caused the required policy check to fail and blocked
merging. Restoring the link recovered passing checks and a clean merge state:
[policy failure](https://github.com/han33-dotcom/Sentra/actions/runs/41529568757/job/125565972275),
[policy recovery](https://github.com/han33-dotcom/Sentra/actions/runs/41529799229/job/125566732037).

This evidence commit exercises stale-approval dismissal. Record the actual
dismissal and subsequent fresh human approval in issue #21 before the final merge.
