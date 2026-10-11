"""Fail if anything that looks like health data, credentials or a big binary is about to enter git.

    python scripts/check_no_data.py            check every tracked file (CI)
    python scripts/check_no_data.py --staged   check what `git commit` would add (pre-commit hook)
"""
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_BYTES = 2_000_000
BLOCKED_DIRS = {"data", "secrets", "tokens", "reports", ".venv", "venv"}
BLOCKED_EXT = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".parquet", ".feather", ".pkl",
               ".csv", ".zip", ".7z", ".txz", ".gz", ".docx", ".xlsx", ".pdf", ".env", ".pem", ".key", ".p12"}
ALLOWED = [re.compile(p) for p in (r"(^|/)tests/fixtures/", r"(^|/)\.env\.example$", r"^website/vendor/")]
SECRET_KEYS = re.compile(r'"(refresh_token|access_token|client_secret|private_key)"\s*:\s*"([^"<]{8,})')
# Obvious stand-ins used in tests and docs ("fake-secret", "new-refresh", "LOCAL_VALUE"). Letters, - and _ only:
# real tokens and client secrets contain digits, dots or slashes, so they still fail.
PLACEHOLDER = re.compile(r"(?i)(fake|dummy|example|placeholder|test|new|replacement|local|your)[a-z_-]*")


def has_secret(text):
    return any(not PLACEHOLDER.fullmatch(m.group(2)) for m in SECRET_KEYS.finditer(text))


def files(staged):
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    return [f for f in subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines() if f]


def problems(path):
    p = PurePosixPath(path)
    if any(rx.search(path) for rx in ALLOWED):
        return []
    out = []
    if BLOCKED_DIRS & set(p.parts[:-1]):
        out.append("inside a data/secrets/reports folder")
    if p.suffix.lower() in BLOCKED_EXT or p.name == ".env":
        out.append(f"blocked file type {p.suffix or p.name}")
    f = Path(path)
    if f.is_file():
        if f.stat().st_size > MAX_BYTES:
            out.append(f"{f.stat().st_size / 1e6:.1f} MB (limit {MAX_BYTES / 1e6:.0f} MB)")
        if f.suffix in {".json", ".txt", ".bat", ".ps1", ".py", ".yml", ".yaml", ".md"}:
            if has_secret(f.read_text(errors="ignore")):
                out.append("contains a token or client secret value")
            if f.suffix == ".bat" and "?code=" in f.read_text(errors="ignore"):
                out.append("contains an OAuth sign-in code")
    return out


def main():
    bad = {f: why for f in files("--staged" in sys.argv) if (why := problems(f))}
    for f, why in bad.items():
        print(f"BLOCKED  {f}: {'; '.join(why)}")
    if bad:
        print("\nHealth data, credentials and generated files stay out of git (see .gitignore / SECURITY.md).")
        sys.exit(1)
    print("data guard: ok")


if __name__ == "__main__":
    main()
