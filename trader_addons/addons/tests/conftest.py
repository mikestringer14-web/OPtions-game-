import sys
from pathlib import Path

import pytest

ADDONS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDONS))

import addons_common as ac  # noqa: E402


class _NoWait:
    def acquire(self):
        pass


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test writes to its own temp log/data dirs and never sleeps on rate limits."""
    monkeypatch.setattr(ac, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(ac, "DATA_DIR", tmp_path / "data")
    for name in ("dexscreener_limiter", "rpc_limiter", "api_limiter"):
        monkeypatch.setattr(ac, name, _NoWait())
    return tmp_path
