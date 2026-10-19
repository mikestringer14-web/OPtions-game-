"""python -m options_screener.status  -> mode, data provider, budget, gate status. Prints no secrets."""
from __future__ import annotations

import json

from . import config as config_mod
from . import sizing
from .config import PASS_FILE, REPORTS, config_hash, env


def gather(cfg) -> dict:
    gate = "no backtest PASS file"
    if PASS_FILE.exists():
        d = json.loads(PASS_FILE.read_text())
        ok = d.get("verdict") == "PASS" and d.get("mode") == "VERIFIED" and d.get("config_hash") == config_hash(cfg)
        gate = f"PASS ({d.get('start')} to {d.get('end')})" if ok else "PASS file present but stale or not VERIFIED"
    backtests = sorted(REPORTS.glob("backtest_*.md"))
    a = cfg["account"]
    return {
        "mode": "RESEARCH (no orders, no broker connection)",
        "data_provider": cfg["data"]["provider"],
        "massive_api_key": "set" if env("MASSIVE_API_KEY") else "MISSING (needed for --provider massive)",
        "budget": f"C${a['capital_cad']:g} -> ~US${sizing.usd_budget(cfg):.2f} at fallback FX {a['cad_usd_rate']}; "
                  f"max premium/contract US${sizing.max_premium_per_contract(cfg):.3f}; ONE position",
        "backtest_gate": gate,
        "latest_backtest_report": backtests[-1].name if backtests else None,
        "config_hash": config_hash(cfg),
        "historical_options_provider": env("HISTORICAL_OPTIONS_PROVIDER", "none"),
        "earnings_calendar": "Alpha Vantage" if env("ALPHAVANTAGE_API_KEY") else
                             ("data/earnings.csv" if (config_mod.DATA / "earnings.csv").exists() else "none"),
        "news": "none (pluggable)",
    }


def main(argv=None) -> int:
    config_mod.load_env()
    for k, v in gather(config_mod.load()).items():
        print(f"{k:28} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
