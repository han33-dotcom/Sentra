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
| Team operator (viewer allowlist) | Participants with current consent, plus pilot participants with data but no consent record; withdrawn or closed consent is excluded | All participants |
| Organization officer or reviewer | Their organization: current, non-withdrawn consent in an open membership (`group_only` or `individual`) | Only `individual` sharing |
| Anyone else | Denied | Denied |

`group_only` participants contribute to group statistics but never appear individually.
The reader keeps the two scopes apart: `group_catalog()` and `group_board()` serve totals
only, while `catalog()` and `board()` stay limited to individual sharing.

## Participation

Counted separately. One state never implies the next.

| State | Meaning |
| --- | --- |
| Enrolled | Current consent in an open membership episode |
| Connected | At least one wearable connection with `authorization_status = authorized` |
| Recently contributing | Latest measurement day within the last 3 days (measurement dates, not collection success) |
| Assessable | The latest published day is within the last 3 days and has a complete assessment under the current versioned board contract (`a` absent and `lvl` green/amber/red) |

The 3-day window is a proposal for team agreement. Organization users see connected, recently
contributing and assessable counts below 5 only as "<5", so a group-only person's activity on a
given day cannot be singled out.
Partial amber/red, insufficient, stale, future and legacy unversioned days do not count as
assessable. This consumes the [indicator contract](indicator-contract.md), rather than
inferring completeness from a baseline.

## Group summary

For the latest published day or the last 7 published days ending there:
- each contributing person gives one value: the median of their available days in the period;
- the group value is the median of those per-person values, **separately per device**: Fitbit and
  WHOOP measure HRV, resting heart rate and sleep differently, so they are never pooled
  (see [medical evidence](medical-evidence.md));
- **each statistic needs at least 5 contributors of its own** (`cohort_k_anonymity`).
  Otherwise it shows "Not shown", the count only as "<5", and the reason. With no
  contributor it says so. Missing values are never filled.
- The threshold is `cohort_k_anonymity` in `processing/thresholds.json`, the same value the
  processing pipeline's cohort statistics use.

These organization- and device-scoped period medians are computed from the board's displayed
precision. They are distinct from the pipeline's global daily cohort output; using a global
cohort here would include people outside the officer's permitted organization.

Measures: sleep (minutes), resting heart rate (bpm), heart rate variability (ms), steps,
and WHOOP recovery (%). With today's two participants, every real group statistic is
correctly hidden.

## Profiles

For one permitted participant: device, latest published day and its age, days with data
in the last 7 (days with a malformed date are skipped), and for each measure the latest value, their own baseline (previous 28
days, at least 7 days) and the difference. "Not supplied" and "Not enough history for a
personal baseline yet" are explicit.

## Limitations

- Profiles show measured values and personal baselines; the overview's assessment availability
  uses the current complete-assessment contract. Detailed rule explanations remain follow-up work.
- Data comes from the published wellness board, so it is only as current as the latest
  daily refresh. Collection remains paused.
- Organization users need, privately: migration 007 applied, an `org.org_users` row and
  access to the Streamlit app's private sharing list.
- Trends over longer periods (#40), explanations (#41) and reports (#42) build on these
  pages.
