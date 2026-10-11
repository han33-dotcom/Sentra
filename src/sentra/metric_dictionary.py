"""Explicit provider/dataset/path semantics, verified 2026-10-10; no suffix guessing."""
from dataclasses import dataclass
from decimal import Decimal

GOOGLE='https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints'
GOOGLE_ROLLUP='https://developers.google.com/health/aggregate-data'
WHOOP='https://developer.whoop.com/api/'


@dataclass(frozen=True)
class Metric:
    label: str
    unit: str
    kind: str
    explanation: str
    reference: str
    display_unit: str = ''
    divisor: int = 1
    precision: int = 1
    duration: bool = False


METRICS={}


def add(provider,dataset,path,label,unit,kind,explanation,*,display_unit='',divisor=1,precision=1,duration=False):
    reference=WHOOP if provider=='whoop' else (GOOGLE_ROLLUP if dataset.startswith(('daily_','minute_')) else GOOGLE)
    METRICS[provider,dataset,path]=Metric(label,unit,kind,explanation,reference,display_unit,divisor,precision,duration)


add('google_health','original_heart-rate','/heartRate/beatsPerMinute','Recorded heart rate','beats/min',
    'measurement','Heart-rate data point at the vendor physical sample time; not a raw optical sensor signal.',precision=0)


for dataset,path,label,unit,explanation,display,divisor,precision in (
    ('steps','/steps/countSum','Steps','steps','Vendor total steps for the requested calendar day.','',1,0),
    ('distance','/distance/millimetersSum','Distance','mm','Vendor total distance; displayed in kilometres.','km',1_000_000,2),
    ('total-calories','/totalCalories/kcalSum','Total energy','kcal','Vendor total energy expenditure, including resting energy.','',1,0),
    ('heart-rate','/heartRate/beatsPerMinuteAvg','Average heart rate','beats/min','Vendor average over returned heart-rate samples.','',1,0),
    ('heart-rate','/heartRate/beatsPerMinuteMin','Minimum heart rate','beats/min','Lowest returned heart-rate value in the requested window.','',1,0),
    ('heart-rate','/heartRate/beatsPerMinuteMax','Maximum heart rate','beats/min','Highest returned heart-rate value in the requested window.','',1,0),
    ('active-zone-minutes','/activeZoneMinutes/sumInFatBurnHeartZone','Moderate zone minutes','active-zone min','Vendor weighted active-zone minutes in its fat-burn zone.','',1,0),
    ('active-zone-minutes','/activeZoneMinutes/sumInCardioHeartZone','Cardio zone minutes','active-zone min','Vendor weighted active-zone minutes in its cardio zone.','',1,0),
    ('active-zone-minutes','/activeZoneMinutes/sumInPeakHeartZone','Peak zone minutes','active-zone min','Vendor weighted active-zone minutes in its peak zone.','',1,0),
):
    for prefix in ('daily_','minute_'):
        add('google_health',prefix+dataset,path,label,unit,'vendor_summary',explanation,
            display_unit=display,divisor=divisor,precision=precision)

for dataset,path,label,unit,explanation in (
    ('daily-resting-heart-rate','/dailyRestingHeartRate/beatsPerMinute','Fitbit resting heart rate','beats/min','Vendor estimate of resting heart rate for this civil day.'),
    ('daily-heart-rate-variability','/dailyHeartRateVariability/averageHeartRateVariabilityMilliseconds','Fitbit average HRV','ms','Vendor average heart-rate variability during sleep; separate from WHOOP HRV.'),
    ('daily-heart-rate-variability','/dailyHeartRateVariability/deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds','Fitbit deep-sleep HRV','ms','Vendor RMSSD during deep sleep.'),
    ('daily-heart-rate-variability','/dailyHeartRateVariability/nonRemHeartRateBeatsPerMinute','Non-REM heart rate','beats/min','Vendor heart rate during non-REM sleep.'),
    ('daily-respiratory-rate','/dailyRespiratoryRate/breathsPerMinute','Fitbit breathing rate','breaths/min','Vendor daily breathing-rate estimate during sleep.'),
    ('daily-sleep-temperature-derivations','/dailySleepTemperatureDerivations/nightlyTemperatureCelsius','Fitbit nightly skin temperature','°C','Mean of skin-temperature samples during sleep.'),
    ('daily-sleep-temperature-derivations','/dailySleepTemperatureDerivations/baselineTemperatureCelsius','Fitbit skin-temperature baseline','°C','Median nightly skin temperature over the past 30 days.'),
    ('daily-sleep-temperature-derivations','/dailySleepTemperatureDerivations/relativeNightlyStddev30dCelsius','Relative skin-temperature variation','°C','Vendor 30-day standard deviation of nightly temperature relative to baseline.'),
):
    add('google_health',dataset,path,label,unit,'vendor_calculation',explanation)

