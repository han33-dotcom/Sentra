"""Entry point for Windows Task Scheduler (run with pythonw.exe, no console).

    schtasks /Run /TN FYPWearablesSync        run it now
    type data\\logs\\sync.log                 see what happened

Lessons carried over from Desktop/fitbit: run pythonw.exe directly (a .cmd wrapper got
killed with 0xC000013A) and turn off 'start only on AC power' or it never runs on battery.
"""
import datetime
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

from wp import config  # noqa: E402

log_dir = config.DATA_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = open(log_dir / "sync.log", "a", encoding="utf-8")


def log(msg):
    log_file.write(msg + "\n")
    log_file.flush()
    if sys.stdout and sys.stdout.isatty():
        print(msg)


log(f"\n==== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ====")
try:
    from wp import worker
    # sync everyone, then refresh processed outputs + etl if any device sent new data
    st = worker.run_once(log=log)
    log(f"[done] ok  rows changed: {st.get('last_sync_rows_changed')}  outputs refreshed: {st.get('last_process_at')}")
except BaseException:          # never let one failure hide the reason (SystemExit included)
    log("[failed]\n" + traceback.format_exc())
finally:
    log_file.close()
