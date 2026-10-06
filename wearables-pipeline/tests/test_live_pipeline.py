"""End-to-end: fake Google Health API data (14 days, 2 people) -> sync -> DB -> processing.
Proves the live path and the Kaggle path share the same processing code."""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wp import db  # noqa: E402
from wp.ingest import sync  # noqa: E402
from wp.process import pipeline  # noqa: E402

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"


class Fake:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)

    def list_points(self, dt, since):
        r = self.rng
        for day in range(14):
            d0 = T0 + timedelta(days=day)
            if dt == "heart-rate":
                for m in range(0, 1440):
                    t = d0 + timedelta(minutes=m)
                    asleep = t.hour < 5 or t.hour >= 21
                    bpm = (58 if asleep else 80) + r.normal(0, 4) + (8 if day == 12 else 0)
                    yield {"name": f"hr/{id(self)}/{day}/{m}", "dataSource": {"platform": "FITBIT"},
                           "heartRate": {"sampleTime": {"physicalTime": t.strftime(ISO), "utcOffset": "10800s"},
                                         "beatsPerMinute": str(int(bpm))}}
            elif dt == "steps":
                for h in range(6, 20):
                    t = d0 + timedelta(hours=h)
                    yield {"name": f"st/{id(self)}/{day}/{h}", "dataSource": {"platform": "FITBIT"},
                           "steps": {"interval": {"startTime": t.strftime(ISO), "endTime": (t + timedelta(minutes=1)).strftime(ISO),
                                                  "startUtcOffset": "10800s"}, "count": str(int(r.integers(0, 120)))}}
            elif dt == "sleep":
                s = d0 - timedelta(hours=3)
                hours = 4.5 if day == 12 else 7.5
                yield {"name": f"sl/{id(self)}/{day}", "dataSource": {"platform": "FITBIT"},
                       "sleep": {"interval": {"startTime": s.strftime(ISO), "endTime": (s + timedelta(hours=hours)).strftime(ISO),
                                              "startUtcOffset": "10800s"},
                                 "stages": [{"startTime": s.strftime(ISO), "endTime": (s + timedelta(hours=hours)).strftime(ISO),
                                             "type": "LIGHT"}]}}
            elif dt == "daily-resting-heart-rate":
                yield {"name": f"rhr/{id(self)}/{day}", "dataSource": {"platform": "FITBIT"},
                       "dailyRestingHeartRate": {"date": {"year": d0.year, "month": d0.month, "day": d0.day},
                                                 "beatsPerMinute": str(60 + (9 if day == 12 else int(r.integers(-1, 2))))}}


def test_live_end_to_end():
    tmp = Path(tempfile.mkdtemp())
    con = db.connect(tmp / "live.db")
    for i, label in enumerate(["mohamad", "friend1"]):
        sync.register(con, label)
        sync.sync_account(con, label, client=Fake(i), log=lambda *_: None)
    con.commit()
    obs = pd.read_sql("SELECT * FROM observations", con)
    g, d, c, _ = pipeline.run(obs, tmp / "out", log=lambda *_: None)
    day12 = d[d.date == pd.Timestamp("2026-09-13")]
    assert len(day12) == 2
    assert day12.flag_short_sleep.all(), "4.5 h night should be flagged"
    assert day12.flag_rhr_up.all(), "+9 bpm resting HR should be flagged"
    assert (day12.fatigue_level == "red").all()
    print("live pipeline test OK:", d[["subject_id", "date", "sleep_min", "rhr", "fatigue_level"]].tail(4).to_string(index=False))


if __name__ == "__main__":
    test_live_end_to_end()
