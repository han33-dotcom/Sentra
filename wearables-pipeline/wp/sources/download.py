"""Fetch the Kaggle 'FitBit Fitness Tracker Data' CSVs from a public GitHub mirror (no Kaggle login needed).
Original: https://www.kaggle.com/datasets/arashnic/fitbit (CC0)."""
from pathlib import Path
from urllib.parse import quote

import requests

MIRROR = "https://raw.githubusercontent.com/Vishak-KR/Bellabeat-Fitbit/main/"
PARTS = {
    "3.12.16-4.11.16": "mturkfitbit_export_3.12.16-4.11.16/Fitabase Data 3.12.16-4.11.16/",
    "4.12.16-5.12.16": "mturkfitbit_export_4.12.16-5.12.16/Fitabase Data 4.12.16-5.12.16/",
}
FILES = ["heartrate_seconds_merged", "minuteStepsNarrow_merged", "minuteMETsNarrow_merged",
         "minuteSleep_merged", "dailyActivity_merged"]


def download(dest: Path):
    for tag, path in PARTS.items():
        (dest / tag).mkdir(parents=True, exist_ok=True)
        for f in FILES:
            out = dest / tag / f"{f}.csv"
            if out.exists():
                continue
            print("downloading", tag, f)
            r = requests.get(MIRROR + quote(path + f + ".csv"), timeout=300)
            r.raise_for_status()
            out.write_bytes(r.content)
    return dest
