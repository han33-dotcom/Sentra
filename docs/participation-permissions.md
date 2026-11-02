# Participation permissions and approval readiness

Status: **draft for team and advisor review** (task
[#26](https://github.com/han33-dotcom/Sentra/issues/26)). No new participant is
enrolled under this document until the team agrees it and the advisor confirms the
review route below. Existing participants `p01` and `p02` keep their current
agreement until they confirm this version.

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
| Heart | Heart rate (minute rollups), resting HR, HRV | Recovery, resting HR, HRV |
| Sleep | Sleep sessions and stages, respiratory rate, sleep temperature | Sleep sessions, stage totals, performance |
| Other physiology | SpO2, VO2 max where returned | SpO2, skin temperature where returned |

**Derived:** daily features, 28-day personal baselines, provisional wellness
indicators and k-anonymous group statistics ([processing](processing.md)).

**Never collected, shown or exported:**
- location, GPS routes or maps;
- provider account identifiers, display names and free-text notes (already removed
  from normalized records by `normalize.IDENTITY_FIELDS`);
- credentials and tokens outside the encrypted collector store;
- contacts, messages or any data unrelated to the categories above.

Original provider responses are kept privately and unchanged for audit, and can
contain identifying fields. Only Sentra operators can open them; organization users
cannot.

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
| Team agrees this document | All | Pending |
| Advisor confirms the review route (institutional review board or exemption) and any required consent wording | Aboulhoda with the advisor | Pending |
| Consent form produced from this document and kept privately | Aboulhoda | Pending |
| Participant added as a Google OAuth test user (Fitbit) | Collection owner | Per participant |
| WHOOP member count stays within the development limit | Collection owner | Per participant |
| Pseudonym assigned (`p03` …), mapping stored privately | Operator | Per participant |

## Provider limits

| Provider | Limit | Effect on the five-participant target |
| --- | --- | --- |
| Google Health (OAuth app in **Testing**) | Up to 100 test users; each must be added before authorizing. Authorizations and refresh tokens **expire 7 days after consent**. | Each Fitbit participant must reconnect weekly while the app stays in Testing. Publishing requires Google's review of the health scopes; unverified apps show a warning and have a lifetime user cap. |
| WHOOP (app not yet approved) | Up to **10 WHOOP members** in development. Approval requires a working app, contact email and privacy policy URL; review times are not guaranteed. | Five participants fit within the limit. Approval is not needed this sprint. |

The Google reconnect question is shared with the collection restart task, which
decides between weekly assisted reconnects and pursuing publication. Sources:
[Google OAuth testing and verification](https://support.google.com/cloud/answer/15549945),
[WHOOP app approval](https://developer.whoop.com/docs/developing/app-approval).

## Questions for the advisor

1. Does this pilot need institutional review board approval or an exemption, given
   that it involves employees, health-related wearable data and an employer-side
   viewer?
2. Is the consent wording sufficient for organization users to view individual
   details at the `individual` level?
3. Which retention period should apply after the project ends?
