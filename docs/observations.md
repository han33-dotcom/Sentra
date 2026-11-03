# Observations

Task: [#41](https://github.com/han33-dotcom/Sentra/issues/41). The **Observations** section on
the Profiles page explains a permitted participant's latest published day. It appears only
for people the signed-in user may see individually ([organization overview](organization-overview.md));
`group_only` participants never get one.

Observations consume the [indicator contract](indicator-contract.md) and the published board.
They do not re-derive any rule: signals come from the board's flags, assessment limits from its
`a`/`m` fields, and the wording repeats the contract's plain wording (`src/sentra/observations.py`).

## Kinds

Kept separate so a data problem is never read as a wellness change, and neither as a medical one.

| Kind | Shown when | Example |
| --- | --- | --- |
| Wellness observation | A rule signalled, or all core rules (sleep, resting HR, HRV) were checked and none signalled | "Resting heart rate above your normal" with this day's value, the person's usual value and the difference in usual variation |
| Assessment limits | The day is `partial` or `insufficient` | "Partial assessment" with every rule that was not checked and why (no reading; personal normal still building) |
| Data collection | No published days; latest day more than 3 days old; a board published under older rules; a level the page cannot explain | "No recent data: the latest published day is 15 days old" |

Rules:
- missing data never produces "No change from usual pattern";
- every wellness observation is labelled provisional while the thresholds await the medical
  expert's sign-off (`thresholds.json` `_status`), and says it is not a medical conclusion;
- a board without the current `assessment_version` shows no observation from its levels;
- an amber or red day is never left unexplained.

## Limitations

- Only the latest published day is explained; trends over time are #40.
- Sustained high heart rate and long inactivity flags are not on the published board, so they
  are not explained here.
- Data is only as current as the daily board refresh. Collection remains paused.
