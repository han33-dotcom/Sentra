# Trends

Task: [#40](https://github.com/han33-dotcom/Sentra/issues/40). The **Trends** page in the
private viewer shows how one measure changes over the last 7, 14 or 28 published days. It
follows the same access rules as the [organization overview](organization-overview.md).
Everything shown is wellness information compared with each person's own pattern, not a
medical assessment.

## Views

| View | Who appears | What it shows |
| --- | --- | --- |
| One person | Only people who chose `individual` sharing (team: everyone) | Daily readings, the person's own baseline each day, days with data, the period median, the typical difference from their usual value, and on how many days the measure's provisional rule was checked and met |
| Group | Group contributors (`group_only` and `individual`; team: current consent and pilot participants, never withdrawn) | The daily group median, per device |

Measures: sleep (minutes), resting heart rate (bpm), heart rate variability (ms), steps and
WHOOP recovery (%).

## Definitions

- **Period**: the selected number of calendar days ending on the latest published day. For one
  person, that is their own latest day. For an organization's group view, it is the latest day
  with at least one statistic that can be shown, so a suppressed reading never moves the window;
  "no readings" and "all hidden" also look the same to organization users. Days are
  Asia/Beirut civil days.
- **Own baseline**: from the [indicator contract](indicator-contract.md), published on the
  board: the median of the previous 28 days, needing at least 7 days with a reading. It is
  not recomputed here.
- **Typical difference**: the median of daily (reading − own baseline) on days that have both.
- **Rule state per day**, from the board only: *met* (its flag), *not checked* (a published reason
  such as `rhr:baseline_building` or `no_reading`), *checked, not met*, or *no data*. A missing
  flag alone never counts as calm. If no day was checked the page says "Not enough information";
  boards from older rules show no rule results. Rules are provisional until the medical expert
  signs them off.
- **Group median**: one value per contributing person that day, then the median, separately
  for Fitbit and WHOOP, which are never pooled. Unknown devices are left out.

## Gaps and small groups

- A day without a reading stays an empty position on the date axis. Nothing is filled or
  interpolated.
- **Each group day needs at least 5 contributors of its own** (`cohort_k_anonymity` in
  `processing/thresholds.json`). Smaller days are left out and their counts are not returned.
- Organization users see only devices that reach 5 contributors on some day, and no hidden-day
  counts, so a small group's (or one person's) wear pattern cannot be read off the table. Team
  operators keep the per-device detail.

## Limitations

- Department comparisons are not available: the organization schema has no departments yet.
  Per the November 3 sequencing, elaborate group comparisons are deferrable.
- Only measures published on the wellness board are covered.
- Data is only as current as the daily board refresh. Collection remains paused.
- With today's two participants, every real group day is correctly hidden.
