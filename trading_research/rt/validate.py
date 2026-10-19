"""Validation protocol: dev/out-of-sample split, yearly walk-forward, cost stress,
parameter perturbation, delayed entries, missed fills, regimes, bootstrap, risk levels,
a $100 worked example and the pre-registered go/no-go gates.

    python -m rt.validate --strategy A_trend_breakout --symbols BTC-USD ETH-USD SOL-USD
"""
import argparse
import itertools
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

from . import data as data_mod
from . import engine
from . import indicators as ind
from .strategies import STRATEGIES

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def ts(date_str):
    return int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp())


def ymd(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def load_config(path=None):
    return json.loads(Path(path or ROOT / "config.json").read_text())


def build(strategy_name, bars_by_symbol, params=None):
    cls = STRATEGIES[strategy_name]
    return {s: cls(**(params or {})).prepare(b) for s, b in bars_by_symbol.items()}


class Runner:
    """Runs and logs every backtest so the number of tries is on record (multiple testing)."""

    def __init__(self, strategy, bars, base_cfg, log_path):
        self.strategy, self.bars, self.base_cfg, self.log_path = strategy, bars, base_cfg, log_path
        self.count = 0

    def __call__(self, label, params=None, symbols=None, **cfg):
        bars = {s: self.bars[s] for s in (symbols or self.bars)}
        res = engine.run(build(self.strategy, bars, params), {**self.base_cfg, **cfg})
        m = engine.metrics(res)
        self.count += 1
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "strategy": self.strategy, "label": label, "params": params or {},
                                    "symbols": list(bars), "cfg": {k: v for k, v in {**self.base_cfg, **cfg}.items()},
                                    "metrics": m}, default=str) + "\n")
        return res, m


def buy_and_hold(bars_by_symbol, start_ts, end_ts, fee, slip, alloc=0.9):
    """Equal-weight buy & hold over the same window, paying entry and exit costs."""
    rets = []
    for b in bars_by_symbol.values():
        idx = [i for i, t in enumerate(b.t) if start_ts <= t <= end_ts]
        if len(idx) < 2:
            continue
        entry = b.o[idx[0]] * (1 + slip) * (1 + fee)
        exit_ = b.c[idx[-1]] * (1 - slip) * (1 - fee)
        rets.append(exit_ / entry - 1)
    return (sum(rets) / len(rets) * alloc * 100) if rets else None


def regime_of(bars, i, vol_median):
    s200 = ind.sma(bars.c[: i + 1], 200)
    a = ind.atr(bars.h[: i + 1], bars.l[: i + 1], bars.c[: i + 1], 14)[-1]
    trend = "unknown"
    if i >= 220 and not ind.isnan(s200[-1]) and not ind.isnan(s200[-21]):
        rising = s200[-1] > s200[-21]
        above = bars.c[i] > s200[-1]
        trend = "bull" if above and rising else "bear" if not above and not rising else "sideways"
    vol = "high_vol" if (not ind.isnan(a) and a / bars.c[i] > vol_median) else "low_vol"
    return trend, vol


