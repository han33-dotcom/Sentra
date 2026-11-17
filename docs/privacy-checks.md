# Privacy checks on the hosted viewer

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). The same access and withdrawal
rules that `tests/test_privacy_matrix.py` checks automatically, written as steps to run on the
deployed viewer after a release. Results go in the table at the end and feed the Real/hosted
column of the [evaluation table](evaluation.md).

## Rules

- Never use real participant data for these checks; use synthetic organizations and fixtures.
  Do not promote a participant account merely for testing. A person may legitimately be both
  an officer and a participant: organization authorization and participation/consent are separate.
- No screenshots of real data, names or emails in GitHub. Record only pass/fail, the date, the
  released commit and short notes.
- Keep collection paused. Limit note creation and consent changes to the approved synthetic fixture.

## Setup (operator, private)

1. Release and deploy the code under test; note the commit from the hosted app.
2. In a synthetic organization, prepare six consenting synthetic participants with published
   board days: two `individual` (A and B), four `group_only`, plus one `individual` in a second
   synthetic organization. Checks 6 and 7 each use their own participant, so they start
   independently.
3. Prepare either separate Google accounts for officer/reviewer in the first organization,
   officer in the second and no role, or one explicitly designated account rotated through
   those states using the sequential procedure below. Ensure the test identity can reach
   Sentra through private hosting, but keep it out of the team/operator allowlist (which takes
   precedence over organization roles). Hosting access alone must not grant application access.
4. Set up Follow-ups using [migration 010 and the private write role](follow-ups.md).
   As each synthetic organization’s officer, record distinct notes for its individually sharing
   participants and one group follow-up. Add an update to each individual follow-up so its history
   has a different note from the current state. Keep note markers free of names, account details
   and participant IDs.

## Sequential account procedure

One designated Google identity is sufficient for sequential role checks; it does not test
concurrent sessions belonging to different people. The owner authorized this method on
November 17, 2026. Keep the real test email and configuration only in private operator evidence.

1. Record the identity's starting roles. Prefer an identity with no existing application access;
   never overwrite unrelated roles. Use two approved synthetic organizations only.
2. Verify no-role denial. Activate exactly one organization/role at a time: first-organization
   officer, first-organization reviewer, second-organization officer, then inactive. Change
   only the approved fixture rows, retaining collection and egress guards.
3. Give each organization distinct synthetic group notes. Include a note assigned to the test
   identity and one assigned to a synthetic reserved-domain assignee. The latter needs no
   Google account. Verify officer creation/update, reviewer update of their assigned note,
   absence of reviewer creation/unassigned update controls, and cross-organization note/history
   exclusion. Database rejection tests complement controls hidden by the UI.
4. Check transitions on the next render in the existing session to exercise caches; also sign
   out/in to check a fresh authenticated session. Deactivation must remove access and cached
   private content. Sign-out must leave no private tables or embedded board.
5. Restore initial access, deactivate temporary assignees, and resolve synthetic group notes
   through the controlled function. Preserve append-only history; do not delete audit records.
   Record the tested commit, states, results, cleanup and any limits without account details.

The complete matrix below requires a separately published synthetic board and synthetic
participants. Never replace or mix the live participant board merely to run these checks.
On the live viewer with empty synthetic organizations, limit checks to denial, role controls,
group follow-ups, organization switching and sign-out. Run individual-sharing, withdrawal,
group-threshold and all-page cases against an isolated synthetic deployment or automated
fixtures; record those separately from hosted results.

## Checks

| # | Signed in as | Do | Expected |
| --- | --- | --- | --- |
| 1 | No-role account | Sign in | "Access restricted"; no data, tables or participant IDs on any page |
| 2 | Officer, org 1 | Open every page in the sidebar | Only A and B appear on individual views. Follow-ups shows A and B’s notes and history plus the org 1 group note. Other organizations’ IDs and note text are absent |
| 3 | Reviewer, org 1 | Same as 2 | Same as 2 |
| 4 | Officer, org 2 | Open every page | Only org 2’s individual participant and permitted Follow-ups notes appear. Org 1’s IDs, notes and history are absent |
| 5 | Officer, org 1 | Organization overview | Statistics with 5 contributors show values; smaller ones show "Not shown" and "<5"; no count from 1 to 4 appears |
| 6 | Operator | Confirm the org 1 officer sees A; then record A's withdrawal (enrollment page) | On the next render, A’s individual details and follow-up notes and history are absent, including in All and Resolved. B and the group follow-up remain visible to the org 1 officer |
| 7 | Operator | Confirm the org 1 officer sees B individually; then change B's sharing to `group_only` | On the next render, B’s individual details and follow-up notes and history are absent, including in All and Resolved. B still counts toward eligible group statistics |
| 8 | Operator | Deactivate the org 1 officer in `org.org_users` | On the next click: "Access restricted" |
| 9 | Officer, org 1 | Sign out | Back to the sign-in page; no data tables or embedded board remain |
| 10 | Any | Check the published board download, if offered | Only pseudonyms; no names, emails, provider IDs or location |

Include both Trends views and Follow-ups in checks 2–4 and 6–7. Add Reports when released.
To repeat the checks, reset the synthetic fixture with new participants A and B, individual
sharing, fresh synthetic Follow-ups notes and an active org 1 officer.

## Results

| Date | Released commit | Checks run | Result | Notes | Checked by |
| --- | --- | --- | --- | --- | --- |
| 2026-11-17 | `9b6e8c048b49f04a89839024cc64e06b3c586506` | Sequential no-role, officer/reviewer, second organization, inactive and sign-out; group notes only | Passed within this scope | Hosted creation, open/ongoing/resolved updates, history, assigned-only reviewer controls, fresh reviewer login, organization isolation and denial verified. Four synthetic group notes resolved; temporary roles disabled; zero fixture participant memberships. | Implementation agent, owner-authorized identity |

This hosted run used two empty synthetic organizations. Three group notes were seeded through
the controlled database functions; the fourth was created through the hosted officer form.
The hosted writer initially reported missing configuration; after the owner saved the private
fragment, hosted creation and officer/reviewer updates succeeded. No real participant record,
consent, published wellness board or collection control was changed. Private role/cleanup receipts
recorded less than 29 MB of additional egress reservations against a 100 MB session cap.

Individual withdrawal/sharing, group thresholds and the complete page matrix remain synthetic
automated evidence, not claims of this hosted run. The PostgreSQL follow-up/access tests passed
(16 tests). The new sequential-identity AppTest retains one session while changing role and
organization, verifies assigned-only reviewer updates, and verifies cache removal on deactivation.
