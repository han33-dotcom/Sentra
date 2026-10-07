"""Keeps the backend current: every time the devices deliver new data, the processed outputs follow.

    sync (every WP_SYNC_EVERY_MIN, or right away when a trigger arrives)
      -> did any row really change?  (sync.ROWS_CHANGED, see UPSERT_* in ingest/sync.py)
      -> yes: mark outputs stale
    stale and the last refresh is older than WP_PROCESS_MIN_GAP_MIN
      -> process (daily features, flags, cohort) + etl (compact tiers)

Triggers are empty files in data/triggers/ named after a provider ("whoop", "google") or "all".
The API drops one when a WHOOP webhook says new data is ready, or when someone presses "sync now".

Entry points
    run_once()       one round; what the Windows scheduled task (run_sync.py) calls every hour
    run_forever()    the Docker worker: python -m wp worker
"""
import json
import os
import time
from datetime import datetime, timezone

from . import config

TICK_SEC = int(os.environ.get("WP_WORKER_TICK_SEC", 20))
PROCESS_MIN_GAP_MIN = int(os.environ.get("WP_PROCESS_MIN_GAP_MIN", 60))   # processing reads the whole DB
LOCK_STALE_SEC = 3 * 3600
PROVIDERS = {"google", "whoop"}


def _state_dir():
    d = config.DATA_DIR / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def trigger_dir():
    d = config.DATA_DIR / "triggers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ status -----------------------------
def status_path():
    return _state_dir() / "pipeline.json"


def load_status():
    try:
        return json.loads(status_path().read_text())
    except (FileNotFoundError, ValueError):
        return {"stale": False}


def save_status(st):
    tmp = status_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2))
    os.replace(tmp, status_path())


def heartbeat():
    (_state_dir() / "heartbeat").write_text(str(time.time()))


def heartbeat_age():
    try:
        return time.time() - float((_state_dir() / "heartbeat").read_text())
    except (FileNotFoundError, ValueError):
        return None


# ------------------------------------------------------------------ lock --------------------------------
class Busy(Exception):
    """Another run (scheduled task, UPDATE_ALL.bat, the Docker worker) holds the lock."""


class RunLock:
    """One writer at a time on the SQLite database, across processes."""

    def __init__(self):
        self.path = _state_dir() / "worker.lock"

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_SEC:   # crashed run left it
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                raise Busy(f"{self.path} is held by another run") from None
        raise Busy(str(self.path))

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)

    def clear_leftover(self):
        """Drop a lock left by a previous worker that was killed mid-run (container restart / redeploy).
        Only for a worker that is the sole writer on its data folder (WP_WORKER_OWNS_DATA=1)."""
        if self.path.exists():
            self.path.unlink(missing_ok=True)
            return True
        return False


# ------------------------------------------------------------------ triggers ----------------------------
def request_sync(provider="all", reason=""):
    """Ask the worker for a sync as soon as possible. Safe to call from the API process."""
    provider = provider if provider in PROVIDERS else "all"
    f = trigger_dir() / f"{provider}-{time.time_ns()}.trigger"
    f.write_text(reason[:200])
    return f.name


def pop_triggers():
    """-> None (nothing waiting), set() (sync everyone) or a set of providers."""
    files = list(trigger_dir().glob("*.trigger"))
    if not files:
        return None
    wanted = set()
    for f in files:
        wanted.add(f.name.split("-", 1)[0])
        f.unlink(missing_ok=True)
    return set() if "all" in wanted else wanted & PROVIDERS


# ------------------------------------------------------------------ the work ----------------------------
def _refresh(st, log):
    from . import etl, jobs
    t0 = time.time()
    jobs.process("live", log=log)
    etl.run(log=log)
    st.update(stale=False, last_process_at=now_iso(), last_process_sec=round(time.time() - t0))


def _refresh_due(st):
    last = st.get("last_process_at")
    if not last:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= PROCESS_MIN_GAP_MIN * 60


def run_once(log=print, providers=None, force_refresh=False, sync=True):
    """One round: sync -> (refresh if data changed and due) -> sign-in reminders. Returns the status dict."""
    from .ingest import sync as ingest
    with RunLock():
        st = load_status()
        if sync:
            before = ingest.ROWS_CHANGED
            try:
                ingest.sync_all(log=log, providers=providers)
            finally:
                changed = ingest.ROWS_CHANGED - before
                st.update(last_sync_at=now_iso(), last_sync_rows_changed=changed)
                if changed:
                    st.update(stale=True, last_change_at=now_iso())
                    log(f"[worker] {changed:,} new or corrected rows")
                save_status(st)
        if force_refresh or (st.get("stale") and _refresh_due(st)):
            try:
                _refresh(st, log)
            except Exception as e:      # keep the old outputs, try again next round
                st["last_process_error"] = f"{now_iso()} {e}"
                log(f"[worker] processing failed: {e}")
            else:
                st.pop("last_process_error", None)
            save_status(st)
    try:
        from . import reminders
        reminders.check_and_notify(log=log)
    except Exception as e:              # a reminder must never break the round
        log(f"[worker] reminders failed: {e}")
    return st


def run_forever(every_min=None, log=print):
    every = (every_min or config.SYNC_EVERY_MIN) * 60
    outer = log

    def log(msg):                       # every log line during a long sync doubles as a heartbeat
        heartbeat()
        outer(msg)
    next_full = 0.0
    if os.environ.get("WP_WORKER_OWNS_DATA") == "1" and RunLock().clear_leftover():
        log("[worker] cleared a lock left by a previous worker")
    log(f"[worker] up:full sync every {every // 60} min, refresh at most every {PROCESS_MIN_GAP_MIN} min, "
        f"triggers in {trigger_dir()}")
    while True:
        heartbeat()
        try:
            wanted = pop_triggers()
            if time.time() >= next_full:
                run_once(log=log)
                next_full = time.time() + every
            elif wanted is not None:
                log(f"[worker] trigger: {sorted(wanted) or 'all'}")
                run_once(log=log, providers=wanted or None)
            elif load_status().get("stale") and _refresh_due(load_status()):
                run_once(log=log, sync=False)
        except Busy as e:
            log(f"[worker] skipped round: {e}")
        except Exception as e:          # the loop itself must survive anything
            log(f"[worker] round failed: {e}")
        time.sleep(TICK_SEC)
