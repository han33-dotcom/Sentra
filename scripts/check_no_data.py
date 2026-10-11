"""Fail if anything that looks like health data, credentials or a big binary is about to enter git.

    python scripts/check_no_data.py            check every tracked file (CI)
    python scripts/check_no_data.py --staged   check what `git commit` would add (pre-commit hook)

Sentra keeps original responses, exports, backups, tokens, keys and consent documents
outside Git (see README "Verification, privacy and remaining work").
"""
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_BYTES = 2_000_000
BLOCKED_DIRS = {".private", "data", "exports", "backups", "secrets", "tokens", ".venv", "venv"}
BLOCKED_EXT = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".parquet", ".feather", ".pkl",
               ".csv", ".zip", ".7z", ".gz", ".tar", ".docx", ".xlsx", ".pdf", ".enc", ".pem", ".key", ".p12"}
BLOCKED_NAMES = [re.compile(p) for p in (
    r"^\.env(\..+)?$", r"^client_secret.*\.json$", r"^credentials.*\.json$", r"^secrets\.toml$", r"^local\.toml$",
)]
ALLOWED = [re.compile(p) for p in (r"(^|/)tests/fixtures/", r"(^|/)\.env\.example$", r"^website/vendor/")]
TEXT_SUFFIXES = {".json", ".toml", ".txt", ".ps1", ".py", ".yml", ".yaml", ".md", ".sql", ".cfg", ".ini"}
# Real-looking values only; example files use REPLACE / COPY_ / YOUR_ placeholders.
SECRET_VALUE = re.compile(
    r'["\']?(refresh_token|access_token|client_secret|private_key|secret_key|service_role_key|cookie_secret)["\']?'
    r'\s*[:=]\s*["\'](?!REPLACE|COPY_|YOUR_|<|\$\{|example)[^"\'\s]{16,}["\']',
    re.IGNORECASE,
)


def files(staged):
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    return [f for f in subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines() if f]


def problems(path):
    p = PurePosixPath(path)
    if any(rx.search(path) for rx in ALLOWED):
        return []
    out = []
    if BLOCKED_DIRS & set(p.parts[:-1]):
        out.append("inside a private data/secrets folder")
    if p.suffix.lower() in BLOCKED_EXT or any(rx.search(p.name) for rx in BLOCKED_NAMES):
        out.append(f"blocked file type {p.suffix or p.name}")
    f = Path(path)
    if f.is_file():
        if f.stat().st_size > MAX_BYTES:
            out.append(f"{f.stat().st_size / 1e6:.1f} MB (limit {MAX_BYTES / 1e6:.0f} MB)")
        if f.suffix.lower() in TEXT_SUFFIXES and f.resolve() != Path(__file__).resolve():
            if SECRET_VALUE.search(f.read_text(encoding="utf-8", errors="ignore")):
                out.append("contains a token, key or client secret value")
    return out


def main():
    bad = {f: why for f in files("--staged" in sys.argv) if (why := problems(f))}
    for f, why in bad.items():
        print(f"BLOCKED  {f}: {'; '.join(why)}")
    if bad:
        print("\nHealth data, credentials and generated files stay out of git (see .gitignore and CONTRIBUTING.md).")
        sys.exit(1)
    print("data guard: ok")


if __name__ == "__main__":
    main()
