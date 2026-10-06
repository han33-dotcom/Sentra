"""Command line.

  python -m wp link <label> [--email x]   print the consent link to send to that person
  python -m wp connect <label> [--code URL]  finish sign-in with the google.com address they land on
  python -m wp remind                 show/notify who must sign in again soon (Testing mode = 7 days)
  python -m wp accounts               list connected people and their status
  python -m wp sync                   pull new data for everyone once
  python -m wp run [--every 15]       keep syncing every N minutes (leave running) - same as `worker`
  python -m wp worker [--every 15]    backend worker: sync, and refresh outputs whenever new data lands
  python -m wp update [--force]       one round: sync, then process + etl if anything changed
  python -m wp trigger [provider]     ask a running worker to sync now (google | whoop | all)
  python -m wp healthcheck            exit 0 if the worker is alive (used by Docker)
  python -m wp import-export <folder> <label>   load an earlier extraction (Desktop/fitbit) into the DB
  python -m wp download-kaggle        fetch the public Kaggle Fitbit dataset (~330 MB)
  python -m wp load-kaggle [folder]   convert the Kaggle Fitbit dataset to canonical form
  python -m wp process --source kaggle|live [--age label=years ...]
  python -m wp whoop-link <label>      WHOOP sign-in link to send
  python -m wp whoop-connect <label> --code URL   finish WHOOP sign-in
  python -m wp etl                    compact tiered copy of the database into data/etl (database untouched)
"""
import argparse
import json
import sqlite3

import pandas as pd

from . import config, db


def main():
    p = argparse.ArgumentParser(prog="wp")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("connect"); c.add_argument("label")
    c.add_argument("--code", help="the google.com address you landed on after tapping Allow")
    c.add_argument("--email", help="Google account to pre-select (saved for next time)")
    lk = sub.add_parser("link"); lk.add_argument("label"); lk.add_argument("--email")
    sub.add_parser("remind")
    sub.add_parser("accounts")
    sub.add_parser("sync")
    for name in ("run", "worker"):
        r = sub.add_parser(name); r.add_argument("--every", type=int, default=config.SYNC_EVERY_MIN)
    u = sub.add_parser("update"); u.add_argument("--force", action="store_true", help="process even if nothing changed")
    t = sub.add_parser("trigger"); t.add_argument("provider", nargs="?", default="all")
    sub.add_parser("healthcheck")
    ie = sub.add_parser("import-export"); ie.add_argument("folder"); ie.add_argument("label")
    sub.add_parser("download-kaggle")
    k = sub.add_parser("load-kaggle"); k.add_argument("folder", nargs="?", default=str(config.DATA_DIR / "raw" / "kaggle_fitbit"))
    pr = sub.add_parser("process"); pr.add_argument("--source", choices=["kaggle", "live"], default="kaggle")
    pr.add_argument("--age", nargs="*", default=[], help="label=age, e.g. mohamad=22")
    sub.add_parser("etl")
    wl = sub.add_parser("whoop-link"); wl.add_argument("label")
    wc = sub.add_parser("whoop-connect"); wc.add_argument("label"); wc.add_argument("--code", required=True)
    a = p.parse_args()

    if a.cmd == "connect":
        from .ingest import google_health, sync
        with db.session() as con:
            row = con.execute("SELECT email FROM accounts WHERE label=?", (a.label,)).fetchone()
        email = a.email or (row[0] if row else None)
        google_health.connect_account(a.label, code=a.code, email=email)
        with db.session() as con:
            sync.register(con, a.label)
            if email:
                con.execute("UPDATE accounts SET email=? WHERE label=?", (email, a.label))
        print(f"Connected '{a.label}'. Now run: python -m wp sync")

    elif a.cmd == "link":
        from .ingest import google_health, sync
        with db.session() as con:
            sync.register(con, a.label)
            if a.email:
                con.execute("UPDATE accounts SET email=? WHERE label=?", (a.email, a.label))
            email = a.email or con.execute("SELECT email FROM accounts WHERE label=?", (a.label,)).fetchone()[0]
        print(google_health.auth_link(a.label, email))

    elif a.cmd == "remind":
        from . import reminders
        if not reminders.check_and_notify(force=True):
            print("nobody is close to expiring")

    elif a.cmd == "accounts":
        import time
        from .ingest.google_health import refresh_expires_at
        with db.session() as con:
            acc = pd.read_sql("SELECT label, email, subject_id, age, status, last_sync_at, last_error FROM accounts", con)
            acc["signin_expires_in_days"] = [
                round((refresh_expires_at(lb) - time.time()) / 86400, 1) if refresh_expires_at(lb) else None
                for lb in acc.label]
            print(acc.to_string(index=False))
            print(pd.read_sql("SELECT label, data_type, synced_until, last_count FROM sync_state ORDER BY label, data_type", con).to_string(index=False))

    elif a.cmd == "sync":
        from .ingest import sync
        sync.sync_all()

    elif a.cmd in ("run", "worker"):
        from . import worker
        worker.run_forever(a.every, log=lambda m: print(m, flush=True))

    elif a.cmd == "update":
        from . import worker
        st = worker.run_once(force_refresh=a.force)
        print(json.dumps(st, indent=2))

    elif a.cmd == "trigger":
        from . import worker
        print("queued", worker.request_sync(a.provider, "cli"))

    elif a.cmd == "healthcheck":
        from . import worker
        import os
        age = worker.heartbeat_age()
        if age is None or age > int(os.environ.get("WP_HEALTH_MAX_AGE_SEC", 900)):   # processing can be quiet for minutes
            raise SystemExit(f"worker heartbeat missing or {age} s old")
        print(f"ok ({age:.0f} s)")

    elif a.cmd == "import-export":
        from .ingest import sync
        sync.import_export(a.folder, a.label)

    elif a.cmd == "whoop-link":
        from .ingest import whoop
        print(whoop.auth_link(a.label))

    elif a.cmd == "whoop-connect":
        from .ingest import whoop
        whoop.connect(a.label, a.code)
        print(f"Connected '{a.label}' (WHOOP). Now run: python -m wp sync")

    elif a.cmd == "etl":
        from . import etl
        etl.run()

    elif a.cmd == "download-kaggle":
        from .sources import download
        print("saved to", download.download(config.DATA_DIR / "raw" / "kaggle_fitbit"))

    elif a.cmd == "load-kaggle":
        from .sources import fitabase
        obs = fitabase.load(a.folder)
        out = config.DATA_DIR / "canonical" / "kaggle_fitbit_observations.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        obs.to_parquet(out, index=False)
        print(f"{len(obs):,} observations, {obs.subject_id.nunique()} subjects -> {out}")

    elif a.cmd == "process":
        from . import jobs
        out = jobs.process(a.source, dict(x.split("=", 1) for x in a.age))
        print("outputs:", out)


if __name__ == "__main__":
    try:
        main()
    except sqlite3.OperationalError as e:
        raise SystemExit(f"database error: {e}") from e
