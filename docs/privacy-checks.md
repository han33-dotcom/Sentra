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
- Collection stays paused; these checks only read.

## Setup (operator, private)

1. Release and deploy the code under test; note the commit from the hosted app.
2. In a synthetic organization, prepare five consenting synthetic participants with published
   board days: one `individual`, four `group_only`, plus one `individual` in a second synthetic
   organization.
3. Prepare four Google accounts: an officer and a reviewer of the first organization, an officer
   of the second, and one account with no role. Add the first three to `org.org_users` and to the
   Streamlit app's private sharing list.

## Checks

| # | Signed in as | Do | Expected |
| --- | --- | --- | --- |
| 1 | No-role account | Sign in | "Access restricted"; no data, tables or participant IDs on any page |
| 2 | Officer, org 1 | Open every page in the sidebar | Only the `individual` participant appears individually; no `group_only` or org 2 ID anywhere, including the wellness board and selection lists |
| 3 | Reviewer, org 1 | Same as 2 | Same as 2 |
| 4 | Officer, org 2 | Open every page | Only org 2's `individual` participant; nothing from org 1 |
| 5 | Officer, org 1 | Organization overview | Statistics with 5 contributors show values; smaller ones show "Not shown" and "<5"; no count from 1 to 4 appears |
| 6 | Operator | Record a withdrawal for the org 1 `individual` participant (enrollment page) | Officer of org 1, on the next click: the participant is gone from every page |
| 7 | Operator | Change a participant's sharing to `group_only` | On the next click: individual details gone from every page; still counted in group statistics |
| 8 | Operator | Deactivate the org 1 officer in `org.org_users` | On the next click: "Access restricted" |
| 9 | Officer, org 1 | Sign out | Back to the sign-in page; no data tables or embedded board remain |
| 10 | Any | Check the published board download, if offered | Only pseudonyms; no names, emails, provider IDs or location |

Pages added later (Trends, Follow-ups, Reports) join checks 2–4 and 6–7 when they are released.

## Results

| Date | Released commit | Checks run | Result | Notes | Checked by |
| --- | --- | --- | --- | --- | --- |
| | | | | | |
