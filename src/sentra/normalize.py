"""Conservative normalization: unknown semantics remain unknown, originals survive."""
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .datasets import canonical, camel
from .errors import SentraError

IDENTITY_FIELDS = {'user_id', 'healthUserId', 'googleWebClientId', 'webClientId', 'notes', 'displayName'}


def private_fields(value):
    if isinstance(value, dict):
        return {k: private_fields(v) for k, v in value.items() if k not in IDENTITY_FIELDS and k != 'name'}
    if isinstance(value, list):
        return [private_fields(v) for v in value]
    return value


def leaves(value, path=''):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaves(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list) and value:
        for i, child in enumerate(value):
            yield from leaves(child, path + '/' + str(i))
    else:
        yield path, value


def is_context_field(path):
    parts = path.split('/')
    return (path == '/dataSource' or path.startswith('/dataSource/')
            or 'sampleTime' in parts or 'metadata' in parts)


def numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
        return float(number) if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def meaning(job, path):
    field = path.rsplit('/', 1)[-1]
    if job.provider == 'whoop':
        definitions = {'strain': ('vendor_score', 'WHOOP strain'), 'recovery_score': ('vendor_score', '%'),
                       'average_heart_rate': ('vendor_summary', 'beats/min'), 'max_heart_rate': ('vendor_summary', 'beats/min'),
                       'resting_heart_rate': ('vendor_calculation', 'beats/min'), 'hrv_rmssd_milli': ('vendor_calculation', 'ms'),
                       'spo2_percentage': ('vendor_summary', '%'), 'skin_temp_celsius': ('vendor_summary', 'degC'),
                       'kilojoule': ('vendor_calculation', 'kJ'), 'distance_meter': ('vendor_summary', 'm'),
                       'sleep_performance_percentage': ('vendor_score', '%'), 'sleep_efficiency_percentage': ('vendor_calculation', '%'),
                       'sleep_consistency_percentage': ('vendor_score', '%'), 'respiratory_rate': ('vendor_summary', 'breaths/min')}
        if field in {'total_in_bed_time_milli', 'total_awake_time_milli', 'total_no_data_time_milli',
                     'total_light_sleep_time_milli', 'total_slow_wave_sleep_time_milli', 'total_rem_sleep_time_milli'}:
            return 'vendor_summary', 'ms'
        return definitions.get(field, ('unknown', None))
    units = {'beatsPerMinute': 'beats/min', 'beatsPerMinuteAvg': 'beats/min', 'beatsPerMinuteMax': 'beats/min',
             'beatsPerMinuteMin': 'beats/min', 'count': 'steps', 'countSum': 'steps',
             'breathsPerMinute': 'breaths/min', 'averageHeartRateVariabilityMilliseconds': 'ms',
             'deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds': 'ms',
             'nonRemHeartRateBeatsPerMinute': 'beats/min', 'minutesAsleep': 'min', 'minutesAwake': 'min',
             'minutesInSleepPeriod': 'min', 'minutesAfterWakeUp': 'min', 'minutesToFallAsleep': 'min'}
    units.update(millimetersSum='mm', kcalSum='kcal', activeMinutesSum='min',
                 sumInCardioHeartZone='active-zone min', sumInPeakHeartZone='active-zone min',
                 sumInFatBurnHeartZone='active-zone min')
    if field not in units or (field in ('count', 'countSum') and job.datatype != 'steps'):
        return 'unknown', None
    if job.mode in ('daily', 'minute'):
        return 'vendor_summary', units[field]
    if job.datatype == 'heart-rate' and field == 'beatsPerMinute':
        return 'measurement', units[field]
    return 'vendor_calculation', units[field]


def normalize_record(job, record, *, cycle=None):
    if not isinstance(record, dict):
        raise SentraError('Record structure invalid; page progress not advanced.')
    vendor = private_fields(record)
    if job.provider == 'whoop':
        identifier = record.get('cycle_id') if job.dataset == 'recovery' else record.get('id')
        if isinstance(identifier, bool) or not isinstance(identifier, (int, str)) or identifier == '':
            raise SentraError('WHOOP record lacks its stable ID; page progress not advanced.')
        record_key = str(identifier)
        timing = cycle or {} if job.dataset == 'recovery' else record
        start, end, point, civil = timing.get('start'), timing.get('end'), None, None
        basis = ('associated_cycle_interval' if cycle else 'unresolved_cycle_interval') if job.dataset == 'recovery' else 'vendor_interval'
        original_time = {k: timing[k] for k in ('start', 'end', 'timezone_offset') if k in timing}
    else:
        data = record.get(camel(job.datatype), {})
        if not isinstance(data, dict):
            raise SentraError('Google record data type invalid; page progress not advanced.')
        interval = data.get('interval', {})
        sample = data.get('sampleTime', {})
        if not isinstance(interval, dict) or not isinstance(sample, dict):
            raise SentraError('Google record timing structure invalid; page progress not advanced.')
        if 'name' in record and not isinstance(record['name'], str):
            raise SentraError('Google record ID structure invalid; page progress not advanced.')
        start = record.get('startTime') or interval.get('startTime')
        end = record.get('endTime') or interval.get('endTime')
        point = sample.get('physicalTime')
        civil = data.get('date') or record.get('civilStartTime')
        original_time = {'interval': interval, 'sampleTime': sample, 'civilDate': civil,
                         'civilEndTime': record.get('civilEndTime')}
        basis = 'vendor_civil_date' if civil and not (start or point) else 'vendor_physical_time'
        if record.get('name'):
            record_key = record['name'].rsplit('/', 1)[-1]
        else:
            identity_time = point or start or civil
            if not identity_time:
                raise SentraError('Google record lacks stable time/ID; page progress not advanced.')
            # Temporal identity excludes mutable values/end times. Distinct sources remain distinct.
            identity = {'time': identity_time, 'dataSource': record.get('dataSource', {}), 'type': job.datatype}
            record_key = hashlib.sha256(canonical(identity).encode()).hexdigest()
    timestamp = datetime.now(timezone.utc).isoformat()
    base = {'record_key': record_key, 'dataset': job.dataset, 'provider': job.provider,
            'interval_start': start, 'interval_end': end, 'measured_at': point, 'civil_date': civil,
            'timestamp_basis': basis, 'vendor_time': original_time, 'vendor_fields': vendor,
            'resolution_description': job.resolution, 'resolution_seconds': 60 if job.mode == 'minute' else None,
            'collected_at': timestamp, 'provisional': True, 'score_state': record.get('score_state'),
            'session_type': job.dataset if job.dataset in ('cycle', 'sleep', 'workout') else ('workout' if job.dataset == 'exercise' else None)}
    metrics = []
    for path, value in leaves(vendor):
        # Source/timing metadata belongs to record context, not measurement
        # rows. It remains intact in vendor_fields and unchanged originals.
        if is_context_field(path):
            continue
        kind, unit = meaning(job, path)
        # Keep returned scalar fields even when they are not measurements or lack time/units.
        metrics.append({**{k: v for k, v in base.items() if k not in ('vendor_fields', 'score_state', 'session_type')},
                        'metric': path, 'vendor_metric': path, 'vendor_value': value, 'vendor_unit': unit,
                        'value': numeric(value) if kind != 'unknown' else None, 'unit': unit,
                        'value_kind': kind, 'availability': 'missing' if value is None else 'available',
                        'interpretation_reference': 'docs/stage-2-collection.md; unmapped fields remain unknown'})
    return {**base, 'measurements': metrics}
