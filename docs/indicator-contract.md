# Indicator and assessment contract

Status: **v0, provisional — pending medical expert sign-off.** This is the shared definition
of what each wellness indicator means. Processing, the wellness board, the read API, reports
and group statistics all use these names, states and counts; consumers must not re-derive
them. Supporting literature and the open questions for the expert are in
[medical-evidence.md](medical-evidence.md). Threshold values live in
[`thresholds.json`](../src/sentra/processing/thresholds.json) and are not changed by this
document; changing them needs the project's expert approval.

Outputs are wellness / fitness-for-shift observations relative to a person's own recent
pattern. They are not medical assessments and must never be presented as a diagnosis.

## Personal baseline

| Item | Value |
| --- | --- |
| Window | the previous 28 calendar days; today is never part of its own baseline |
| Minimum history | 7 days with a reading inside the window; otherwise no baseline |
| Centre | median of those days |
| Spread | MAD × 1.4826, floored per metric (`MIN_SCALE` in `pipeline.py`) |
| Score | robust z = (today − median) / spread |
| Signal | \|z\| ≥ 2.0 in the unfavourable direction |
| Day | Asia/Beirut civil day; sleep belongs to the wake day |

## Wellness rules (feed the level)

| Code | Flag column | Input (unit) | Rule | Needs baseline | Plain wording |
| --- | --- | --- | --- | --- | --- |
| `sleep` | `flag_short_sleep` | `sleep_min` (minutes asleep) | < 360 min | no | "Slept less than 6 hours" |
| `rhr` | `flag_rhr_above_baseline` | `rhr` (bpm; vendor resting HR, else Sentra estimate) | z ≥ 2 | yes | "Resting heart rate above your normal" |
| `sleep_hr` | `flag_sleep_hr_above_baseline` | `sleep_hr` (bpm, mean while asleep) | z ≥ 2 | yes | "Sleeping heart rate above your normal" |
| `hrv` | `flag_hrv_below_baseline` | `daily_hrv_rmssd` (ms, RMSSD) | z ≤ −2 | yes | "Heart-rate variability below your normal" |

**Core rules** are `sleep`, `rhr` and `hrv`. `sleep_hr` needs a sleep-stage timeline that
WHOOP does not provide, so it adds a signal when it is available, but its absence alone
never blocks an assessment.

## Separate flags (do not feed the level)

| Flag | Input | Rule | Note |
| --- | --- | --- | --- |
| `flag_sustained_high_hr` | minute HR while worn | HR > 180 − age for ≥ 5 consecutive min | default age 30 is an assumption; formula weakly supported, see evidence |
| `flag_long_inactivity_in_shift` | worn, awake, zero-step minutes | ≥ 90 consecutive min inside 08:00–18:00 | the shift window is a hardcoded assumption |

## Assessment states

Every rule gets a per-day state in `assess_<code>`:

| State | Meaning |
| --- | --- |
| `signal` | the rule was assessed and its condition holds |
| `clear` | the rule was assessed and its condition does not hold |
| `no_reading` | today's input is missing |
| `baseline_building` | today's input exists but fewer than 7 of the previous 28 days have one |

The day then gets:

| Column | Values | Rule |
| --- | --- | --- |
| `assessment_state` | `complete` | all three core rules assessed |
| | `partial` | at least one rule assessed, not all core rules |
| | `insufficient` | no rule assessed |
| `assessment_reasons` | e.g. `rhr:baseline_building;sleep_hr:no_reading` | every rule not assessed, in rule order |
| `rules_assessed` | 0–4 | number of rules with `signal` or `clear` |
| `wellness_signals` | 0–4 | number of wellness rules with `signal` |
| `wellness_level` | `red` | 2 or more signals |
| | `amber` | exactly 1 signal |
| | `green` | 0 signals **and** `assessment_state = complete` |
| | `insufficient` | 0 signals and the assessment is not complete |

