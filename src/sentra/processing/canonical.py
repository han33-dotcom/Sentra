"""Canonical metric names and units (ported from archive/monorepo-v0 wp/canonical.py; UCUM-style units)."""

METRICS = {
    # intraday
    'heart_rate': 'bpm',
    'steps': 'count',
    'met': 'MET',
    'sleep_stage': 'code',  # see SLEEP_STAGE codes
    'hrv_rmssd': 'ms',
    'spo2': '%',
    'active_zone_minutes': 'min',
    'sedentary_minutes': 'min',
    # daily summaries from the device vendor
    'resting_heart_rate': 'bpm',
    'daily_hrv_rmssd': 'ms',
    'daily_hrv_deep_rmssd': 'ms',
    'daily_respiratory_rate': 'br/min',
    'daily_spo2': '%',
    'daily_nonrem_hr': 'bpm',
    'nightly_skin_temp_c': 'Cel',
    'sleep_respiratory_rate': 'br/min',
    # summaries that WHOOP (and other non-stage devices) report per night / day
    'daily_sleep_min': 'min',
    'daily_in_bed_min': 'min',
    'daily_deep_sleep_min': 'min',
    'daily_rem_sleep_min': 'min',
    'daily_awake_min': 'min',
    'daily_avg_hr': 'bpm',
    'daily_max_hr': 'bpm',
    'daily_kilojoule': 'kJ',
    'whoop_recovery_score': '%',
    'whoop_strain': 'score',
    'whoop_sleep_performance_pct': '%',
}

# one code set for all vendors; vendor stages are mapped onto these
SLEEP_STAGE = {'awake': 0, 'light': 1, 'deep': 2, 'rem': 3, 'asleep_unspecified': 4, 'restless': 5}


def unit(metric: str) -> str:
    return METRICS.get(metric, 'unknown')
