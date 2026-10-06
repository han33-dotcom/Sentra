"""Sign-in expiry reminders.

While the Google app is in Testing mode every person's access dies 7 days after they last
signed in. This checks each account and, when one is close to expiring (or already expired),
shows a Windows notification (at most every 12 h per person) and writes the fresh consent links
to data/reauth_links.txt.
"""
import json
import subprocess
import sys
import time

from . import config, db
from .ingest.google_health import auth_link, refresh_expires_at

WARN_HOURS = 48
REPEAT_HOURS = 12


def _state_path():
    return config.DATA_DIR / "reminder_state.json"


def status(con):
    """[(label, email, hours_left or None, status)]"""
    out = []
    for label, email, st, prov in con.execute("SELECT label, email, status, COALESCE(provider,'google') FROM accounts"):
        exp = refresh_expires_at(label) if prov == "google" else None   # WHOOP tokens don't expire weekly
        hours = None if exp is None else (exp - time.time()) / 3600
        out.append((label, email, hours, st))
    return out


def _link(label, email):
    with db.session() as con:
        prov = (con.execute("SELECT provider FROM accounts WHERE label=?", (label,)).fetchone() or ["google"])[0]
    if prov == "whoop":
        from .ingest import whoop
        return whoop.auth_link(label) + f"\nthen: python -m wp whoop-connect {label} --code \"<address>\""
    return auth_link(label, email) + f"\nthen: python -m wp connect {label} --code \"<address>\""


def due(rows):
    return [r for r in rows if r[3] == "needs_reconnect" or (r[2] is not None and r[2] < WARN_HOURS)]


def toast(title, body):
    if sys.platform != "win32":
        print(f"[reminder] {title}: {body}")
        return
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$x=$t.GetElementsByTagName('text');"
        f"$x.Item(0).AppendChild($t.CreateTextNode({json.dumps(title)})) > $null;"
        f"$x.Item(1).AppendChild($t.CreateTextNode({json.dumps(body)})) > $null;"
        "$id='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                   creationflags=0x08000000, timeout=30)   # CREATE_NO_WINDOW


def check_and_notify(log=print, force=False):
    with db.session() as con:
        rows = status(con)
    todo = due(rows)
    links = config.DATA_DIR / "reauth_links.txt"
    if not todo:
        return []
    state_file = _state_path()
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    lines = []
    for label, email, hours, st in todo:
        when = "EXPIRED" if st == "needs_reconnect" or (hours is not None and hours <= 0) else f"expires in {hours:.0f} h"
        lines.append(f"{label} ({email or 'no email set'}): {when}\n{_link(label, email)}\n")
        if force or time.time() - state.get(label, 0) > REPEAT_HOURS * 3600:
            try:
                toast(f"Fitbit sign-in: {label} {when}",
                      "Double-click REAUTH.bat in Desktop\\FYP\\wearables-pipeline (takes 1 minute).")
            except Exception as e:   # a failed notification must never break the sync
                log(f"  toast failed: {e}")
            state[label] = time.time()
        log(f"  [reminder] {label}: {when}")
    links.write_text("\n".join(lines), encoding="utf-8")
    state_file.write_text(json.dumps(state))
    return todo
