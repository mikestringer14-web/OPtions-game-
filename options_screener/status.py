"""python -m options_screener.status  -> mode, configured data providers, gate status."""
from __future__ import annotations

import json

from . import config as config_mod
from .config import PAPER_PORTS, PASS_FILE, REPORTS, config_hash, env


def gather(cfg) -> dict:
    gate, mode = "no backtest PASS file (paper locked)", "RESEARCH"
    if PASS_FILE.exists():
        d = json.loads(PASS_FILE.read_text())
        if d.get("verdict") == "PASS" and d.get("mode") == "VERIFIED" and d.get("config_hash") == config_hash(cfg):
            gate, mode = f"PASS ({d.get('start')} to {d.get('end')}, created {d.get('created')})", "PAPER (unlocked)"
        else:
            gate = "PASS file present but stale or not VERIFIED (paper locked)"
    port = env("IBKR_PORT", "4002")
    backtests = sorted(REPORTS.glob("backtest_*.md"))
    return {
        "mode": mode,
        "gate": gate,
        "latest_backtest_report": backtests[-1].name if backtests else None,
        "config_hash": config_hash(cfg),
        "ibkr": f"{env('IBKR_HOST', '127.0.0.1')}:{port} " + ("(paper port)" if port.isdigit() and int(port) in PAPER_PORTS else "(NOT a paper port: screen/paper will refuse)"),
        "ibkr_paper_account_set": bool(env("IBKR_PAPER_ACCOUNT")),
        "historical_options_provider": env("HISTORICAL_OPTIONS_PROVIDER", "none") + (
            "" if env("HISTORICAL_OPTIONS_PROVIDER", "none") != "massive" else
            f" (key {'set' if env('MASSIVE_API_KEY') else 'MISSING'}, quotes {'on' if env('MASSIVE_HAS_QUOTES') == 'true' else 'off'})"),
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