for stats,label in (('fullSleepStats','full sleep'),('deepSleepStats','deep sleep'),
                    ('lightSleepStats','light sleep'),('remSleepStats','REM sleep')):
    # standardDeviation/signalToNoise have no documented unit; they stay unmapped but retained.
    add('google_health','respiratory-rate-sleep-summary','/respiratoryRateSleepSummary/'+stats+'/breathsPerMinute',
        'Fitbit breathing rate ('+label+')','breaths/min','vendor_calculation',
        'Vendor average breaths per minute during '+label+' for one sleep; several per day are possible.')

for field,label,explanation in (
    ('minutesAsleep','Asleep','Vendor minutes classified as sleep, excluding awake stages.'),
    ('minutesAwake','Awake','Vendor minutes classified as awake.'),
    ('minutesInSleepPeriod','Sleep period','Vendor elapsed time between bedtime and wake time, including all stages.'),
    ('minutesToFallAsleep','Time to fall asleep','Vendor restlessness-based estimate of time to fall asleep.'),
    ('minutesAfterWakeUp','After waking','Vendor restlessness-based estimate of time after waking.'),
):
    add('google_health','sleep','/sleep/summary/'+field,label,'min','vendor_calculation',explanation,duration=True)

for field,label,unit,explanation,display,divisor,precision in (
    ('activeDuration','Active duration','s','Vendor exercise duration excluding pauses.','',1,0),
    ('metricsSummary/averageHeartRateBeatsPerMinute','Average heart rate','beats/min','Vendor average heart rate during the workout.','',1,0),
    ('metricsSummary/caloriesKcal','Workout energy','kcal','Vendor estimated energy expenditure during the workout.','',1,0),
    ('metricsSummary/distanceMillimeters','Distance','mm','Vendor workout distance.','km',1_000_000,2),
    ('metricsSummary/steps','Steps','steps','Vendor total steps during this workout.','',1,0),
    ('metricsSummary/activeZoneMinutes','Active zone minutes','active-zone min','Vendor weighted active-zone minutes for this workout.','',1,0),
    ('metricsSummary/averagePaceSecondsPerMeter','Average pace','s/m','Vendor average seconds per metre; shown as minutes per kilometre.','min/km',Decimal('0.06'),2),
):
    add('google_health','exercise','/exercise/'+field,label,unit,'vendor_summary',explanation,
        display_unit=display,divisor=divisor,precision=precision,duration=field=='activeDuration')

for dataset in ('cycle','workout'):
    for field,label,unit,kind,explanation in (
        ('strain','WHOOP strain','WHOOP strain','vendor_score','WHOOP proprietary cardiovascular strain score; not a Fitbit activity metric.'),
        ('average_heart_rate','Average heart rate','beats/min','vendor_summary','WHOOP average heart rate over this interval.'),
        ('max_heart_rate','Maximum heart rate','beats/min','vendor_summary','WHOOP highest heart rate over this interval.'),
        ('kilojoule','WHOOP energy','kJ','vendor_calculation','WHOOP estimated energy expenditure in kilojoules.'),
    ):
        add('whoop',dataset,'/score/'+field,label,unit,kind,explanation)
