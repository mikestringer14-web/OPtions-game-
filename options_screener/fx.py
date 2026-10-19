"""CAD->USD rate. Bank of Canada Valet API (free, no key), cached once per day; falls back to the
config value, labelled as an ASSUMPTION.

  GET https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1
  -> observations[0] = {"d": "YYYY-MM-DD", "FXUSDCAD": {"v": "1.3789"}}   (CAD per 1 USD)
Docs: https://www.bankofcanada.ca/valet/docs
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from .config import DATA

VALET = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"


@dataclass
class FxRate:
    cad_usd: float          # USD per 1 CAD
    source: str
    as_of: str
    tag: str                # VERIFIED (Bank of Canada) or ASSUMPTION (config fallback)


def parse_valet(body: dict) -> tuple[float, str]:
    obs = body["observations"][-1]
    usdcad = float(obs["FXUSDCAD"]["v"])
    return 1.0 / usdcad, obs["d"]


def get_rate(cfg: dict, use_network: bool = True, http=None, cache_dir: Path = DATA / "cache", today=None) -> FxRate:
    fallback = FxRate(cfg["account"]["cad_usd_rate"], "config fallback", "n/a", "ASSUMPTION")
    if not use_network:
        return fallback
    today = today or date.today()
    path = cache_dir / f"fx_{today:%Y%m%d}.json"
    try:
        if path.exists():
            body = json.loads(path.read_text())
        else:
            r = (http or requests).get(VALET, params={"recent": 1}, timeout=10)
            if r.status_code != 200:
                return fallback
            body = r.json()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body))
        rate, d = parse_valet(body)
        return FxRate(round(rate, 5), "Bank of Canada Valet FXUSDCAD", d, "VERIFIED")
    except Exception:
        return fallback