A signal is shown even when other rules are missing: amber or red with `partial` means
"something changed, and these other things could not be checked". **Missing data can never
produce green.** Missing values are never filled or treated as zero.

## Group statistics (`cohort_daily`)

- Only usable days count. A group day is shown only when at least 5 people have usable data
  (`suppressed`), and **each statistic** additionally needs 5 people who supplied its input.
- `pct_wellness_amber_or_red` counts only assessed days (`green`, `amber`, `red`); an
  `insufficient` day is not a calm day.
- Each statistic publishes its eligible contributor count as `n_<statistic>` (for example
  `n_pct_wellness_amber_or_red`), so dashboards and reports show "not available — 3 of 5
  needed" without recomputing it.

## Board payload

Per day: `lvl` is `green`/`amber`/`red`, or absent for `insufficient`. `a` is `partial` or
`insufficient` when the assessment is not complete, and `m` lists the reasons using the codes
above. The page shows "Partial assessment" or "Not enough information" with the reasons,
never a green pill. An amber or red day with `a = partial` reads "Amber · partial
assessment" (or Red), so it is never mistaken for a complete assessment.

The board also carries `assessment_version` (`ASSESSMENT_VERSION` in `pipeline.py`).
Bump it whenever these rules or their meaning change. The daily refresh rebuilds any board
published under another version from the existing data, even when no new collection has
arrived. Boards from before this contract carry no version, so the first refresh after
deployment replaces their misleading greens.

## Provider differences (preserved, not merged)

| Input | Fitbit (Google Health) | WHOOP |
| --- | --- | --- |
| `sleep_min` | vendor minutes asleep; stage timeline as fallback | light + slow-wave + REM, only when all three exist |
| `rhr` | vendor daily resting HR; else Sentra estimate from still, awake minutes | recovery resting HR (measured during sleep) |
| `daily_hrv_rmssd` | RMSSD over the main sleep (needs ≥ 3 h of sleep, per Google's API docs) | RMSSD during sleep; WHOOP describes it as the last slow-wave period, but publishes no formal specification |
| `sleep_hr` | mean minute HR while asleep | not available (no stage timeline) |

The same name does not mean the same measurement across devices, so baselines are always
personal and never compared across people or devices.

## Evidence summary and items for expert review

From [medical-evidence.md](medical-evidence.md) (section numbers in brackets). None of these
change a threshold here; each needs the expert's decision first.

| Rule | Evidence | Open question for the expert |
| --- | --- | --- |
| Short sleep < 6 h [1] | Supported; lenient against the ≥ 7 h adult consensus | add a "below 7 h" band, or flag repeated short nights |
| Baseline method [2] | Median/MAD and personal baselines supported | z = 2 is lenient (2.5 is commonly recommended); 28-day / 7-day choices have no direct source; require two consecutive days? |
| Resting HR up [3] | Partly supported (research and population studies) | normal week-to-week swings are common; keep wellness wording |
| Sleeping HR up [4] | Supported | overlaps with resting HR on Fitbit? |
| HRV down [5] | Concept supported | use ln(RMSSD) and 7-day trends |
| Sustained high HR [6] | **Weakly supported**: `180 − age` is a non-peer-reviewed training formula | replace with a stated share of age-predicted maximum (208 − 0.7 × age) and drop the default age |
| Long inactivity [7] | Partly supported; studies break sitting every 20–30 min | 30–60 min instead of 90 |
| Valid wear day [8], MET bands [10] | Supported research conventions | align sedentary to ≤ 1.5 METs |
| HR range [9] | Engineering plausibility filter, not a medical value | — |
| Group size k = 5 [11] | Privacy policy choice | stricter k (e.g. 10) in the privacy review |
| Devices [12] | Consumer wearables have known error | baselines stay per person and per device |
| Missing data [13] | No direct guideline | the "never green when missing" rule here is a design principle |

Other assumptions: the 08:00–18:00 shift window and the `MIN_SCALE` floors.
