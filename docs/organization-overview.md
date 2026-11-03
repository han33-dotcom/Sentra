# Organization overview and profiles

Task: [#39](https://github.com/han33-dotcom/Sentra/issues/39). Two pages in the private
viewer for a health and safety officer: **Organization overview** and **Profiles**. They
follow [participation permissions](participation-permissions.md) and the access rules in
[schema](schema.md).
Everything shown is wellness information compared with each person's own pattern, not a
medical assessment.

## Who sees what

| Signed-in user | Overview counts and group statistics | Profiles |
| --- | --- | --- |
| Team operator (viewer allowlist) | All participants | All participants |
| Organization officer or reviewer | Their organization: current, non-withdrawn consent in an open membership (`group_only` or `individual`) | Only `individual` sharing |
| Anyone else | Denied | Denied |

`group_only` participants contribute to group statistics but never appear individually.
The reader keeps the two scopes apart: `group_catalog()` and `group_board()` serve totals
only, while `catalog()` and `board()` stay limited to individual sharing.

## Participation

Counted separately. One state never implies the next.

| State | Meaning |
| --- | --- |
| Enrolled | Current consent in an open membership episode (team: every participant in the catalog) |
| Connected | At least one wearable connection with `authorization_status = authorized` |
| Recently contributing | Latest measurement day within the last 3 days (measurement dates, not collection success) |
| Assessable | The latest published day has at least one personal baseline (sleep, resting HR, HRV or steps) |

The 3-day window is a proposal for team agreement.

## Group summary

For the latest published day or the last 7 published days ending there:
- each contributing person gives one value: the median of their available days in the period;
- the group value is the median of those per-person values;
- **each statistic needs at least 5 contributors of its own** (`cohort_k_anonymity`).
  Otherwise it shows "Not shown" with the contributor count and the reason. With no
  contributor it says so. Missing values are never filled.

Measures: sleep (minutes), resting heart rate (bpm), heart rate variability (ms), steps,
and WHOOP recovery (%). With today's two participants, every real group statistic is
correctly hidden.

## Profiles

For one permitted participant: device, latest published day and its age, days with data
in the last 7, and for each measure the latest value, their own baseline (previous 28
days, at least 7 days) and the difference. "Not supplied" and "Not enough history for a
personal baseline yet" are explicit.

## Limitations

- Assessment levels (green/amber/red) are **not shown yet**. The board's day level can look
  reassuring when inputs are missing until the incomplete-assessment contract (#45, #49)
  is released. These pages will then show its states and reasons instead.
- Data comes from the published wellness board, so it is only as current as the latest
  daily refresh. Collection remains paused.
- Organization users need, privately: migration 007 applied, an `org.org_users` row and
  access to the Streamlit app's private sharing list.
- Trends over longer periods (#40), explanations (#41) and reports (#42) build on these
  pages.
