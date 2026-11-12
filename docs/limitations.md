# Known limitations

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). One consolidated list, collected
from the limitations recorded in each merged PR and the reviewed documents. Each item links its
source; owners keep their own items current. See also the [evaluation table](evaluation.md).

Last updated: November 12, 2026, from `develop` at `464222e`.

## Meaning of the results

- **Wellness, not medical.** Every indicator compares a person with their own recent pattern.
  Nothing is a diagnosis or a medical assessment ([indicator contract](indicator-contract.md)).
- **Provisional thresholds.** All rule values are v0, pending the medical expert's sign-off. Some
  rules are weakly supported (sustained high heart rate uses `180 − age` and a default age of 30;
  long inactivity uses a hardcoded 08:00–18:00 shift window). See
  [medical evidence](medical-evidence.md). (#56)
- **Devices measure differently.** Fitbit and WHOOP define HRV, resting heart rate and sleep
  differently. The organization overview reports devices separately, and baselines are personal.
  Device separation in the cohort API is still in review. (#56, #62, #79)
- **Rounded evidence.** The board publishes rounded values; rules run on the unrounded readings, and
  observations say so. Group medians use board display precision. (#62, #65)
- **Only some rules are explained.** Sustained high heart rate and long inactivity flags are not on
  the published board, so the observations page does not explain them. (#65)

## Privacy and access

- **k = 5 is a policy choice.** Small-group protection uses at least 5 contributors per statistic;
  the privacy review may ask for a stricter value. (#56)
- **Identity comes from the viewer.** Organization access relies on the viewer's verified Google
  sign-in and on the hosted app protecting its secrets.
- **Team operators keep operator access**, including to withdrawn participants' stored data, for
  operations and retention; organization views exclude them. (#51)
- **Officers and reviewers share the organization’s read scope.** Follow-up writes also
  depend on the active officer or assignee role. The operator can read closed history after
  sharing ends. (#51, #55, #72)
- **The read API is a team operator credential** with no organization users. (#55)
- **Data already delivered cannot be recalled.** Permission changes and withdrawals apply on the
  next render, but earlier downloads and exports stay with their recipient. (#64)
- **Real organization users need hosting setup:** migration 007 applied, an `org.org_users` row,
  and the Streamlit app's private sharing list. (#55)
- **Participation document is a draft** until the team agrees it and the advisor confirms the
  review route. (#33)

## Enrollment and collection

- **Collection is paused.** Merging or deploying never restarts it; restart needs explicit
  authorization and readiness evidence. (#53)
- **Provider limits.** Google Testing mode means weekly Fitbit reconnects. WHOOP is limited to 10
  members in development and is disabled on the host until its developer app registers the hosted
  callback. (#33, #64)
- **Real-phone evidence is partial.** One real Google signup and a sharing update are recorded;
  phone timing, reconnect and withdrawal on real devices, and hosted organization-user acceptance
  are outstanding. (#52, #64)
- **Assessment eligibility is not fed to enrollment.** The participant page shows assessment as
  unavailable rather than guessing. (#52, #64)
- **Free hosting.** The enrollment host can take tens of seconds to wake, and an inactive Free
  database can pause again. (#36, #64)
- **Provider-side settings are unverified.** Stored token metadata cannot prove provider-side
  authorization; the Google Audience page did not load and WHOOP needs sign-in. (#53)

## Storage, backup and recovery

- **Retention periods are proposals.** The team, advisor and IRB decide them; no expiry is
  implemented. (#58, [retention policy](retention-policy.md))
- **Supabase's own backups remain unverified.** The full backup and isolated restore have
  synthetic evidence. A fresh shared backup and the operator rehearsal remain pending. Apply
  migration 010 to a rehearsal target if the archive contains follow-up tables. (#58, #67)
- **Compact storage is extra space for now.** Removing the per-field rows (phase 3) stays gated on
  the retention policy, a verified backup, the recovery rehearsal and both owners' approval. (#59)
- **Publishing keeps two tier slots.** Tiers can be one run ahead of the board after an
  interrupted upload. The next successful refresh repairs the board. Old root objects remain
  until an admin removes them. (#57, #80)
- **Growth forecast pending.** The next-batch recommendation needs enough days of collection;
  egress comparisons are only valid within one month. (#60)

## Organization application

- **Small pilot means hidden statistics.** With today's participants, every real group statistic
  is correctly hidden.
- **The 3-day "recently contributing" window** is a proposal for team agreement. (#62)
- **Only the latest published day is explained** on Profiles; trends and reports are separate
  tasks. (#65)
- **Data is only as current as the daily board refresh.**
- **Reports are Markdown only, with no record of who prepared or downloaded one.** Follow-up
  counts cover the latest 50. The demonstration copy uses only people who agreed, also in group
  figures, pending the team's review. ([reports](reports.md))
- **Follow-ups need hosted setup and acceptance.** Apply migration 010, configure the private
  follow-up write role and run the hosted privacy checks with synthetic accounts. (#72)
