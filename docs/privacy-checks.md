# Privacy checks on the hosted viewer

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). The same access and withdrawal
rules that `tests/test_privacy_matrix.py` checks automatically, written as steps to run on the
deployed viewer after a release. Results go in the table at the end and feed the Real/hosted
column of the [evaluation table](evaluation.md).

## Rules

- Never use real participants for these checks; use the synthetic test organization and accounts.
  Participant accounts must never be given officer or viewer access for testing.
- No screenshots of real data, names or emails in GitHub. Record only pass/fail, the date, the
  released commit and short notes.
- Keep collection paused. Limit note creation and consent changes to the approved synthetic fixture.

## Setup (operator, private)

1. Release and deploy the code under test; note the commit from the hosted app.
2. In a synthetic organization, prepare six consenting synthetic participants with published
   board days: two `individual` (A and B), four `group_only`, plus one `individual` in a second
   synthetic organization. Checks 6 and 7 each use their own participant, so they start
   independently.
3. Prepare four Google accounts: an officer and a reviewer of the first organization, an officer
   of the second, and one account with no role. Add the first three to `org.org_users`. Add **all
   four** to the Streamlit app's private sharing list, so the no-role account reaches Sentra's own
   check; keep it out of `org.org_users` and the operator allowlist.
4. Set up Follow-ups using [migration 010 and the private write role](follow-ups.md).
   As each synthetic organization’s officer, record distinct notes for its individually sharing
   participants and one group follow-up. Add an update to each individual follow-up so its history
   has a different note from the current state. Keep note markers free of names, account details
   and participant IDs.

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
| | | | | | |
