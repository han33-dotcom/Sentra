# Processing layer (v0 wellness features)

Ported from `archive/monorepo-v0:wearables-pipeline/wp/process/pipeline.py`. It runs on
the parquet tiers (see [parquet-tiers.md](parquet-tiers.md)), not on the database, so it
uses no database egress except the egress needed to download tiers.

```
tiers -> observations.py (metric_map.py) -> clean -> minute grid -> daily -> 28-day personal baselines
      -> v0 flags (thresholds.json) -> k-anonymous cohort
```

> **Thresholds are v0 — pending medical expert sign-off.** Outputs are wellness
> indicators relative to each person's own recent pattern. They are not medical
> assessments and must never be presented as a diagnosis. Flags use neutral names:
> `flag_short_sleep`, `flag_rhr_above_baseline`, `flag_sleep_hr_above_baseline`,
> `flag_hrv_below_baseline`, `flag_sustained_high_hr`, `flag_long_inactivity_in_shift`.
> They feed `wellness_signals` (0–4) and `wellness_level` (green/amber/red).

## Running

```powershell
.venv/Scripts/python.exe -m pip install "pyarrow>=18" "pandas>=2.2" "numpy>=1.26"
.venv/Scripts/sentra.exe process-run --tiers .private/tiers --out .private/processed
.venv/Scripts/sentra.exe process-run --from-bucket --out .private/processed   # viewer role, egress reserved
```

Outputs, written atomically: `minute.parquet`, `daily_features.parquet`,
`cohort_daily.parquet` and `metadata.json` (notice, thresholds, cleaning report). Inputs
and outputs must stay beneath `.private`.

## Behaviour on this schema

- **Local day:** Asia/Beirut. Vendor civil dates stay civil. Sleep belongs to the wake day
  (interval end). WHOOP cycles and recoveries belong to the cycle start day.
- **Heart-rate source per minute:** raw readings (30-day hot tier) are used first, then
  Sentra minutes from raw, then vendor 60 s rollups. Sources are never mixed within one
  minute.
- **Missing data:** values stay NaN. Missing data never raises a flag. Days with no sleep
  data keep `sleep_min` empty.
- **Sleep:** several sleep sessions on one wake day keep the longest duration (naps are
  not added). WHOOP asleep minutes = light + slow-wave + REM, only when all three are
  present.
- **Fitbit sleep stages:** the Google sleep records already collected contain the stage
  timeline (`/sleep/stages/N/{type,startTime,endTime}`) and per-stage minutes
  (`/sleep/summary/stagesSummary/N`). `observations.google_sleep` maps them to
  `sleep_stage` minutes and `daily_deep_sleep_min` / `daily_rem_sleep_min`.
  Unknown stage types or unparseable times are skipped.
  - Complete vendor sleep duration takes precedence over stage-derived `sleep_min`,
    so skipped unknown stages cannot reduce the reported total. Stages supply the
    fallback duration, `sleep_eff` and `sleep_hr` (mean minute heart rate while asleep).
  - WHOOP has no stage timeline, so its `sleep_hr` stays empty and its sleep comes from
    the nightly totals.
  - Resting minutes now exclude stage-asleep minutes.
- **No MET values:** `active_min` and `sedentary_min` stay empty.
- **Cohort:** a day is shown only when at least `cohort_k_anonymity` (5) people have
  usable data. With the current two participants, every cohort day is suppressed.

## Metric-name mapping (`src/sentra/processing/metric_map.py`)

Paths are matched exactly; nothing is matched by suffix.

