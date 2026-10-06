import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wp import config  # noqa: E402


@pytest.fixture
def wp_home(tmp_path, monkeypatch):
    """Point every path the pipeline uses at a throwaway folder (never the real data/ or secrets/)."""
    data, secrets = tmp_path / "data", tmp_path / "secrets"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "SECRETS_DIR", secrets)
    monkeypatch.setattr(config, "TOKENS_DIR", secrets / "tokens")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "DB_PATH", data / "wearables.db")
    config.ensure_dirs()
    return tmp_path
