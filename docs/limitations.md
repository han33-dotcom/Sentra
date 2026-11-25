# Known limitations

Task: [SEN-32](https://github.com/han33-dotcom/Sentra/issues/32). One consolidated list, collected
from the limitations recorded in each merged PR and the reviewed documents. Each item links its
source; owners keep their own items current. See also the [evaluation table](evaluation.md).

Updated November 26, 2026. [November sprint closeout](sprint-closeout.md) · [Evaluation](evaluation.md)

## Meaning of the results

- **Wellness, not medical.** Every indicator compares a person with their own recent pattern.
  Nothing is a diagnosis or a medical assessment ([indicator contract](indicator-contract.md)).
- **Provisional thresholds.** All rule values are v0, pending the medical expert's sign-off. Some
  rules are weakly supported (sustained high heart rate uses `180 − age` and a default age of 30;
  long inactivity uses a hardcoded 08:00–18:00 shift window). See
  [medical evidence](medical-evidence.md). (#56)
- **Devices measure differently.** Fitbit and WHOOP define HRV, resting heart rate and sleep
  differently. The overview, processing and the read API report devices separately, and baselines
  are personal. A participant with readings from both devices counts toward no device statistic.
  (#56, #62, #79)
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
- **Organization API access is opt-in.** Individual expiring bearer credentials use
  current database roles/consent through the shared access module. Operator keys retain
  full operator scope and must never be shared with organization users. The API stays
  loopback-only; no live organization credential or public deployment was provisioned.
  Old processed files need an authorized rebuild before organization cohort requests.
- **Data already delivered cannot be recalled.** Permission changes and withdrawals apply on the
  next render, but earlier downloads and exports stay with their recipient. (#64)
- **Real organization users need hosting setup:** migration 007 applied, an `org.org_users` row,
  and the Streamlit app's private sharing list. (#55)
- **Participation policy is team approved**, as reported November 18. The owner removed the
  advisor-review outcome from sprint scope. The public notice and Google/WHOOP links
  were verified November 18 under SEN-26; participant-specific consent remains required.

## Enrollment and collection

- **Collection is paused.** Merging or deploying never restarts it; restart needs explicit
  authorization and readiness evidence. (#53)
- **Enrollment and renewal.** Hosted sign-in supports Fitbit and WHOOP. Google Testing can require participant-led reconnects. Recheck consent and usable authorization before a future run. [Hosted provider verification](https://github.com/han33-dotcom/Sentra/issues/28#issuecomment-7007700210)
- **Phone evidence.** The accepted Fitbit flow includes a real phone signup. Reconnect and withdrawal have synthetic transaction coverage. Elapsed signup time was optional. [Enrollment acceptance](https://github.com/han33-dotcom/Sentra/issues/28)
- **Assessment needs enough history.** Five Fitbit and four WHOOP contributors had a recent dashboard day. One Fitbit contributor had a complete recent assessment. Absent or stale eligibility remains unknown. [November sprint closeout](sprint-closeout.md)

## Storage, backup and recovery

- **Interim retention has team agreement.** The owner reported agreement on November 18.
  Post-project custody is outside the sprint; no expiry is implemented. The advisor-review
  outcome was removed from sprint scope by the owner.
  (#58, [retention policy](retention-policy.md))
- **Supabase's own backups remain unverified.** The full encrypted application backup
  and isolated hosted restore passed November 18: all 16 table counts/fingerprints and
  220 destination-original hashes matched. Derived-output rebuilding, off-machine
  custody and key-loss recovery were not rehearsed. See the [dated recovery record](recovery-rehearsal.md#record).
- **Bounded storage removal.** One approved removal was verified against all 774 reconstructed readings. Each further removal requires a fresh preview, recovery evidence and approval. The measured 5.1× difference in representation size does not establish reclaimed disk space. [Storage acceptance](https://github.com/han33-dotcom/Sentra/issues/46#issuecomment-6992737541)
- **Publication is ordered, not atomic across board and tiers.** A board upload failure retains its previous complete version; tier hashes force repair on retry. Monthly immutable objects, legacy slots and obsolete versions count against storage until separately reviewed cleanup. Both writer commands share a database lock. (#57, #80, #106)
- **Monthly refresh still does server work.** Source fingerprints scan all logical source rows, and processing downloads the complete bounded compact cache. The builder can reuse unchanged groups within a month. [Refresh accounting](sprint-closeout.md)
- **Refresh is not scheduled.** The November 26 publication used stored readings through November 24. Another refresh requires its own authorization.
- **Compact reads depend on records.** Phase 3 must keep `audit.records`, whose response ID proves
  a compact reading is current. The private viewer now reads current compact-only rows (#98). Compact writes default off (012); deletion uses separately gated previews and actual owner approval comments (#105).
- **Recurring cost remains unmeasured.** The eight-person batch fit within its 60 MB cap. The team stopped at ten contributors. [Capacity measurements](capacity-measurements.md)

## Organization application

- **Small groups.** Each statistic needs at least five eligible contributors per device, date and measure. Demonstration reports also require demonstration consent.
- **The 3-day "recently contributing" window** is a proposal for team agreement. (#62)
- **Only the latest published day is explained** on Profiles; trends and reports are separate
  tasks. (#65)
- **Data is only as current as the daily board refresh.**
- **Reports (Markdown and PDF) keep no record of who prepared or downloaded one.** Follow-up
  counts cover the latest 50. The demonstration copy uses only people who agreed, also in group
  figures, pending the team's review. ([reports](reports.md))
- **Hosted follow-up scope is bounded.** Writer configuration and sequential officer/reviewer
  group-note checks passed November 17 with one designated identity and two empty synthetic
  organizations. Individual consent/withdrawal and the five-contributor hosted matrix still
  need an isolated synthetic fixture. Temporary roles were deactivated. (#72, #111)

- **Recovery does not authorize live deletion.** The November 18
  rollout and one full encrypted backup completed within the authorized 4.5 GB transfer
  and 500 MB private-backup ceilings. See the [dated record](storage-plan.md#rollout-and-verified-backup-observed-november-18).
  The separate hosted recovery also passed within its bounded scope. Team retention
  agreement was subsequently reported, and separately authorized cleanup removed the
  isolated recovery project and its temporary copies. Live destructive approvals,
  exact previews and lossless checks apply to each removal.