| Provider | Dataset | Vendor path | Canonical | Resolution | Scale | Day |
| --- | --- | --- | --- | --- | --- | --- |
| google_health | `original_heart-rate` | `/heartRate/beatsPerMinute` | `heart_rate` | sample | 1 | — |
| google_health | `minute_heart-rate` | `/heartRate/beatsPerMinuteAvg` | `heart_rate` | minute | 1 | — |
| google_health | `minute_steps` | `/steps/countSum` | `steps` | minute | 1 | — |
| google_health | `daily-resting-heart-rate` | `/dailyRestingHeartRate/beatsPerMinute` | `resting_heart_rate` | daily | 1 | civil |
| google_health | `daily-heart-rate-variability` | `/dailyHeartRateVariability/averageHeartRateVariabilityMilliseconds` | `daily_hrv_rmssd` | daily | 1 | civil |
| google_health | `daily-heart-rate-variability` | `/dailyHeartRateVariability/deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds` | `daily_hrv_deep_rmssd` | daily | 1 | civil |
| google_health | `daily-heart-rate-variability` | `/dailyHeartRateVariability/nonRemHeartRateBeatsPerMinute` | `daily_nonrem_hr` | daily | 1 | civil |
| google_health | `daily-respiratory-rate` | `/dailyRespiratoryRate/breathsPerMinute` | `daily_respiratory_rate` | daily | 1 | civil |
| google_health | `daily-sleep-temperature-derivations` | `/dailySleepTemperatureDerivations/nightlyTemperatureCelsius` | `nightly_skin_temp_c` | daily | 1 | civil |
| google_health | `respiratory-rate-sleep-summary` | `/respiratoryRateSleepSummary/fullSleepStats/breathsPerMinute` | `sleep_respiratory_rate` | daily | 1 | start |
| google_health | `sleep` | `/sleep/summary/minutesAsleep` | `daily_sleep_min` | daily | 1 | end |
| google_health | `sleep` | `/sleep/summary/minutesInSleepPeriod` | `daily_in_bed_min` | daily | 1 | end |
| google_health | `sleep` | `/sleep/summary/minutesAwake` | `daily_awake_min` | daily | 1 | end |
| whoop | `cycle` | `/score/strain` | `whoop_strain` | daily | 1 | start |
| whoop | `cycle` | `/score/average_heart_rate` | `daily_avg_hr` | daily | 1 | start |
| whoop | `cycle` | `/score/max_heart_rate` | `daily_max_hr` | daily | 1 | start |
| whoop | `cycle` | `/score/kilojoule` | `daily_kilojoule` | daily | 1 | start |
| whoop | `recovery` | `/score/recovery_score` | `whoop_recovery_score` | daily | 1 | start |
| whoop | `recovery` | `/score/resting_heart_rate` | `resting_heart_rate` | daily | 1 | start |
| whoop | `recovery` | `/score/hrv_rmssd_milli` | `daily_hrv_rmssd` | daily | 1 | start |
| whoop | `recovery` | `/score/spo2_percentage` | `daily_spo2` | daily | 1 | start |
| whoop | `recovery` | `/score/skin_temp_celsius` | `nightly_skin_temp_c` | daily | 1 | start |
| whoop | `sleep` | `/score/sleep_performance_percentage` | `whoop_sleep_performance_pct` | daily | 1 | end |
| whoop | `sleep` | `/score/respiratory_rate` | `daily_respiratory_rate` | daily | 1 | end |
| whoop | `sleep` | `/score/stage_summary/total_in_bed_time_milli` | `daily_in_bed_min` | daily | ms → min | end |
| whoop | `sleep` | `/score/stage_summary/total_awake_time_milli` | `daily_awake_min` | daily | ms → min | end |
| whoop | `sleep` | `/score/stage_summary/total_slow_wave_sleep_time_milli` | `daily_deep_sleep_min` | daily | ms → min | end |
| whoop | `sleep` | `/score/stage_summary/total_rem_sleep_time_milli` | `daily_rem_sleep_min` | daily | ms → min | end |

| Provider | Dataset | Why not used |
| --- | --- | --- |
| google_health | `daily_steps` | steps come from minute rollups; a vendor daily total would conflict with the minute sum |
| google_health | `minute_active-zone-minutes` | three weighted zones; no agreed canonical aggregation |
| google_health | `daily-oxygen-saturation` | no records returned so far; field path unverified |
| google_health | `daily-vo2-max` | no records returned so far; no canonical metric |
| google_health | `sedentary-period` | interval expansion to sedentary_minutes pending review |
| google_health | `activity-level` | no MET values; level-to-MET conversion would be an invented value |
| google_health | `exercise` | workout sessions are not used by the v0 daily features |
| whoop | `workout` | workout sessions are not used by the v0 daily features |
