"""Offline test of the extractor with fake API responses shaped like the Google Health API docs.
Run: python -m pytest tests  (or python tests/test_sync.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wp import db  # noqa: E402
from wp.ingest import sync  # noqa: E402


def fake_points(dt):
    if dt == "heart-rate":
        return [{"dataSource": {"recordingMethod": "PASSIVELY_MEASURED", "platform": "FITBIT", "device": {"displayName": "Fitbit Air"}},
                 "heartRate": {"sampleTime": {"physicalTime": f"2026-09-30T08:00:{i*5:02d}Z", "utcOffset": "10800s"},
                               "beatsPerMinute": str(70 + i)}} for i in range(10)]
    if dt == "steps":
        return [{"name": "users/1/dataTypes/steps/dataPoints/s1", "dataSource": {"platform": "FITBIT"},
                 "steps": {"interval": {"startTime": "2026-09-30T08:00:00Z", "endTime": "2026-09-30T08:01:00Z",
                                        "startUtcOffset": "10800s"}, "count": "87"}}]
    if dt == "sleep":
        return [{"name": "users/1/dataTypes/sleep/dataPoints/z1", "dataSource": {"platform": "FITBIT"},
                 "sleep": {"interval": {"startTime": "2026-09-29T21:00:00Z", "endTime": "2026-09-30T04:00:00Z",
                                        "startUtcOffset": "10800s"},
                           "stages": [{"startTime": "2026-09-29T21:00:00Z", "endTime": "2026-09-29T22:00:00Z", "type": "LIGHT"},
                                      {"startTime": "2026-09-29T22:00:00Z", "endTime": "2026-09-29T23:00:00Z", "type": "DEEP"}],
                           "summary": {"minutesAsleep": "400"}}}]
    if dt == "daily-resting-heart-rate":
        return [{"name": "users/1/dataTypes/daily-resting-heart-rate/dataPoints/r1", "dataSource": {"platform": "FITBIT"},
                 "dailyRestingHeartRate": {"date": {"year": 2026, "month": 9, "day": 30}, "beatsPerMinute": "58"}}]
    if dt == "daily-respiratory-rate":
        return [{"name": "users/1/dataTypes/daily-respiratory-rate/dataPoints/b1", "dataSource": {"platform": "FITBIT"},
                 "dailyRespiratoryRate": {"date": {"year": 2026, "month": 9, "day": 30}, "breathsPerMinute": 14.2}}]
    return []


class FakeClient:
    def list_points(self, dt, since):
        yield from fake_points(dt)


def test_sync_is_idempotent(tmp_path=None):
    path = (tmp_path or Path("/tmp")) / "t.db"
    path.unlink(missing_ok=True)
    con = db.connect(path)
    sync.register(con, "mohamad")
    for _ in range(3):  # three overlapping runs must not duplicate anything
        sync.sync_account(con, "mohamad", client=FakeClient(), log=lambda *_: None)
    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    assert q("SELECT COUNT(*) FROM raw_datapoints") == 4   # heart rate keeps no raw copy
    assert q("SELECT COUNT(*) FROM observations WHERE metric='heart_rate'") == 10
    assert q("SELECT value FROM observations WHERE metric='resting_heart_rate'") == 58
    assert q("SELECT COUNT(*) FROM observations WHERE metric='sleep_stage'") == 2
    assert q("SELECT utc_offset_min FROM observations WHERE metric='steps'") == 180
    assert q("SELECT COUNT(*) FROM observations WHERE metric = 'daily_respiratory_rate'") == 1
    assert q("SELECT COUNT(*) FROM sessions") == 1
    assert q("SELECT device FROM observations WHERE metric='heart_rate' LIMIT 1") == "Fitbit Air"
    print("sync test OK")


if __name__ == "__main__":
    test_sync_is_idempotent()
