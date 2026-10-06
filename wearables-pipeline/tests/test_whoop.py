"""Offline test of the WHOOP connector with records shaped like the API v2 docs."""
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wp import db  # noqa: E402
from wp.ingest import sync, whoop  # noqa: E402
from wp.process import pipeline  # noqa: E402


def fake(kind, since):
    out = []
    for d in range(1, 15):
        day = f"2026-09-{d:02d}"
        nxt = f"2026-09-{d + 1:02d}"
        hrs = 4.5 if d == 12 else 7.5
        if kind == "sleep":
            out.append({"id": f"s{d}", "cycle_id": d, "start": f"{day}T20:30:00.000Z", "end": f"{nxt}T04:00:00.000Z",
                        "timezone_offset": "+03:00", "nap": False, "score_state": "SCORED",
                        "score": {"stage_summary": {"total_in_bed_time_milli": int((hrs + .5) * 3.6e6),
                                                    "total_awake_time_milli": int(.5 * 3.6e6),
                                                    "total_light_sleep_time_milli": int(hrs * .5 * 3.6e6),
                                                    "total_slow_wave_sleep_time_milli": int(hrs * .25 * 3.6e6),
                                                    "total_rem_sleep_time_milli": int(hrs * .25 * 3.6e6)},
                                  "respiratory_rate": 15.5, "sleep_performance_percentage": 80}})
        elif kind == "recovery":
            out.append({"cycle_id": d, "sleep_id": f"s{d}", "score_state": "SCORED",
                        "score": {"recovery_score": 70, "resting_heart_rate": 55 + (9 if d == 12 else d % 2),
                                  "hrv_rmssd_milli": 70.0 - (30 if d == 12 else 0), "spo2_percentage": 96.0,
                                  "skin_temp_celsius": 33.5}})
        elif kind == "cycle":
            out.append({"id": d, "start": f"{day}T05:00:00.000Z", "end": f"{nxt}T05:00:00.000Z",
                        "timezone_offset": "+03:00", "score_state": "SCORED",
                        "score": {"strain": 12.3, "kilojoule": 9000, "average_heart_rate": 70, "max_heart_rate": 160}})
    return out


def test_whoop():
    tmp = Path(tempfile.mkdtemp())
    con = db.connect(tmp / "w.db")
    sync.register(con, "friend2")
    con.execute("UPDATE accounts SET provider='whoop' WHERE label='friend2'")
    for _ in range(2):
        whoop.sync_account(con, "friend2", log=lambda *_: None, fetch=fake)
    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    assert q("SELECT COUNT(*) FROM observations WHERE metric='resting_heart_rate'") == 14
    assert q("SELECT COUNT(*) FROM sessions WHERE kind='sleep'") == 14
    obs = pd.read_sql("SELECT * FROM observations", con)
    g, d, c, _ = pipeline.run(obs, tmp / "out", log=lambda *_: None)
    day = d[d.date == pd.Timestamp("2026-09-13")].iloc[0]   # night of the 12th, woke on the 13th
    assert abs(day.sleep_min - 270) < 1, day.sleep_min
    assert day.flag_short_sleep and day.flag_rhr_up and day.flag_hrv_down
    print("whoop test OK:", d[["date", "sleep_min", "rhr", "daily_hrv_rmssd", "fatigue_level"]].tail(3).to_string(index=False))


if __name__ == "__main__":
    test_whoop()
