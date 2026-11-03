# Trends

Task: [#40](https://github.com/han33-dotcom/Sentra/issues/40). The **Trends** page in the
private viewer shows how one measure changes over the last 7, 14 or 28 published days. It
follows the same access rules as the [organization overview](organization-overview.md).
Everything shown is wellness information compared with each person's own pattern, not a
medical assessment.

## Views

| View | Who appears | What it shows |
| --- | --- | --- |
| One person | Only people who chose `individual` sharing (team: everyone) | Daily readings, the person's own baseline each day, days with data, the period median, the typical difference from their usual value, and how many days met the measure's provisional wellness rule |
| Group | Group contributors (`group_only` and `individual`; team: current consent and pilot participants, never withdrawn) | The daily group median, per device |

Measures: sleep (minutes), resting heart rate (bpm), heart rate variability (ms), steps and
WHOOP recovery (%).

## Definitions

- **Period**: the selected number of calendar days ending on the latest published day
  (for one person, their own latest day). Days are Asia/Beirut civil days.
- **Own baseline**: from the [indicator contract](indicator-contract.md), published on the
  board: the median of the previous 28 days, needing at least 7 days with a reading. It is
  not recomputed here.
- **Typical difference**: the median of daily (reading − own baseline) on days that have both.
- **Days meeting the rule**: the board's own flags (short sleep, resting HR above normal,
  HRV below normal). Rules are provisional until the medical expert signs them off.
- **Group median**: one value per contributing person that day, then the median, separately
  for Fitbit and WHOOP, which are never pooled.

## Gaps and small groups

- A day without a reading stays an empty position on the date axis. Nothing is filled or
  interpolated.
- **Each group day needs at least 5 contributors of its own** (`cohort_k_anonymity` in
  `processing/thresholds.json`). Smaller days are left out. Counts below 5 show only as "<5".

## Limitations

- Department comparisons are not available: the organization schema has no departments yet.
  Per the November 3 sequencing, elaborate group comparisons are deferrable.
- Only measures published on the wellness board are covered.
- Data is only as current as the daily board refresh. Collection remains paused.
- With today's two participants, every real group day is correctly hidden.