def regime_table(trades, bars_by_symbol):
    medians = {}
    for s, b in bars_by_symbol.items():
        a = ind.atr(b.h, b.l, b.c, 14)
        vals = sorted(a[k] / b.c[k] for k in range(len(b)) if not ind.isnan(a[k]))
        medians[s] = vals[len(vals) // 2] if vals else 0
    table = {}
    for tr in trades:
        b = bars_by_symbol[tr["symbol"]]
        for key in regime_of(b, tr["signal_index"], medians[tr["symbol"]]):
            row = table.setdefault(key, {"trades": 0, "net_pnl": 0.0, "wins": 0, "r_sum": 0.0})
            row["trades"] += 1
            row["net_pnl"] += tr["net_pnl"]
            row["wins"] += tr["net_pnl"] > 0
            row["r_sum"] += tr["r_multiple"]
    for row in table.values():
        row["win_rate_pct"] = row["wins"] / row["trades"] * 100
        row["expectancy_r"] = row["r_sum"] / row["trades"]
    return table


def bootstrap_expectancy(trades, n=5000, seed=11):
    rs = [t["r_multiple"] for t in trades]
    if len(rs) < 5:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(rs) for _ in rs) / len(rs) for _ in range(n))
    return {"p5": means[int(n * 0.05)], "p50": means[n // 2], "p95": means[int(n * 0.95)],
            "prob_mean_gt_0": sum(m > 0 for m in means) / n}


def perturbations(strategy_name, factors=(0.8, 1.0, 1.2), max_runs=81):
    defaults = STRATEGIES[strategy_name].defaults
    keys = [k for k, v in defaults.items() if isinstance(v, (int, float)) and k != "rsi_len"]
    grids = []
    for k in keys:
        v = defaults[k]
        vals = sorted({(max(2, round(v * f)) if isinstance(v, int) else round(v * f, 4)) for f in factors})
        grids.append(vals)
    combos = list(itertools.product(*grids))
    if len(combos) > max_runs:
        rng = random.Random(3)
        combos = rng.sample(combos, max_runs)
    return [dict(zip(keys, c)) for c in combos]


def breakeven_move(fee, slip):
    """Price move needed for a round trip to net zero."""
    return ((1 + fee + slip) / (1 - fee - slip) - 1) * 100


def validate(strategy_name, bars_by_symbol, cfg_all, log_path=None):
    cfg = cfg_all["engine"]
    split, gates = cfg_all["split"], cfg_all["gates"]
    run = Runner(strategy_name, bars_by_symbol, cfg, log_path)
    first = min(b.t[0] for b in bars_by_symbol.values())
    last = max(b.t[-1] for b in bars_by_symbol.values())
    oos_start = ts(split["oos_start"])
    report = {"strategy": strategy_name, "params": STRATEGIES[strategy_name].defaults,
              "symbols": list(bars_by_symbol), "data_from": ymd(first), "data_to": ymd(last),
              "oos_start": split["oos_start"], "engine_cfg": cfg,
              "data_problems": [p for b in bars_by_symbol.values() for p in data_mod.check_quality(b)][:50]}

    _, report["dev"] = run("dev", trade_end_ts=oos_start - 86400)
    oos_res, report["oos"] = run("oos", trade_start_ts=oos_start)
    report["oos_buy_hold_pct"] = buy_and_hold(bars_by_symbol, oos_start, last, cfg["fee_rate"], cfg["slippage_rate"])
    report["dev_buy_hold_pct"] = buy_and_hold(bars_by_symbol, first, oos_start - 86400, cfg["fee_rate"], cfg["slippage_rate"])

    report["per_symbol_oos"] = {s: run(f"oos:{s}", symbols=[s], trade_start_ts=oos_start)[1] for s in bars_by_symbol}

    years = sorted({datetime.fromtimestamp(t, timezone.utc).year for b in bars_by_symbol.values() for t in b.t})
    report["by_year"] = {}
    for y in years:
        _, m = run(f"year:{y}", trade_start_ts=ts(f"{y}-01-01"), trade_end_ts=ts(f"{y}-12-31"))
        report["by_year"][y] = m

    report["cost_stress"] = {}
    for mult in (1.0, 1.5, 2.0):
        _, m = run(f"cost:{mult}", trade_start_ts=oos_start,
                   fee_rate=cfg["fee_rate"] * mult, slippage_rate=cfg["slippage_rate"] * mult)
        report["cost_stress"][str(mult)] = m

    _, report["delayed_entry_oos"] = run("delay2", trade_start_ts=oos_start, entry_delay=2)
    _, report["missed_fills_oos"] = run("miss20", trade_start_ts=oos_start, miss_rate=0.2)

    report["risk_levels_oos"] = {}
    for r in (0.25, 0.5, 1.0, 2.0):
        _, report["risk_levels_oos"][str(r)] = run(f"risk:{r}", trade_start_ts=oos_start, risk_pct=r)

    pert = []
    for p in perturbations(strategy_name):
        _, m = run("perturb", params=p, trade_start_ts=oos_start)
        pert.append({"params": p, "net_return_pct": m["net_return_pct"], "expectancy_r": m["expectancy_r"],
                     "trades": m["trades"], "max_drawdown_pct": m["max_drawdown_pct"]})
    report["perturbation"] = {
        "runs": len(pert),
        "profitable_share": sum(1 for x in pert if x["net_return_pct"] > 0) / len(pert) if pert else None,
        "worst_net_return_pct": min((x["net_return_pct"] for x in pert), default=None),
        "best_net_return_pct": max((x["net_return_pct"] for x in pert), default=None),
    }

    report["oos_regimes"] = regime_table(oos_res["trades"], bars_by_symbol)
    report["oos_bootstrap_r"] = bootstrap_expectancy(oos_res["trades"])
    report["oos_skips"] = _count(oos_res["log"])
    report["breakeven_move_pct"] = breakeven_move(cfg["fee_rate"], cfg["slippage_rate"])
    report["worked_example"] = worked_example(oos_res, cfg)
    report["total_backtests_run"] = run.count
    report["gates"] = evaluate_gates(report, gates)
    report["verdict"] = "PASS: eligible for paper trading" if all(g["pass"] for g in report["gates"]) \
        else "FAIL: do not trade; keep researching or paper trade only"
    return report


def _count(log):
    out = {}
    for e in log:
        key = f"{e['event']}:{e.get('reason', '')}".rstrip(":")
        out[key] = out.get(key, 0) + 1
    return out


def worked_example(res, cfg):
    trades = res["trades"]
    init = cfg["initial_equity"]
    gross = sum(t["gross_pnl"] for t in trades)
    fees = sum(t["fees"] for t in trades)
    slip = sum(t["slippage_cost"] for t in trades)
    net = sum(t["net_pnl"] for t in trades)
    one = 30.0
    move = 0.10
    f, s = cfg["fee_rate"], cfg["slippage_rate"]
    single = {
        "position_usd": one, "gross_move_pct": move * 100,
        "gross_profit": one * move,
        "entry_fee": one * f, "exit_fee": one * (1 + move) * f,
        "slippage": one * s + one * (1 + move) * s,
    }
    single["net_profit"] = single["gross_profit"] - single["entry_fee"] - single["exit_fee"] - single["slippage"]
    single["account_after"] = init + single["net_profit"]
    return {"oos_account": {"start": init, "gross_pnl": gross, "fees": fees, "slippage": slip,
                            "net_pnl": net, "end_equity_closed_trades": init + net,
                            "end_equity_marked": res["equity"][-1][1] if res["equity"] else init},
            "single_trade_example": single}


def _val(x):
    return x if x is not None else float("nan")


def evaluate_gates(r, g):
    oos, boot = r["oos"], r["oos_bootstrap_r"] or {}
    checks = [
        ("oos_trades", oos["trades"], ">=", g["oos_trades_min"]),
        ("oos_expectancy_r", _val(oos["expectancy_r"]), ">", 0.0),
        ("oos_profit_factor", _val(oos["profit_factor"]), ">=", g["oos_profit_factor_min"]),
        ("bootstrap_p5_expectancy_r", _val(boot.get("p5")), ">", 0.0),
        ("oos_max_drawdown_pct", oos["max_drawdown_pct"], "<=", g["max_drawdown_pct_max"]),
        ("cost_1.5x_profit_factor", _val(r["cost_stress"]["1.5"]["profit_factor"]), ">=", g["cost_15x_profit_factor_min"]),
        ("cost_2x_expectancy_r", _val(r["cost_stress"]["2.0"]["expectancy_r"]), ">", 0.0),
        ("delayed_entry_expectancy_r", _val(r["delayed_entry_oos"]["expectancy_r"]), ">", 0.0),
        ("perturbation_profitable_share", _val(r["perturbation"]["profitable_share"]), ">=", g["perturbation_profitable_share_min"]),
        ("symbols_profitable_oos", sum(1 for m in r["per_symbol_oos"].values() if m["net_return_pct"] > 0),
         ">=", g["symbols_profitable_min"]),
        ("years_profitable_share", sum(1 for m in r["by_year"].values() if m["net_return_pct"] > 0) / max(1, len(r["by_year"])),
         ">=", g["years_profitable_share_min"]),
    ]
    out = []
    for name, value, op, threshold in checks:
        ok = (not math.isnan(value)) and {">=": value >= threshold, ">": value > threshold, "<=": value <= threshold}[op]
        out.append({"gate": name, "value": value, "rule": f"{op} {threshold}", "pass": bool(ok)})
    return out


def fmt(v, nd=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if isinstance(v, float):
        return "inf" if math.isinf(v) else f"{v:.{nd}f}"
    return str(v)


def render_markdown(r):
    L = [f"# Backtest report: {r['strategy']}", "",
         "**SIMULATION RESULTS, NOT REAL TRADING.** Past results do not guarantee future results.", "",
         f"- Symbols: {', '.join(r['symbols'])}  |  Data: {r['data_from']} to {r['data_to']} (daily, UTC)",
         f"- Out-of-sample starts: {r['oos_start']}  |  Backtests run to produce this report: {r['total_backtests_run']}",
         f"- Params: `{json.dumps(r['params'])}`",
         f"- Costs per side: fee {r['engine_cfg']['fee_rate'] * 100:.2f}% + slippage {r['engine_cfg']['slippage_rate'] * 100:.2f}%"
         f"  |  break-even move per round trip: {r['breakeven_move_pct']:.2f}%",
         f"- Risk per trade: {r['engine_cfg']['risk_pct']}% of equity, max {r['engine_cfg']['max_alloc_pct']}% per position",
         "", f"## Verdict: {r['verdict']}", "", "| gate | value | rule | pass |", "|---|---|---|---|"]
    for g in r["gates"]:
        L.append(f"| {g['gate']} | {fmt(g['value'], 3)} | {g['rule']} | {'PASS' if g['pass'] else 'FAIL'} |")
    keys = [("trades", 0), ("net_return_pct", 2), ("cagr_pct", 2), ("win_rate_pct", 1), ("avg_win_usd", 3),
            ("avg_loss_usd", 3), ("expectancy_usd", 4), ("expectancy_r", 3), ("profit_factor", 2),
            ("max_drawdown_pct", 2), ("longest_drawdown_days", 0), ("recovery_factor", 2),
            ("sharpe_daily_ann", 2), ("fees_usd", 3), ("slippage_usd", 3), ("avg_bars_held", 1)]
    L += ["", "## Development vs out-of-sample (account level, $100 start)", "", "| metric | dev | oos |", "|---|---|---|"]
    for k, nd in keys:
        L.append(f"| {k} | {fmt(r['dev'].get(k), nd)} | {fmt(r['oos'].get(k), nd)} |")
    L.append(f"| buy & hold (90% invested, after costs) | {fmt(r['dev_buy_hold_pct'])}% | {fmt(r['oos_buy_hold_pct'])}% |")
    L += ["", "## Per symbol (out-of-sample)", "", "| symbol | trades | net % | PF | max DD % | exp R |", "|---|---|---|---|---|---|"]
    for s, m in r["per_symbol_oos"].items():
        L.append(f"| {s} | {m['trades']} | {fmt(m['net_return_pct'])} | {fmt(m['profit_factor'])} | {fmt(m['max_drawdown_pct'])} | {fmt(m['expectancy_r'], 3)} |")
    L += ["", "## Walk-forward by calendar year (fixed parameters)", "", "| year | trades | net % | PF | max DD % |", "|---|---|---|---|---|"]
    for y, m in r["by_year"].items():
        L.append(f"| {y} | {m['trades']} | {fmt(m['net_return_pct'])} | {fmt(m['profit_factor'])} | {fmt(m['max_drawdown_pct'])} |")
    L += ["", "## Stress tests (out-of-sample)", "", "| test | trades | net % | PF | exp R | max DD % |", "|---|---|---|---|---|---|"]
    rows = [(f"costs x{k}", m) for k, m in r["cost_stress"].items()] + \
           [("entry delayed 1 extra bar", r["delayed_entry_oos"]), ("20% of entries missed", r["missed_fills_oos"])]
    for name, m in rows:
        L.append(f"| {name} | {m['trades']} | {fmt(m['net_return_pct'])} | {fmt(m['profit_factor'])} | {fmt(m['expectancy_r'], 3)} | {fmt(m['max_drawdown_pct'])} |")
    p = r["perturbation"]
    L += ["", f"Parameter perturbation (each numeric param x0.8 / x1.0 / x1.2, {p['runs']} runs): "
          f"{fmt((p['profitable_share'] or 0) * 100, 0)}% profitable, worst {fmt(p['worst_net_return_pct'])}%, best {fmt(p['best_net_return_pct'])}%."]
    b = r["oos_bootstrap_r"]
    if b:
        L.append(f"Bootstrap of mean R per trade: 5th pct {b['p5']:.3f}, median {b['p50']:.3f}, 95th {b['p95']:.3f}, P(mean>0) = {b['prob_mean_gt_0']:.2f}.")
    L += ["", "## Risk per trade comparison (out-of-sample)", "", "| risk % | net % | max DD % | trades |", "|---|---|---|---|"]
    for k, m in r["risk_levels_oos"].items():
        L.append(f"| {k} | {fmt(m['net_return_pct'])} | {fmt(m['max_drawdown_pct'])} | {m['trades']} |")
    L += ["", "## Regimes at entry (out-of-sample)", "", "| regime | trades | win % | exp R | net $ |", "|---|---|---|---|---|"]
    for k, v in sorted(r["oos_regimes"].items()):
        L.append(f"| {k} | {v['trades']} | {fmt(v['win_rate_pct'], 0)} | {fmt(v['expectancy_r'], 3)} | {fmt(v['net_pnl'], 3)} |")
    w = r["worked_example"]
    a, s1 = w["oos_account"], w["single_trade_example"]
    L += ["", "## $100 worked example", "",
          f"Out-of-sample account: start ${a['start']:.2f}, gross P/L ${a['gross_pnl']:.2f}, fees -${a['fees']:.2f}, "
          f"slippage -${a['slippage']:.2f}, net ${a['net_pnl']:.2f}, ending equity ${a['end_equity_marked']:.2f}.", "",
          f"Single trade: ${s1['position_usd']:.0f} position, +{s1['gross_move_pct']:.0f}% move = ${s1['gross_profit']:.2f} gross; "
          f"entry fee -${s1['entry_fee']:.2f}, exit fee -${s1['exit_fee']:.2f}, slippage -${s1['slippage']:.2f}; "
          f"net ${s1['net_profit']:.2f}; account ${s1['account_after']:.2f}.",
          "", "## Order skips (out-of-sample)", "", json.dumps(r["oos_skips"]),
          "", "## Data problems found", ""]
    L += [f"- {p}" for p in r["data_problems"]] or ["- none"]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="A_trend_breakout", choices=sorted(STRATEGIES))
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--csv-dir", help="load <SYMBOL>_1d.csv or <SYMBOL>.csv from here instead of downloading")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    symbols = args.symbols or cfg["symbols"]
    bars = {}
    for s in symbols:
        if args.csv_dir:
            d = Path(args.csv_dir)
            path = next((p for p in (d / f"{s}_1d.csv", d / f"{s}.csv") if p.exists()), None)
            if not path:
                raise SystemExit(f"no CSV for {s} in {d}")
            bars[s] = data_mod.load_csv(path, s)
        else:
            bars[s] = data_mod.load_or_fetch(s, cfg["data_start"], refresh=args.refresh)
    report = validate(args.strategy, bars, cfg, log_path=REPORTS / "param_log.jsonl")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{args.strategy}_{stamp}.json").write_text(json.dumps(report, indent=2, default=str))
    md = render_markdown(report)
    (REPORTS / f"{args.strategy}_{stamp}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
