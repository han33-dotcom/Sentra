"""Kaggle 'FitBit Fitness Tracker Data' (Fitabase export, 2016)  ->  canonical observations.

Same shape as what our live extractor produces, so the processing code is shared.
Note: timestamps are local with no timezone -> utc_offset_min = 0 (treated as local).
METs are stored x10 in these files (10 = 1.0 MET).
"""
from pathlib import Path

import pandas as pd

from ..canonical import SLEEP_STAGE, unit

FMT = "%m/%d/%Y %I:%M:%S %p"
SLEEP_MAP = {1: SLEEP_STAGE["asleep_unspecified"], 2: SLEEP_STAGE["restless"], 3: SLEEP_STAGE["awake"]}


def _frame(subject, metric, value, start, end, resolution):
    return pd.DataFrame({
        "subject_id": "fb_" + subject.astype(str), "source": "fitabase", "device": "Fitbit (2016, unspecified)",
        "metric": metric, "value": value.astype(float), "unit": unit(metric),
        "start_utc": start, "end_utc": end, "utc_offset_min": 0, "resolution": resolution,
        "method": "auto", "quality_flag": "ok", "raw_ref": None,
    })


def load(root: Path) -> pd.DataFrame:
    root = Path(root)
    parts = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        f = d / "heartrate_seconds_merged.csv"
        if f.exists():
            x = pd.read_csv(f)
            t = pd.to_datetime(x.Time, format=FMT)
            parts.append(_frame(x.Id, "heart_rate", x.Value, t, pd.NaT, "sample"))
        f = d / "minuteStepsNarrow_merged.csv"
        if f.exists():
            x = pd.read_csv(f)
            t = pd.to_datetime(x.ActivityMinute, format=FMT)
            parts.append(_frame(x.Id, "steps", x.Steps, t, t + pd.Timedelta(minutes=1), "interval"))
        f = d / "minuteMETsNarrow_merged.csv"
        if f.exists():
            x = pd.read_csv(f)
            t = pd.to_datetime(x.ActivityMinute, format=FMT)
            parts.append(_frame(x.Id, "met", x.METs / 10.0, t, t + pd.Timedelta(minutes=1), "interval"))
        f = d / "minuteSleep_merged.csv"
        if f.exists():
            x = pd.read_csv(f)
            t = pd.to_datetime(x.date, format=FMT).dt.floor("min")
            parts.append(_frame(x.Id, "sleep_stage", x.value.map(SLEEP_MAP), t, t + pd.Timedelta(minutes=1), "interval"))
    obs = pd.concat(parts, ignore_index=True)
    # the two monthly exports overlap by a day -> drop exact duplicates
    return obs.drop_duplicates(["subject_id", "metric", "start_utc"]).reset_index(drop=True)
