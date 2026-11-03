# Assisted enrollment runbook

Task: [#28](https://github.com/han33-dotcom/Sentra/issues/28). Status: **draft**. Use
it for the first new participants while the enrollment interface is built. It
follows [participation permissions](participation-permissions.md); nothing here
overrides that document's pre-enrollment checks.

Collection remains paused. Enrolling someone never restarts collection; a first
import or ongoing collection needs the collection owner's explicit approval.

## Current limitation

The collector supports **one participant per provider** today (`p01` Fitbit,
`p02` WHOOP): `config/local.toml` has one section per provider and the cloud setup
stores one participant ID per provider. Enrolling a third participant waits for the
multi-participant collector change owned by the collection owner. Steps 1–4 below
can be prepared now; steps 5–7 apply once that change is merged.

## Roles

| Role | Who | Does |
| --- | --- | --- |
| Enrollment operator | Aboulhoda (or a teammate he names) | Runs steps 1–4 and 8, records evidence |
| Collection operator | Collection owner | Runs steps 5–7 on the callback computer |
| Participant | Consenting member | Reads the consent, chooses sharing, signs in to their own provider account |

The operator never asks for, types or sees the participant's provider password.

## 1. Pre-enrollment checks

Confirm every item in the
[before enrolling anyone](participation-permissions.md#before-enrolling-anyone)
table, including the **recorded review outcome**. Stop if any is pending.

## 2. Consent and sharing choice

1. Give the participant the consent form produced from the permissions document.
2. Record privately (outside Git): signed form, date, consent version, sharing level
   (`group_only` by default, or `individual`), demonstration consent yes/no.
3. Assign the next pseudonym (`p03`, `p04` …). Keep the person-to-pseudonym mapping
   only in the team's private store. Never put a name, e-mail or phone number in
   Git, issues, Slack or Sentra tables.

## 3. Organization record

Once [#35](https://github.com/han33-dotcom/Sentra/pull/35) is merged and applied by
the owner, an admin records, in one transaction:
- the pseudonym in `audit.participants`;
- an open membership episode in `org.memberships` (organization, optional team,
  `joined_on`);
- the first row in `org.consents` with the version, sharing level and demonstration
  choice from step 2.

Consent rows are append-only. A mistake is corrected by a new row, never an edit.

## 4. Provider readiness

- **Fitbit / Google Health:** add the participant's Google account as a test user on
  the OAuth consent screen before step 5. In Testing mode their authorization
  expires after seven days, so plan weekly reconnects unless the team chooses
  publication (see the permissions document).
- **WHOOP:** confirm the app stays within its 10-member development limit.

## 5. Connect the device (collection operator)

On the callback computer, in a **private browser window**:
1. Add the participant's section to `config/local.toml` with
   `team_data_agreement = true`, then run `sentra check-config <provider>`.
2. Run `sentra authorize <provider>`. The participant signs in to their own
   account and approves the read-only scopes. Close the window afterwards.
3. Run `sentra cloud-connect <provider>` to hand the encrypted credentials to the
   hosted collector. Never print tokens or provider error bodies.

The exact commands for a second participant on the same provider follow the
multi-participant change and will be updated here when it merges.

## 6. First import (needs collection approval)

With the collection owner's approval, run a bounded `initial` import through
**Actions → Private wearable collection → Run workflow** (see the
[operating guide](operating-guide.md#manual-runs-and-reconnect)). Do not enable
scheduled collection as part of enrollment.

## 7. Verify participation status

Record each state separately; one does not imply the next:

| State | Evidence |
| --- | --- |
| Enrolled | Membership episode open and a current consent row that is not withdrawn |
| Connected | Cloud credentials active; latest collection run for the participant not `denied` or `failed` |
| Recently contributing | Latest measurement day within the last 3 days (measurement dates, not collection success) |
| Assessable | At least 7 usable days in the baseline window, so indicators are not "insufficient history" |

Report counts for each state, never individual values, in shared channels.

## 8. Permission change and withdrawal

- **Sharing change:** append a new `org.consents` row with the new level. Views use
  the latest row; earlier reports already shared are not recalled.
- **Withdrawal:** append a withdrawn consent row, then close the membership episode
  (`left_on`). Ask the collection operator to stop collection for that participant
  and revoke or let the provider authorization expire. The participant disappears
  from organization views immediately. Stored data is kept or deleted only under
  the agreed retention policy ([#29](https://github.com/han33-dotcom/Sentra/issues/29)).
- **Organization change:** withdraw from the old organization, close its episode,
  then open a new episode with fresh consent for the new one.

## Connection problems

Route these to the collection owner with the pseudonym and the state from step 7,
never with tokens, screenshots of provider pages or health values:

| Symptom | Likely cause |
| --- | --- |
| `Reconnect required` or `denied` | Expired Google Testing authorization, revoked access or changed scopes |
| Connected but not contributing | Device not synced or not worn; provider still processing recent days |
| Contributing but not assessable | Fewer than 7 usable baseline days yet |
