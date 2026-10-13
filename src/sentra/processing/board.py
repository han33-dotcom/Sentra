"""Wellness board payload: one pseudonymous JSON document built from daily_features.

Shape matches the board page (src/sentra/board/board.html): a list of participants, each with
dated rows. Missing values are omitted, never zero-filled; days without usable data are left out
so the page shows them as "no data".
"""
import html
import json
from pathlib import Path

import pandas as pd

from .pipeline import NOTICE, TH

DEVICES = {'google_health': 'Fitbit', 'whoop': 'WHOOP'}
FIELDS = {  # board key -> daily_features column, decimals
    'sleep': ('sleep_min', 0), 'rhr': ('rhr', 0), 'hrv': ('daily_hrv_rmssd', 1),
    'br': ('daily_respiratory_rate', 1), 'temp': ('nightly_skin_temp_c', 1), 'steps': ('steps', 0),
    'wear': ('wear_min', 0), 'sleep_hr': ('sleep_hr', 0), 'deep': ('daily_deep_sleep_min', 0),
    'rem': ('daily_rem_sleep_min', 0), 'rec': ('whoop_recovery_score', 0), 'strain': ('whoop_strain', 1),
    'spo2': ('daily_spo2', 1),
    'rhr_b': ('rhr_base', 1), 'hrv_b': ('daily_hrv_rmssd_base', 1), 'sleep_b': ('sleep_min_base', 0),
    'rhr_z': ('rhr_z', 1), 'hrv_z': ('daily_hrv_rmssd_z', 1), 'sleep_z': ('sleep_min_z', 1),
}
FLAGS = {'flag_short_sleep': 'short_sleep', 'flag_rhr_above_baseline': 'rhr_up',
         'flag_hrv_below_baseline': 'hrv_down', 'flag_sleep_hr_above_baseline': 'sleep_hr_up'}
TEMPLATE = Path(__file__).resolve().parents[1] / 'board' / 'board.html'


def _value(raw, decimals):
    if raw is None or pd.isna(raw):
        return None
    number = round(float(raw), decimals)
    return int(number) if decimals == 0 else number


def payload(daily, devices, *, built_at, source_run=None):
    """devices maps pseudonym -> provider; names are never part of the payload."""
    people = []
    for pid, rows in daily[daily.usable_day.fillna(False).astype(bool)].groupby('subject_id', sort=True):
        days = []
        for _, row in rows.sort_values('date').iterrows():
            level = row.get('wellness_level')
            day = {'d': pd.Timestamp(row['date']).date().isoformat(), 'lvl': level if level in ('green', 'amber', 'red') else None}
            for key, (column, decimals) in FIELDS.items():
                if column in rows and (value := _value(row[column], decimals)) is not None:
                    day[key] = value
            flags = [code for column, code in FLAGS.items() if column in rows and pd.notna(row[column]) and bool(row[column])]
            if flags:
                day['f'] = flags
            days.append(day)
        people.append({'id': str(pid), 'name': str(pid), 'device': DEVICES.get(devices.get(pid), 'Unknown'), 'days': days})
    latest = max((p['days'][-1]['d'] for p in people if p['days']), default=None)
    return {'built_at': built_at, 'source_run': source_run, 'data_through': latest, 'notice': NOTICE,
            'thresholds_status': TH['_status'], 'people': people}


def render(board):
    """Board HTML with the payload embedded; safe against `</script>` inside values."""
    data = json.dumps(board['people'], separators=(',', ':')).replace('</', '<\\/')
    page = TEMPLATE.read_text(encoding='utf-8')
    return (page.replace('/*__SENTRA_DATA__*/[]', data)
                .replace('__SENTRA_ASOF__', html.escape(board.get('data_through') or 'no data yet'))
                .replace('__SENTRA_NOTICE__', html.escape(board.get('notice') or '')))
