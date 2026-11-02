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
