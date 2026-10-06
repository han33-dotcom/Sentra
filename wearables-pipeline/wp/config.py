"""Paths and settings. Override with environment variables if needed."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("WP_ROOT", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(os.environ.get("WP_DATA", ROOT / "data"))
SECRETS_DIR = Path(os.environ.get("WP_SECRETS", ROOT / "secrets"))
REPORTS_DIR = Path(os.environ.get("WP_REPORTS", ROOT / "reports"))

DB_PATH = Path(os.environ.get("WP_DB", DATA_DIR / "wearables.db"))
CLIENT_SECRET = Path(os.environ.get("WP_CLIENT_SECRET", SECRETS_DIR / "client_secret.json"))
TOKENS_DIR = SECRETS_DIR / "tokens"

# --- sync behaviour ---------------------------------------------------------
BACKFILL_DAYS = int(os.environ.get("WP_BACKFILL_DAYS", 30))   # first sync pulls this much history
OVERLAP_HOURS = int(os.environ.get("WP_OVERLAP_HOURS", 6))    # re-read window to catch late phone syncs
SYNC_EVERY_MIN = int(os.environ.get("WP_SYNC_EVERY_MIN", 15))


def ensure_dirs():
    for d in (DATA_DIR, SECRETS_DIR, TOKENS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
