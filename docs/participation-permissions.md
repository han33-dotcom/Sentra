# Participation permissions and approval readiness

Status: **team approved**, reported by the project owner on November 18, 2026
(task [#26](https://github.com/han33-dotcom/Sentra/issues/26)). On the same date,
the owner removed the advisor-review outcome from the sprint scope. It is not an
acceptance, enrollment or collection-restart gate. Existing participants retain
their current agreement until they confirm this version; each new participant
must make their own consent and sharing choices.

This document defines what a participant agrees to, who may see what, and what must
be in place before enrollment. Signed forms, names, contact details and the
pseudonym mapping are kept outside Git, in the team's private store, as before.

## Roles

| Role | Who | Sees |
| --- | --- | --- |
| Participant | Consenting member wearing a supported device | Their own data on request |
| Health and safety officer | Authorized organization user | Group results; individual details only within each participant's sharing choice |
| Follow-up reviewer | Officer assigned to a follow-up | The follow-up and the data it refers to, within the same limits |
| Sentra operator | Team member running collection and storage | Everything needed to operate, audit and recover the system |

Officers and reviewers belong to one organization and see only that organization's
participants. Operator access stays limited to the existing team accounts.

## Data categories

**Collected** (unchanged, see the [data dictionary](data-dictionary.md)):

| Category | Fitbit / Google Health | WHOOP |
| --- | --- | --- |
| Activity | Steps, distance, calories, active and sedentary minutes, exercise sessions | Workouts, strain |
| Heart | Heart rate at original API resolution (initial import, kept in the 30-day `hr_raw` tier), minute rollups and daily summaries; resting HR, HRV | Recovery, resting HR, HRV |
| Sleep | Sleep sessions and stages, respiratory rate, sleep temperature | Sleep sessions, stage totals, performance |
| Other physiology | SpO2, VO2 max where returned | SpO2, skin temperature where returned |

All values are readings and summaries returned by the provider APIs, not raw
physical sensor signals.

**Derived:** daily features, 28-day personal baselines, provisional wellness
indicators and k-anonymous group statistics ([processing](processing.md)).

**Never included in wellness records, organization views or exports:**
- location, GPS routes or maps;
- provider account identifiers, display names and free-text notes (already removed
  from normalized records by `normalize.IDENTITY_FIELDS`);
- credentials and tokens outside the encrypted collector store;
- contacts, messages or any data unrelated to the categories above.

Original provider responses are kept privately and unchanged for audit, and can
contain identifying fields. Only Sentra operators can open them; organization users
cannot.

For [self-service enrollment](self-service-enrollment.md), Sentra privately checks
the provider's stable account identifier to recognize returning participants and
prevent duplicate or incorrect account linking. Google uses `openid`; WHOOP uses
`read:profile`. Only a provider-specific keyed hash is retained for this purpose.
Names and email addresses also returned by WHOOP are discarded immediately.
Provider passwords remain with the provider. This identity check is separate from
the wearable dataset and is described on the joining page.

## Sharing choices

Each participant chooses one sharing level, recorded with its date and the consent
version:

| Level | Organization users see |
| --- | --- |
| `group_only` (default) | Nothing individual. The participant only contributes to group statistics, which are published only when each statistic has at least 5 eligible contributors. |
| `individual` | Their pseudonymous profile, trends, indicators and follow-ups, plus group statistics. |

Participants can also agree separately to:
- **Demonstration use:** their pseudonymous real data may appear in internal
  project demonstrations. No real-data screenshots go into public material.
- **Named recipients:** the organization and officer roles listed in their consent.
  Adding a new recipient organization needs fresh consent.

Changing the sharing level takes effect from the next page load. Earlier reports
already shared are not recalled; the change is recorded.

## Withdrawal

A participant can withdraw at any time, without giving a reason:
1. Collection for them stops, and their provider authorization is revoked or left to expire.
2. They disappear from organization views and new reports immediately, and stop
   counting towards group statistics from the withdrawal date.
3. Their stored data is kept or deleted according to the agreed retention policy
   ([#29](https://github.com/han33-dotcom/Sentra/issues/29)). Nothing is deleted
   automatically, and backups follow the same decision.

## Before enrolling anyone

| Check | Owner | Status |
| --- | --- | --- |
| Team agrees this document | All | Approved, as reported by the owner November 18 |
| Consent form produced from this document and kept privately | Aboulhoda | Pending |
| Participant added as a Google OAuth test user (Fitbit) | Collection owner | Per participant |
| WHOOP member count stays within the development limit | Collection owner | Per participant |
| Pseudonym assigned (`p03` …), mapping stored privately | Operator | Per participant |

## Provider limits

| Provider | Limit | Effect on the five-participant target |
| --- | --- | --- |
| Google Health (OAuth app in **Testing**) | Up to 100 test users; each must be added before authorizing. Authorizations and refresh tokens **expire 7 days after consent**. | Each Fitbit participant must reconnect weekly while the app stays in Testing. Switching to **In production** is separate from verification: an unverified app still shows a warning and keeps a lifetime user cap, in Testing or production. Whether verification is required, or this pilot qualifies for an exception (for example, a few personally known users), must be checked and recorded before choosing between weekly reconnects and publication. |
| WHOOP (app not yet approved) | Up to **10 WHOOP members** in development. Approval requires a working app, contact email and privacy policy URL; review times are not guaranteed. | Five participants fit within the limit. Approval is not needed this sprint. |

The Google reconnect question is shared with the collection restart task, which
decides between weekly assisted reconnects and pursuing publication. Sources:
[Google OAuth audience and testing](https://support.google.com/cloud/answer/15549945),
[restricted-scope verification exceptions](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification#exceptions),
[Google Health API setup](https://developers.google.com/health/setup),
[WHOOP app approval](https://developer.whoop.com/docs/developing/app-approval).

## November 18 sprint scope correction

The review-route requirement originated in the initial document in
[PR #33](https://github.com/han33-dotcom/Sentra/pull/33), merged November 3.
The owner's November 18 instruction supersedes that sprint requirement. Historical
issue comments and PR descriptions retain their original context. Team agreement,
participant-specific consent, access boundaries, provider setup, public-policy
publication and explicit operational authorization continue to govern their own steps.

Provider-console observations on November 18 confirmed Google External / Testing
with 2 of 100 test users and WHOOP Sandbox with 1 of 10 members. WHOOP's registered
redirects now include localhost and the owner-authorized hosted callback, with the
existing read-only scopes preserved. Actual rates are 100 requests/minute and
10,000/day. See [readiness evidence](collection-restart-readiness.md#november-18-provider-console-readback).
