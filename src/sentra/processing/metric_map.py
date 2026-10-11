"""Sentra provider/dataset/vendor-path -> canonical metric (processing/canonical.py).

Each entry: (canonical, resolution, scale, day_basis).
  resolution  'sample' (instant), 'minute' (vendor 60 s rollup) or 'daily' (one value per day/session)
  scale       multiply the stored value to reach the canonical unit (e.g. WHOOP ms -> min)
  day_basis   which local (Asia/Beirut) date a daily value belongs to: 'civil' vendor date,
              'start' of its interval, or 'end' of its interval (sleep belongs to the wake day)

Anything not listed is not used by processing; it stays in the audit tables and tiers.
UNMAPPED records known gaps so they are not mistaken for oversights.
"""
from .canonical import METRICS

G, W = 'google_health', 'whoop'
MS_TO_MIN = 1 / 60_000

MAPPING = {
    # Google Health v4: intraday
    (G, 'original_heart-rate', '/heartRate/beatsPerMinute'): ('heart_rate', 'sample', 1, None),
    (G, 'minute_heart-rate', '/heartRate/beatsPerMinuteAvg'): ('heart_rate', 'minute', 1, None),
    (G, 'minute_steps', '/steps/countSum'): ('steps', 'minute', 1, None),
    # Google Health v4: daily vendor calculations (civil date)
    (G, 'daily-resting-heart-rate', '/dailyRestingHeartRate/beatsPerMinute'): ('resting_heart_rate', 'daily', 1, 'civil'),
    (G, 'daily-heart-rate-variability', '/dailyHeartRateVariability/averageHeartRateVariabilityMilliseconds'):
        ('daily_hrv_rmssd', 'daily', 1, 'civil'),
    (G, 'daily-heart-rate-variability', '/dailyHeartRateVariability/deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds'):
        ('daily_hrv_deep_rmssd', 'daily', 1, 'civil'),
    (G, 'daily-heart-rate-variability', '/dailyHeartRateVariability/nonRemHeartRateBeatsPerMinute'):
        ('daily_nonrem_hr', 'daily', 1, 'civil'),
    (G, 'daily-respiratory-rate', '/dailyRespiratoryRate/breathsPerMinute'): ('daily_respiratory_rate', 'daily', 1, 'civil'),
    (G, 'daily-sleep-temperature-derivations', '/dailySleepTemperatureDerivations/nightlyTemperatureCelsius'):
        ('nightly_skin_temp_c', 'daily', 1, 'civil'),
    (G, 'respiratory-rate-sleep-summary', '/respiratoryRateSleepSummary/fullSleepStats/breathsPerMinute'):
        ('sleep_respiratory_rate', 'daily', 1, 'start'),
    # Google Health v4: sleep session summaries (wake day)
    (G, 'sleep', '/sleep/summary/minutesAsleep'): ('daily_sleep_min', 'daily', 1, 'end'),
    (G, 'sleep', '/sleep/summary/minutesInSleepPeriod'): ('daily_in_bed_min', 'daily', 1, 'end'),
    (G, 'sleep', '/sleep/summary/minutesAwake'): ('daily_awake_min', 'daily', 1, 'end'),
    # WHOOP v2: cycles (start day)
    (W, 'cycle', '/score/strain'): ('whoop_strain', 'daily', 1, 'start'),
    (W, 'cycle', '/score/average_heart_rate'): ('daily_avg_hr', 'daily', 1, 'start'),
    (W, 'cycle', '/score/max_heart_rate'): ('daily_max_hr', 'daily', 1, 'start'),
    (W, 'cycle', '/score/kilojoule'): ('daily_kilojoule', 'daily', 1, 'start'),
    # WHOOP v2: recovery (associated cycle start day)
    (W, 'recovery', '/score/recovery_score'): ('whoop_recovery_score', 'daily', 1, 'start'),
    (W, 'recovery', '/score/resting_heart_rate'): ('resting_heart_rate', 'daily', 1, 'start'),
    (W, 'recovery', '/score/hrv_rmssd_milli'): ('daily_hrv_rmssd', 'daily', 1, 'start'),
    (W, 'recovery', '/score/spo2_percentage'): ('daily_spo2', 'daily', 1, 'start'),
    (W, 'recovery', '/score/skin_temp_celsius'): ('nightly_skin_temp_c', 'daily', 1, 'start'),
    # WHOOP v2: sleep (wake day); asleep minutes are derived in observations.py
    (W, 'sleep', '/score/sleep_performance_percentage'): ('whoop_sleep_performance_pct', 'daily', 1, 'end'),
    (W, 'sleep', '/score/respiratory_rate'): ('daily_respiratory_rate', 'daily', 1, 'end'),
    (W, 'sleep', '/score/stage_summary/total_in_bed_time_milli'): ('daily_in_bed_min', 'daily', MS_TO_MIN, 'end'),
    (W, 'sleep', '/score/stage_summary/total_awake_time_milli'): ('daily_awake_min', 'daily', MS_TO_MIN, 'end'),
    (W, 'sleep', '/score/stage_summary/total_slow_wave_sleep_time_milli'): ('daily_deep_sleep_min', 'daily', MS_TO_MIN, 'end'),
    (W, 'sleep', '/score/stage_summary/total_rem_sleep_time_milli'): ('daily_rem_sleep_min', 'daily', MS_TO_MIN, 'end'),
}

# WHOOP asleep minutes: light + slow-wave + REM of one sleep record, only when all three are present.
WHOOP_ASLEEP_PARTS = ('/score/stage_summary/total_light_sleep_time_milli',
                      '/score/stage_summary/total_slow_wave_sleep_time_milli',
                      '/score/stage_summary/total_rem_sleep_time_milli')

UNMAPPED = {
    (G, 'daily_steps'): 'steps come from minute rollups; a vendor daily total would conflict with the minute sum',
    (G, 'minute_active-zone-minutes'): 'three weighted zones; no agreed canonical aggregation',
    (G, 'daily-oxygen-saturation'): 'no records returned so far; field path unverified',
    (G, 'daily-vo2-max'): 'no records returned so far; no canonical metric',
    (G, 'sedentary-period'): 'interval expansion to sedentary_minutes pending review',
    (G, 'activity-level'): 'no MET values; level-to-MET conversion would be an invented value',
    (G, 'exercise'): 'workout sessions are not used by the v0 daily features',
    (W, 'workout'): 'workout sessions are not used by the v0 daily features',
}

assert all(target[0] in METRICS for target in MAPPING.values())


def lookup(provider, dataset, metric):
    return MAPPING.get((provider, dataset, metric))
