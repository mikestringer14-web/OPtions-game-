"""Load config.toml (+ env vars for anything sensitive) and expose a stable config hash."""
from __future__ import annotations

import hashlib
import json
import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parent
REPORTS = PKG / "reports"
LOGS = PKG / "logs"
DATA = PKG / "data"
PASS_FILE = REPORTS / "PASS.json"
PAPER_PORTS = frozenset({7497, 4002})     # used only by the optional, unused-by-default providers/ibkr.py
PROVIDERS = ("mock", "synthetic", "massive")


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(PKG / ".env", override=False)
    except ImportError:  # pragma: no cover
        pass


def load(path: Path | None = None, overrides: dict | None = None) -> dict[str, Any]:
    with open(path or PKG / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    if overrides:
        cfg = merge(cfg, overrides)
    return cfg


def merge(base: dict, extra: dict) -> dict:
    out = deepcopy(base)
    for k, v in extra.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config_hash(cfg: dict) -> str:
    """Hash of everything that affects which trades are taken and how."""
    relevant = {k: cfg.get(k) for k in ("signals", "gates", "contract", "fill_quality", "plan", "costs", "backtest", "account", "strategies")}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()