add('whoop','workout','/score/distance_meter','Distance','m','vendor_summary','WHOOP recorded workout distance.',display_unit='km',divisor=1000,precision=2)
add('whoop','workout','/score/percent_recorded','Recorded interval','%','vendor_summary','Percentage of the workout interval recorded by WHOOP.')
for field,label,unit,kind,explanation in (
    ('recovery_score','WHOOP recovery','%','vendor_score','WHOOP readiness score based on its recovery inputs; not a diagnosis or a Fitbit score.'),
    ('resting_heart_rate','WHOOP resting heart rate','beats/min','vendor_calculation','WHOOP resting heart-rate estimate associated with recovery.'),
    ('hrv_rmssd_milli','WHOOP HRV','ms','vendor_calculation','WHOOP RMSSD heart-rate variability used in recovery; keep separate from Fitbit HRV.'),
    ('spo2_percentage','WHOOP oxygen saturation','%','vendor_summary','WHOOP blood-oxygen estimate associated with recovery.'),
    ('skin_temp_celsius','WHOOP skin temperature','°C','vendor_summary','WHOOP skin-temperature summary associated with recovery.'),
):
    add('whoop','recovery','/score/'+field,label,unit,kind,explanation,precision=0 if field=='recovery_score' else 1)
for field,label,kind,explanation in (
    ('sleep_performance_percentage','WHOOP sleep performance','vendor_score','WHOOP sleep obtained relative to its calculated sleep need.'),
    ('sleep_efficiency_percentage','WHOOP sleep efficiency','vendor_calculation','WHOOP proportion of time in bed spent sleeping.'),
    ('sleep_consistency_percentage','WHOOP sleep consistency','vendor_score','WHOOP sleep-timing consistency score.'),
    ('respiratory_rate','WHOOP breathing rate','vendor_summary','WHOOP average breathing rate during sleep.'),
):
    add('whoop','sleep','/score/'+field,label,'breaths/min' if field=='respiratory_rate' else '%',kind,explanation,precision=1 if field=='respiratory_rate' else 0)
for field,label in (
    ('total_in_bed_time_milli','In bed'),('total_awake_time_milli','Awake'),
    ('total_no_data_time_milli','No recorded sleep data'),('total_light_sleep_time_milli','Light sleep'),
    ('total_slow_wave_sleep_time_milli','Deep sleep'),('total_rem_sleep_time_milli','REM sleep'),
):
    add('whoop','sleep','/score/stage_summary/'+field,label,'ms','vendor_summary','WHOOP classified duration in this sleep session.',duration=True)

ASLEEP=Metric('Asleep','ms','sentra_calculation','Sum of WHOOP light, slow-wave and REM durations; only when all three are returned and scored.',WHOOP,duration=True)
ELAPSED=Metric('Session duration','s','sentra_calculation','Elapsed physical end minus start; includes pauses and differs from active duration.',GOOGLE,duration=True)
# Interval datasets: per-day totals of returned periods from one source, only when no
# interval is invalid or overlapping. Periods count toward their Beirut start day.
SEDENTARY=Metric('Sedentary time','s','sentra_calculation',
    'Sum of returned Fitbit sedentary periods starting on this day; unreturned time is not assumed active.',GOOGLE,duration=True)
ACTIVITY_LEVELS={level:Metric('Time '+text,'s','sentra_calculation',
    'Sum of returned Fitbit activity-level intervals classified '+level+' starting on this day; unreturned time is not assumed.',GOOGLE,duration=True)
    for level,text in (('SEDENTARY','sedentary (activity level)'),('LIGHTLY_ACTIVE','lightly active'),
                       ('MODERATELY_ACTIVE','moderately active'),('VERY_ACTIVE','very active'))}


def period_metric(dataset,fields):
    if dataset=='sedentary-period': return SEDENTARY
    if dataset=='activity-level':
        level=fields.get('activityLevel',{}).get('activityLevelType') if isinstance(fields.get('activityLevel'),dict) else None
        return ACTIVITY_LEVELS.get(level)
    return None


def definition(provider,dataset,path):
    return METRICS.get((provider,dataset,path))
