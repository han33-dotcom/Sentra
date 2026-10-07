"""The backend follows the devices: new data -> outputs refreshed; nothing new -> no work."""
import json
from datetime import datetime, timedelta, timezone

from wp import db, worker
from wp.ingest import sync

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"


class Device:
    """Deterministic fake Google Health account. `bump` changes resting HR on the last day."""

    def __init__(self, label, days=10, bump=0):
        self.label, self.days, self.bump = label, days, bump

    def list_points(self, dt, since):
        for day in range(self.days):
            d0 = T0 + timedelta(days=day)
            if dt == "heart-rate":
                for m in range(0, 1440, 5):
                    t = d0 + timedelta(minutes=m)
                    yield {"name": f"{self.label}/hr/{day}/{m}", "dataSource": {"platform": "FITBIT"},
                           "heartRate": {"sampleTime": {"physicalTime": t.strftime(ISO), "utcOffset": "10800s"},
                                         "beatsPerMinute": str(60 if t.hour < 6 else 80)}}
            elif dt == "sleep":
                s = d0 - timedelta(hours=3)
                yield {"name": f"{self.label}/sl/{day}", "dataSource": {"platform": "FITBIT"},
                       "sleep": {"interval": {"startTime": s.strftime(ISO), "endTime": (s + timedelta(hours=7)).strftime(ISO),
                                              "startUtcOffset": "10800s"},
                                 "stages": [{"startTime": s.strftime(ISO), "endTime": (s + timedelta(hours=7)).strftime(ISO),
                                             "type": "LIGHT"}]}}
            elif dt == "daily-resting-heart-rate":
                bpm = 60 + (self.bump if day == self.days - 1 else 0)
                yield {"name": f"{self.label}/rhr/{day}", "dataSource": {"platform": "FITBIT"},
                       "dailyRestingHeartRate": {"date": {"year": d0.year, "month": d0.month, "day": d0.day},
                                                 "beatsPerMinute": str(bpm)}}


def _connect(monkeypatch, devices):
    with db.session() as con:
        for label in devices:
            sync.register(con, label)
    monkeypatch.setattr(sync, "GoogleHealthClient", lambda label: devices[label])


def test_refreshes_only_when_devices_send_something_new(wp_home, monkeypatch):
    monkeypatch.setattr(worker, "PROCESS_MIN_GAP_MIN", 0)
    devices = {"a": Device("a"), "b": Device("b")}
    _connect(monkeypatch, devices)
    quiet = lambda *_: None  # noqa: E731

    st = worker.run_once(log=quiet)                       # first pull: everything is new
    assert st["last_sync_rows_changed"] > 0
    assert st["stale"] is False and st.get("last_process_at")
    daily = wp_home / "data" / "processed" / "live" / "daily_features.parquet"
    assert daily.exists() and (wp_home / "data" / "etl" / "size_report.txt").exists()
    first = st["last_process_at"]

    st = worker.run_once(log=quiet)                       # same data re-read (overlap window): no writes
    assert st["last_sync_rows_changed"] == 0
    assert st["last_process_at"] == first

    devices["a"].bump = 9                                 # watch re-syncs a corrected value
    st = worker.run_once(log=quiet)
    assert st["last_sync_rows_changed"] == 2           # its raw record + the canonical row
    assert st["stale"] is False                           # refreshed again

    saved = json.loads((wp_home / "data" / "state" / "pipeline.json").read_text())
    assert saved["last_sync_rows_changed"] == 2


def test_refresh_waits_for_the_gap(wp_home, monkeypatch):
    monkeypatch.setattr(worker, "PROCESS_MIN_GAP_MIN", 60)
    devices = {"a": Device("a")}
    _connect(monkeypatch, devices)
    worker.run_once(log=lambda *_: None)
    devices["a"].days = 11                                # a new day arrives right after
    st = worker.run_once(log=lambda *_: None)
    assert st["last_sync_rows_changed"] > 0 and st["stale"] is True   # queued, not run yet


def test_triggers_and_lock(wp_home):
    assert worker.pop_triggers() is None
    worker.request_sync("whoop")
    worker.request_sync("nonsense")                       # unknown provider -> everyone
    assert worker.pop_triggers() == set()
    worker.request_sync("whoop")
    assert worker.pop_triggers() == {"whoop"}
    with worker.RunLock():
        try:
            with worker.RunLock():
                raise AssertionError("second lock must fail")
        except worker.Busy:
            pass


def test_owning_worker_clears_a_leftover_lock(wp_home):
    lock = worker.RunLock()
    lock.path.write_text("1 0")                           # a killed container left this behind
    try:
        with worker.RunLock():
            raise AssertionError("leftover lock must block until cleared")
    except worker.Busy:
        pass
    assert lock.clear_leftover() is True
    with worker.RunLock():                                # free again
        pass
    assert lock.clear_leftover() is False
