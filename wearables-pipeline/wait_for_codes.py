"""Waits (up to 60 min) for sign-in addresses dropped into data/incoming/<label>.txt,
signs that person in immediately, then pulls their data. Lets Claude finish a sign-in
the moment you paste the google.com address in chat."""
import datetime
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
INBOX = HERE / "data" / "incoming"
INBOX.mkdir(parents=True, exist_ok=True)
LOG = HERE / "data" / "incoming.log"
PY = str(HERE / ".venv" / "Scripts" / "python.exe")


def log(msg):
    line = f"{datetime.datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(args, env=None):
    r = subprocess.run([PY, "-m", "wp", *args], capture_output=True, text=True, env=env)
    out = (r.stdout + r.stderr).strip()
    log(out)
    return r.returncode == 0


log("waiting for sign-in addresses in data/incoming ...")
end = time.time() + 3600
while time.time() < end:
    for f in sorted(INBOX.glob("*.txt")):
        label = f.stem
        code = f.read_text(encoding="utf-8").strip()
        f.rename(f.with_suffix(".used"))
        log(f"got address for {label}, signing in")
        args = ["connect", label, "--code", code]   # the account's email is already saved in the DB
        if run(args):
            env = dict(os.environ, WP_BACKFILL_DAYS="60")
            log(f"{label} connected. pulling data (heart-rate backfill takes a while)")
            run(["sync"], env)
            run(["accounts"])
            log(f"DONE {label}")
        else:
            log(f"FAILED {label}: get a fresh address (codes expire within minutes)")
    time.sleep(2)
log("stopped after 60 min")
