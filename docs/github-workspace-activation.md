# Activate the Sentra GitHub workspace

## Current state

Foundation [PR #15](https://github.com/han33-dotcom/Sentra/pull/15) was approved by
`MohamadNasrallah` and merged into `develop` on October 15, 2026. Follow-up #17 is
also merged. Synchronization #19, preview-gate #20 and reviewed release #18 remain
prerequisites for activation on `main`.
The private [Sentra board](https://github.com/users/han33-dotcom/projects/1) and public
[Wiki](https://github.com/han33-dotcom/Sentra/wiki) were published on October 14, 2026.
On October 15, approved board Write grants and Slack PR/review subscriptions were
applied and verified. Expiring Projects credentials and the actual Project node IDs
were securely saved and verified later that day. Default-branch activation and the
human acceptance pilot remain pending. Board status is updated manually until activation.
Both repositories explicitly have `TEAM_SYNC_ENABLED=false`.
No Notion API token or synchronization is needed for the new setup.

## Project board

The board already exists; do not create a duplicate. It has all seven Status options:
Not started, In progress, In review, Changes requested, Implemented, Done and Blocked.
This is also the saved board column order, verified after reload on October 15.
The Status board and **All tasks** table are available. For your own work, filter
Assignees with `assignee:@me`; a dedicated saved My tasks view remains optional polish.

Use **Priority** (High/Medium/Low), **Due date** (date), **Human reviewer** (text GitHub
handle) and **Blocked reason** (text). Use native **Assignees** for the task owner.
GitHub's built-in Reviewers field refers to PR reviewers; it is not the task's Human
reviewer field. Acceptance criteria and completion evidence belong in the issue body.

Native auto-add is enabled only for `han33-dotcom/Sentra` with `is:issue`; new items
start at Not started. Automatic issue closure, PR-merge completion and sub-issue
addition are disabled. Keep Done under human acceptance control.

Rollout issue #16 is attached, assigned to `han33-dotcom`, In progress and High
priority. The four original university report/meeting records remain in Notion;
no private records were published to the Wiki.

The owner approved and applied Write access for `MohamadNasrallah` and
`mhmdaboulhoda` on October 15; Manage access shows both with Role: Write.
Teammates still need to verify opening the board from their own accounts.
Repository permissions do not automatically confer Project access.

The authenticated Project API verified the owner, private visibility, required fields
and exactly one linked repository matching this project on October 15. Before
activation, teammates must also verify opening the board from their own accounts. Its private visibility does not make repository issues
private; these issues and the Wiki are public.

## Project synchronization credentials and activation

The repository `GITHUB_TOKEN` reads issues, PRs and reviews. GitHub Projects needs
additional authentication; the default repository token does not grant Project
access. Use a GitHub App with appropriate Project access where supported, or an
expiring personal token with Projects read/write permission for this account.
Store it as the Actions secret **PROJECTS_TOKEN**; never paste it into chat, tasks,
Wiki pages, logs or code. A personal Projects token can cover more than one board;
our code additionally validates the configured owner and exactly linked repository.

Set Actions variable **TEAM_PROJECT_ID** to this board's actual GraphQL node ID
(`PVT_...`), not its visible numeric URL suffix. Obtain it using GitHub's documented
Project API query or an authenticated CLI. Set **TEAM_SYNC_ENABLED** to `true` only
when the reviewed workflow code is on the repository's **default branch** (`main`),
the correct Project exists, and its fields, repository link and credentials are
verified. Sentra therefore needs the normal reviewed develop-to-main release before
its default-branch automation can run. Do not bypass branch protections.

After the preview-gate change reaches `main`, run **Team project sync** manually
with dry_run checked while `TEAM_SYNC_ENABLED=false`. Inspect proposed transitions
before enabling sync; scheduled/event runs and manual writes remain disabled.
Then enable sync and run an approved fixture with dry_run unchecked. The worker consumes current
metadata rather than event bodies; it does not check out PR code or execute task text.
Events wake it through a separate signal workflow with no credentials or checkout.
Daily reconciliation repairs missed events; same-repository writes are serialized.
API requests have timeouts, bounded pagination and retries for transient HTTP errors.
Triage/API errors make the run fail and leave completion unclaimed.

Only PR authors in the configured team roster can influence task status; external
contributor PRs need manual triage until deliberately added to that roster.
The worker updates only Project Status, never issue content/closure, assignments or
acceptance evidence. It preserves closed issues and manual Done/Blocked. A remaining
race exists if a human edits Status after the final read and before the API write;
GitHub supplies no compare-and-swap here. If that happens, restore the intended manual
state and rerun. This is not a guarantee of atomic human/automation updates.

## Wiki publication

The Wiki has Home, project background, meeting-note index, meeting-note template,
references and a sidebar. General material is maintained in the Wiki; temporary
repository bootstrap copies have been removed. Technical documentation remains in
`docs/`, with canonical agent instructions at the repository root.

Wiki editing was verified as restricted to repository collaborators.
Do not publish participant data, private contacts, university attachments or original
private meeting records without explicit approval. The references page links agent instructions on the normal implementation branch
(Sentra `develop`, TechScout `main`), updated on October 21.

## Slack subscriptions

GitHub's official Slack app is installed in **nsquared** (`nsquared-corp`), with its
GitHub installation restricted to Sentra and TechScout. Optional code-channel
management was unchecked; shared cloud AI review remains deferred.

In `#fyp-sentra`, GitHub [confirmed the subscription](https://nsquared-corp.slack.com/archives/C0C92DZ9TN0/p1792048788286009)
for `pulls` and `reviews`; `/github subscribe list` shows only this repository.
No existing subscription was removed. The configured command is:

```text
/github subscribe han33-dotcom/Sentra pulls reviews
```

Inspect `/github subscribe list` before changing subscriptions. Native messages handle PR/review events; no custom bot duplicates
those messages. Task descriptions and review details remain on GitHub. Receiving a
notification does not automatically launch a teammate's personal AI assistant.

## October 21 activation checkpoint

- Mohamad approved follow-up #17, which merged into `develop` on October 15.
- Synchronization #19 repairs main ancestry without changing develop's file tree.
  It must merge with a merge commit before release #18; release and the subsequent
  reviewed back-merge also require merge commits and real human approval.
- `pr-policy` is now required on `develop` alongside the existing guard and both
  Python matrix jobs. Both integration branches require resolved review threads,
  one CODEOWNER approval and stale-approval dismissal. Main retains its existing
  code checks; add `pr-policy` only after the bootstrap release reaches main.
- `TEAM_SYNC_ENABLED=false`, `SENTRA_COLLECTION_ENABLED=false` and the Project node
  ID were read back. The existing `PROJECTS_TOKEN` secret remains present; its next
  live authentication check is the default-branch preview. No live write or pilot
  is claimed. Collection remains paused throughout activation.
- Teammate board access checks, the full review/change/fix/acceptance pilot and
  replay checks remain pending.
- Live policy tests on #20 rejected a missing task link and a self-applied
  exemption. GitHub reported merging blocked; restoring the task link and removing
  the temporary label recovered a successful policy check. The
  [self-exemption run](https://github.com/han33-dotcom/Sentra/actions/runs/39586012538/job/119175003125)
  records the independent-label rejection. No human approval was supplied by an agent.
- Dedicated synthetic pilot [#21](https://github.com/han33-dotcom/Sentra/issues/21)
  records the remaining human actions and required evidence. Its criteria remain
  unchecked until observed; the rollout issue remains open.

## October 15 verification checkpoint (historical)

- `MohamadNasrallah` approved the current foundation head and merged #15 into `develop`.
- The existing one-approval requirement and stale-review dismissal are preserved;
  branch protections were not weakened.
- Foundation CI and policy regression jobs passed at reviewed head `12ed8e405883`.
  Its metadata job logged `Bootstrap pending`. Follow-up PRs can now validate
  against the merged base; required-check enforcement remains pending.
- `Team project sync` is absent from Sentra `main`; reviewed fixes and the release
  must reach `main` before activation. Follow the release/back-merge procedure in
  [CONTRIBUTING.md](../CONTRIBUTING.md#keeping-release-branches-current).
- `PROJECTS_TOKEN` was entered through a masked local prompt and encrypted into this
  repository's Actions secrets. Its `project` scope and authenticated read access
  were verified; it expires November 14, 2026. No plaintext token was logged or saved.
- `TEAM_PROJECT_ID=PVT_kwHOC_Gyqs4BnAWo` and `TEAM_SYNC_ENABLED=false`
  were read back from Actions variables. A workflow dry run and credentialed write
  test remain pending until reviewed follow-up code reaches `main`.
- GitHub approval and merge notifications were observed in this channel on October
  15. Draft/change-request/fix delivery, replay behavior and duplicate suppression
  remain part of the human pilot.
- `SENTRA_COLLECTION_ENABLED=false` was verified and left unchanged.
- `workflow-maintenance` and `release` labels now exist. The owner confirmed
  `mhmdaboulhoda` may grant independent exemptions; CODEOWNERS remain unchanged.

## Pilot

Use the rollout tracking issue and a synthetic/test-only PR. Open a draft, ready it,
request a human review, request a change, push a fix and re-review the latest head.
Observe In progress → In review → Changes requested → In review. Merge only after an
actual teammate approval and required checks. Observe Implemented; the teammate then
records acceptance, sets Done and closes the issue. Replay/reconcile and verify no
incorrect transition or duplicate notification. Preserve the same branch flow and
Sentra collection pause throughout.

## References

- [GitHub Projects API](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects)
- [Project automation authentication](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/automating-projects-using-actions)
- [GitHub Wiki editing](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages)
- [GitHub Slack notifications](https://docs.github.com/en/integrations/how-tos/slack/customize-notifications)
