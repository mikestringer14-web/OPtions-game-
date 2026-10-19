"""Backtest + validation + the PASS gate that unlocks paper mode.

    python -m options_screener.backtest --start 2024-01-01 --end 2026-09-30
    python -m options_screener.backtest --start 2026-03-01 --end 2026-09-30 --mock

For each past session D the screen runs on an AsOfView fixed at the PRIOR close (no lookahead),
then the morning plan is simulated on D's 1-minute bars. Without a historical options provider
the run is an UNDERLYING-PROXY approximation, the fill-quality gate is UNVERIFIED, and the gate
can never PASS (proxy results must not unlock paper trading). Mock data can never PASS either.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime

from . import config as config_mod
from . import market_calendar, signals, sim, stats
from .config import PASS_FILE, REPORTS, config_hash
from .models import TORONTO
from .providers.base import AsOfView, NullCatalysts, NullNews, ProviderUnavailable
from .screen import screen_day

B_KEYS = ["unusual_volume", "iv", "momentum", "move_potential"]


@dataclass
class DayCandidate:
    day: date
    cand: object
    b_score: float
    passes_c: bool


def collect(view, catalysts, news, days, cfg, symbols=None, enforce_c=True, permissive_b=None, progress=None):
    """Run the screen for each session using only data up to the prior close."""
    scfg = config_mod.merge(cfg, {"gates": {"move_signal_min": permissive_b}}) if permissive_b is not None else cfg
    out = []
    for i, d in enumerate(days):
        asof = market_calendar.previous_session(d)
        res = screen_day(AsOfView(view, asof), asof, d, scfg, catalysts, news, symbols, enforce_c=enforce_c)
        for c in res.passed_ab:
            out.append(DayCandidate(d, c, signals.weighted(c.scores, cfg, B_KEYS) or 0.0, c.fill.passed))
        if progress:
            progress(i + 1, len(days))
    return out


class Simulator:
    """Replays candidates on the session itself. Option bars are cached across parameter sweeps."""

    def __init__(self, view, cfg):
        self.view, self.cfg = view, cfg
        self._bars: dict = {}

    def _get(self, kind, key, fn):
        if (kind, key) not in self._bars:
            try:
                self._bars[(kind, key)] = fn()
            except ProviderUnavailable:
                self._bars[(kind, key)] = []
        return self._bars[(kind, key)]

    def run(self, dcs, *, b_min, use_c=True, delay=0, cost_mult=1.0, overrides=None):
        cfg, trades, by_day = self.cfg, [], {}
        for dc in dcs:
            if dc.b_score >= b_min and (dc.passes_c or not use_c):
                by_day.setdefault(dc.day, []).append(dc)
        for d, lst in sorted(by_day.items()):
            for dc in sorted(lst, key=lambda x: x.cand.combined, reverse=True)[: cfg["contract"]["top_n"]]:
                c = dc.cand
                k = c.snapshot.contract
                ob = self._get("opt", (k, d), lambda k=k, d=d: self.view.option_bars(k, d))   # the session being simulated
                ub = self._get("und", (k.symbol, d), lambda k=k, d=d: self.view.intraday_bars(k.symbol, d))
                fq = c.fill
                t = sim.simulate(day=d, contract=k, direction=c.direction, option_bars=ob, underlying_bars=ub, cfg=cfg,
                                 hist_median_spread_pct=fq.median_spread_pct, quotes=self.view.has_quotes,
                                 entry_delay_min=delay, cost_mult=cost_mult, overrides=overrides,
                                 meta={"earnings": c.earnings, "score": c.combined, "fq_score": fq.score})
                trades.append(t)
        return trades


def _bucket_score(t):
    return "score<0.60" if t.score < 0.6 else "0.60-0.75" if t.score < 0.75 else "score>=0.75"


def _bucket_dte(t):
    return "DTE 1-3" if t.dte <= 3 else "DTE 4-7" if t.dte <= 7 else "DTE 8-21"


def _bucket_fq(t):
    return "FQ 1.00" if t.fq_score >= 0.999 else "FQ 0.80-0.99" if t.fq_score >= 0.8 else "FQ <0.80"


def validate(dcs, days, sim_, cfg, mode):
    bt = cfg["backtest"]
    cut = days[int(len(days) * (1 - bt["oos_fraction"]))] if days else None
    is_dcs = [x for x in dcs if x.day < cut]
    oos_dcs = [x for x in dcs if x.day >= cut]
    is_days, oos_days = [d for d in days if d < cut], [d for d in days if d >= cut]
    base_b, base_stop = cfg["gates"]["move_signal_min"], cfg["plan"]["stop_pct"]

    grid = []
    for b in sorted({round(base_b - 0.05, 2), base_b, round(base_b + 0.10, 2)}):
        for stop in (10.0, 15.0, 20.0):
            m = stats.metrics(sim_.run(is_dcs, b_min=b, overrides={"stop_pct": stop}), len(is_days))
            grid.append({"move_signal_min": b, "stop_pct": stop, **{k: m[k] for k in ("filled", "expectancy_usd", "profit_factor")}})
    usable = [g for g in grid if g["filled"] >= 20 and g["expectancy_usd"] is not None]
    chosen = max(usable, key=lambda g: g["expectancy_usd"]) if usable else {"move_signal_min": base_b, "stop_pct": base_stop}
    b, ov = chosen["move_signal_min"], {"stop_pct": chosen["stop_pct"]}

    oos = sim_.run(oos_dcs, b_min=b, overrides=ov)
    oos_noc = sim_.run(oos_dcs, b_min=b, overrides=ov, use_c=False)
    full = sim_.run(dcs, b_min=b, overrides=ov)
    full_noc = sim_.run(dcs, b_min=b, overrides=ov, use_c=False)
    m_oos = stats.metrics(oos, len(oos_days))
    filled = [t for t in oos if t.filled]
    boot = stats.bootstrap([t.net_ret for t in filled], bt["bootstrap_samples"])
    cost2 = stats.metrics(sim_.run(oos_dcs, b_min=b, overrides=ov, cost_mult=2.0), len(oos_days))
    delay1 = stats.metrics(sim_.run(oos_dcs, b_min=b, overrides=ov, delay=1), len(oos_days))
    p = cfg["plan"]
    perturb = []
    for name, o in (("target x0.8", {"target_pct": p["target_pct"] * 0.8}), ("target x1.2", {"target_pct": p["target_pct"] * 1.2}),
                    ("stop x0.8", {"stop_pct": ov["stop_pct"] * 0.8}), ("stop x1.2", {"stop_pct": ov["stop_pct"] * 1.2}),
                    ("time stop 10:20", {"time_stop": "10:20"}), ("time stop 10:40", {"time_stop": "10:40"})):
        m = stats.metrics(sim_.run(oos_dcs, b_min=b, overrides={**ov, **o}))
        perturb.append({"variant": name, "filled": m["filled"], "expectancy_usd": m["expectancy_usd"]})

    reasons = []
    if mode != "VERIFIED":
        reasons.append(f"data mode is {mode}: only a backtest on real historical option data can unlock paper")
    if (m_oos["expectancy_usd"] or 0) <= 0:
        reasons.append(f"OOS expectancy {_f(m_oos['expectancy_usd'])} USD/trade is not > 0 after costs")
    if not boot or boot["p5"] <= 0:
        reasons.append(f"bootstrap p5 {_f(boot['p5'], 4) if boot else 'n/a (too few trades)'} is not > 0")
    if (cost2["expectancy_usd"] or 0) <= 0:
        reasons.append(f"2x-cost expectancy {_f(cost2['expectancy_usd'])} USD/trade is not > 0")
    if m_oos["fill_rate"] is None or m_oos["fill_rate"] < bt["min_entry_fill_rate"]:
        reasons.append(f"entry fill rate {_f(m_oos['fill_rate'])} < {bt['min_entry_fill_rate']}")
    if m_oos["filled"] < bt["min_oos_trades"]:
        reasons.append(f"OOS trades {m_oos['filled']} < {bt['min_oos_trades']}")
    return {
        "mode": mode, "split_date": cut.isoformat() if cut else None, "grid": grid, "chosen": chosen,
        "oos": m_oos, "oos_without_c": stats.metrics(oos_noc, len(oos_days)),
        "full": stats.metrics(full, len(days)), "full_without_c": stats.metrics(full_noc, len(days)),
        "bootstrap": boot, "cost_2x": cost2, "delay_1min": delay1, "perturbation": perturb,
        "perturbation_profitable_share": (sum(1 for x in perturb if (x["expectancy_usd"] or 0) > 0) / len(perturb)),
        "splits": {"signal bucket": stats.split(filled, _bucket_score), "DTE": stats.split(filled, _bucket_dte),
                   "call vs put": stats.split(filled, lambda t: "CALL" if t.right == "C" else "PUT"),
                   "earnings": stats.split(filled, lambda t: "earnings" if t.earnings else "non-earnings"),
                   "fill-quality score": stats.split(filled, _bucket_fq)},
        "verdict": "PASS" if not reasons else "FAIL", "reasons": reasons,
        "oos_trades": [asdict(t) for t in oos],
    }


def _f(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return "inf" if v == float("inf") else f"{v:.{nd}f}"
    return str(v)


METRIC_KEYS = ["entries_attempted", "filled", "fill_rate", "hit_rate_target", "win_rate", "avg_win", "avg_loss",
               "expectancy_usd", "expectancy_ret", "profit_factor", "max_drawdown_usd", "total_pnl",
               "avg_minutes_to_fill", "avg_minutes_held", "trades_per_day"]


def render(r, start, end, source, cfg) -> str:
    L = [f"# Backtest {start} to {end}", "",
         "**Research only. Not financial advice. Options can lose 100%. Simulated results, not real trading.**", "",
         f"- Run: {datetime.now(TORONTO):%Y-%m-%d %H:%M %Z} | data: {source}",
         f"- Mode: **{r['mode']}**" + (" (UNDERLYING-PROXY approximation; fill-quality gate UNVERIFIED)" if r["mode"] == "PROXY" else ""),
         f"- In-sample before {r['split_date']}, out-of-sample from it | config hash {config_hash(cfg)}",
         f"- Costs: USD {cfg['costs']['commission_per_contract']}/contract (min {cfg['costs']['min_commission_per_order']}/order) + "
         f"{cfg['costs']['other_fees_per_contract']}/contract fees; buys at the ask, sells at the bid",
         "", f"## GATE: {r['verdict']}", ""]
    L += [f"- {x}" for x in r["reasons"]] or ["- all conditions met"]
    L += ["", "| metric | OOS (with C) | OOS (without C) | full (with C) | full (without C) | OOS 2x costs | OOS +1 min delay |",
          "|---|---|---|---|---|---|---|"]
    for k in METRIC_KEYS:
        L.append(f"| {k} | " + " | ".join(_f(r[s].get(k)) for s in ("oos", "oos_without_c", "full", "full_without_c", "cost_2x", "delay_1min")) + " |")
    b = r["bootstrap"]
    L += ["", "Bootstrap of OOS net returns per trade: " + (f"p5 {b['p5']:.4f}, median {b['p50']:.4f}, "
          f"P(mean>0) {b['prob_mean_gt_0']:.2f}" if b else "too few trades")]
    L += ["", "## In-sample tuning grid (chosen = highest IS expectancy with >= 20 trades)", "",
          "| move_signal_min | stop % | filled | expectancy $ | PF |", "|---|---|---|---|---|"]
    L += [f"| {g['move_signal_min']} | {g['stop_pct']} | {g['filled']} | {_f(g['expectancy_usd'])} | {_f(g['profit_factor'])} |" for g in r["grid"]]
    L.append(f"\nChosen: {r['chosen']}")
    L += ["", "## Parameter perturbation (OOS)", "", "| variant | filled | expectancy $ |", "|---|---|---|"]
    L += [f"| {x['variant']} | {x['filled']} | {_f(x['expectancy_usd'])} |" for x in r["perturbation"]]
    L.append(f"\nProfitable share: {r['perturbation_profitable_share']:.0%}")
    for name, groups in r["splits"].items():
        L += ["", f"## OOS split: {name}", "", "| bucket | filled | hit rate | expectancy $ | PF |", "|---|---|---|---|---|"]
        L += [f"| {k} | {m['filled']} | {_f(m['hit_rate_target'])} | {_f(m['expectancy_usd'])} | {_f(m['profit_factor'])} |" for k, m in groups.items()]
    return "\n".join(L) + "\n"


def write(r, start, end, source, cfg):
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = f"backtest_{datetime.now(TORONTO):%Y%m%d}" + ("_MOCK" if r["mode"] == "MOCK" else "")
    md = REPORTS / f"{stem}.md"
    md.write_text(render(r, start, end, source, cfg))
    (REPORTS / f"{stem}.json").write_text(json.dumps(r, indent=2, default=str))
    if r["verdict"] == "PASS":
        PASS_FILE.write_text(json.dumps({"verdict": "PASS", "config_hash": config_hash(cfg), "created": datetime.now(TORONTO).isoformat(),
                                         "start": str(start), "end": str(end), "mode": r["mode"], "oos": r["oos"]}, indent=2, default=str))
    elif PASS_FILE.exists():
        PASS_FILE.unlink()          # a failing run re-locks paper mode
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest the morning screen (research only)")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--underlying", choices=["ibkr", "csv"], default="csv")
    ap.add_argument("--symbols")
    args = ap.parse_args(argv)
    config_mod.load_env()
    cfg = config_mod.load()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    days = market_calendar.sessions_between(start, end)
    symbols = args.symbols.split(",") if args.symbols else None
    if args.mock:
        from .providers.mock import MockWorld

        view = MockWorld(symbols, end=end, history_days=(end - start).days + 120, earnings_on={})
        catalysts, mode, source, symbols = view, "MOCK", "MOCK synthetic data (not market data)", view.symbols
    else:
        view, catalysts, mode, source = build_historical(cfg, args.underlying)
    news = NullNews()
    dcs = collect(view, catalysts, news, days, cfg, symbols, enforce_c=(mode != "PROXY"),
                  permissive_b=round(cfg["gates"]["move_signal_min"] - 0.05, 2),
                  progress=lambda i, n: print(f"\rscreened {i}/{n} sessions", end="", flush=True))
    print()
    r = validate(dcs, days, Simulator(view, cfg), cfg, mode)
    md = write(r, start, end, source, cfg)
    print(md.read_text())
    print(f"Wrote {md}")
    return 0


def build_historical(cfg, underlying_kind):
    from .config import env
    from .providers.csv_provider import CSVEarnings, CSVOptions, CSVUnderlying
    from .providers.historical import HistoricalView

    if underlying_kind == "ibkr":
        from .providers.ibkr import IBKRView

        und = IBKRView.connect_readonly(cfg)
    else:
        und = CSVUnderlying()
    kind = env("HISTORICAL_OPTIONS_PROVIDER", "none").lower()
    opts = None
    if kind == "massive":
        from .providers.massive import MassiveOptions

        opts = MassiveOptions()
    elif kind == "csv":
        opts = CSVOptions()
    elif kind == "thetadata":
        from .providers.massive import ThetaDataOptions

        opts = ThetaDataOptions()
    view = HistoricalView(und, opts, cfg)
    mode = "PROXY" if opts is None else ("VERIFIED" if opts.has_quotes else "BARS-ONLY")
    catalysts = CSVEarnings() if (config_mod.DATA / "earnings.csv").exists() else NullCatalysts()
    return view, catalysts, mode, view.name


if __name__ == "__main__":
    raise SystemExit(main())
