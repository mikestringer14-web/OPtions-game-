"""Portfolio backtest engine with conservative fills.

Fill model (all deliberate, all conservative):
  * Signals use the completed daily bar i. Entries fill at the OPEN of bar i+delay, plus slippage.
  * Stops are checked on every bar's low. A gap below the stop fills at the open, not the stop.
  * A position entered at a bar's open can be stopped out on that same bar.
  * Fees are charged on both sides as a fraction of notional (taker by default).
  * Orders under the exchange minimum notional are skipped and logged.
  * Missed fills can be simulated with a seeded RNG.
"""
import math
import random
from copy import deepcopy

DEFAULT_CFG = {
    "initial_equity": 100.0,
    "risk_pct": 0.5,               # % of equity lost if the stop is hit (before slippage/gaps)
    "max_alloc_pct": 30.0,         # max notional per position, % of equity
    "max_total_exposure_pct": 90.0,
    "max_positions": 3,
    "fee_rate": 0.006,             # per side. Coinbase Advanced lowest tier taker (verify your tier)
    "slippage_rate": 0.001,        # per side, on top of the fee (spread + impact)
    "min_notional": 1.0,           # USD
    "entry_delay": 1,              # bars after the signal bar
    "miss_rate": 0.0,              # fraction of entries that never fill
    "seed": 7,
    "halt_drawdown_pct": 25.0,     # stop opening trades beyond this drawdown from peak
    "trade_start_ts": None,        # entries only from signal bars at/after this epoch
    "trade_end_ts": None,          # positions force-closed at the last bar at/before this epoch
    "blocked_windows": [],         # external kill switch: [[start_ts, end_ts or None], ...] no new entries
}


def run(strategies_by_symbol, cfg=None):
    """strategies_by_symbol: {symbol: prepared Strategy}. Returns dict with trades, equity, log."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    rng = random.Random(cfg["seed"])
    fee, slip = cfg["fee_rate"], cfg["slippage_rate"]

    index = {s: {t: i for i, t in enumerate(st.bars.t)} for s, st in strategies_by_symbol.items()}
    timeline = sorted({t for st in strategies_by_symbol.values() for t in st.bars.t})
    start_ts, end_ts = cfg["trade_start_ts"], cfg["trade_end_ts"]
    if end_ts is not None:
        timeline = [t for t in timeline if t <= end_ts]

    cash = cfg["initial_equity"]
    positions, pending_entry, pending_exit = {}, {}, set()
    trades, equity_curve, log = [], [], []
    last_close = {}
    peak = cash
    halted = False
    equity = cash

    def close_position(sym, price, t, reason):
        nonlocal cash
        pos = positions.pop(sym)
        fill = price * (1 - slip)
        proceeds = pos["qty"] * fill
        exit_fee = proceeds * fee
        cash += proceeds - exit_fee
        gross = pos["qty"] * (price - pos["entry_ref"])
        net = proceeds - exit_fee - pos["cost"]
        trades.append({
            "symbol": sym, "entry_ts": pos["entry_ts"], "exit_ts": t, "entry_price": pos["fill"],
            "exit_price": fill, "qty": pos["qty"], "notional": pos["notional"],
            "fees": pos["entry_fee"] + exit_fee,
            "slippage_cost": pos["qty"] * (pos["fill"] - pos["entry_ref"]) + pos["qty"] * (price - fill),
            "gross_pnl": gross, "net_pnl": net, "ret": net / pos["notional"],
            "r_multiple": net / pos["risk_usd"] if pos["risk_usd"] > 0 else 0.0,
            "bars_held": pos["bars"], "reason": reason, "signal_index": pos["signal_index"],
        })

    for t in timeline:
        for sym, st in strategies_by_symbol.items():
            i = index[sym].get(t)
            if i is None:
                continue
            b = st.bars
            o, h, l, c = b.o[i], b.h[i], b.l[i], b.c[i]

            # 1) scheduled exit at this open
            if sym in pending_exit and sym in positions:
                pending_exit.discard(sym)
                close_position(sym, o, t, "rule_exit")

            # 2) scheduled entry at this open
            if sym in pending_entry and pending_entry[sym]["fill_index"] == i:
                sig = pending_entry.pop(sym)
                fill = o * (1 + slip)
                stop = st.initial_stop(sig["signal_index"], fill)
                reason = None
                if halted:
                    reason = "halted"
                elif stop >= fill or stop <= 0:
                    reason = "invalid_stop"
                elif len(positions) >= cfg["max_positions"]:
                    reason = "max_positions"
                if reason is None:
                    risk_usd = equity * cfg["risk_pct"] / 100.0
                    qty = risk_usd / (fill - stop)
                    exposure = sum(p["qty"] * last_close.get(s, p["fill"]) for s, p in positions.items())
                    cap = min(equity * cfg["max_alloc_pct"] / 100.0,
                              equity * cfg["max_total_exposure_pct"] / 100.0 - exposure,
                              cash / (1 + fee))
                    notional = min(qty * fill, cap)
                    if notional < cfg["min_notional"]:
                        reason = "below_min_notional"
                if reason:
                    log.append({"ts": t, "symbol": sym, "event": "entry_skipped", "reason": reason})
                else:
                    qty = notional / fill
                    entry_fee = notional * fee
                    cash -= notional + entry_fee
                    positions[sym] = {"qty": qty, "fill": fill, "entry_ref": o, "notional": notional,
                                      "entry_fee": entry_fee, "cost": notional + entry_fee, "stop": stop,
                                      "risk_usd": qty * (fill - stop), "entry_ts": t, "entry_index": i,
                                      "signal_index": sig["signal_index"], "bars": 0}

            # 3) stop check during this bar
            if sym in positions:
                pos = positions[sym]
                if o <= pos["stop"]:
                    close_position(sym, o, t, "stop_gap")
                elif l <= pos["stop"]:
                    close_position(sym, pos["stop"], t, "stop")

            # 4) end of bar: manage open position or look for a new signal
            last_close[sym] = c
            if sym in positions:
                pos = positions[sym]
                pos["bars"] += 1
                if end_ts is not None and t == timeline[-1]:
                    close_position(sym, c, t, "end_of_test")
                    continue
                pos["stop"] = max(pos["stop"], st.update_stop(i, pos))
                if st.exit_at_close(i, pos):
                    pending_exit.add(sym)
            elif sym not in pending_entry and i >= st.warmup() and (start_ts is None or t >= start_ts):
                blocked = any(a < t and (z is None or t <= z) for a, z in cfg["blocked_windows"])
                if st.entry(i) and not halted and not blocked:
                    if rng.random() < cfg["miss_rate"]:
                        log.append({"ts": t, "symbol": sym, "event": "entry_missed"})
                    elif i + cfg["entry_delay"] < len(b):
                        pending_entry[sym] = {"signal_index": i, "fill_index": i + cfg["entry_delay"]}

        equity = cash + sum(p["qty"] * last_close[s] for s, p in positions.items())
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        if dd >= cfg["halt_drawdown_pct"] and not halted:
            halted = True
            log.append({"ts": t, "event": "halt", "reason": f"drawdown {dd:.1f}%"})
        if start_ts is None or t >= start_ts:
            equity_curve.append((t, equity))

    return {"trades": trades, "equity": equity_curve, "log": log, "cfg": cfg, "halted": halted,
            "open_positions": deepcopy(positions), "pending_entries": deepcopy(pending_entry),
            "pending_exits": sorted(pending_exit), "last_close": dict(last_close)}


def metrics(result):
    trades, eq = result["trades"], result["equity"]
    init = eq[0][1] if eq else result["cfg"]["initial_equity"]
    final = eq[-1][1] if eq else init
    wins = [x for x in trades if x["net_pnl"] > 0]
    losses = [x for x in trades if x["net_pnl"] <= 0]
    gross_win = sum(x["net_pnl"] for x in wins)
    gross_loss = -sum(x["net_pnl"] for x in losses)
    peak, max_dd, dd_start, longest, cur_start = -1, 0.0, None, 0, None
    for t, e in eq:
        if e >= peak:
            peak, cur_start = e, t
        else:
            max_dd = max(max_dd, (peak - e) / peak)
            longest = max(longest, (t - cur_start) // 86400)
    days = (eq[-1][0] - eq[0][0]) / 86400 if len(eq) > 1 else 0
    rets = [(eq[k][1] / eq[k - 1][1] - 1) for k in range(1, len(eq)) if eq[k - 1][1] > 0]
    mean = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    net = final / init - 1 if init else 0.0
    cagr = (final / init) ** (365 / days) - 1 if days > 30 and final > 0 else None
    in_mkt = sum(x["bars_held"] for x in trades)
    return {
        "trades": len(trades),
        "net_return_pct": net * 100,
        "cagr_pct": cagr * 100 if cagr is not None else None,
        "final_equity": final,
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else None,
        "avg_win_usd": gross_win / len(wins) if wins else None,
        "avg_loss_usd": -gross_loss / len(losses) if losses else None,
        "expectancy_usd": sum(x["net_pnl"] for x in trades) / len(trades) if trades else None,
        "expectancy_r": sum(x["r_multiple"] for x in trades) / len(trades) if trades else None,
        "avg_trade_ret_pct": sum(x["ret"] for x in trades) / len(trades) * 100 if trades else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else None),
        "max_drawdown_pct": max_dd * 100,
        "longest_drawdown_days": longest,
        "recovery_factor": (net / max_dd) if max_dd > 0 else None,
        "sharpe_daily_ann": (mean / sd * math.sqrt(365)) if sd > 0 else None,
        "fees_usd": sum(x["fees"] for x in trades),
        "slippage_usd": sum(x["slippage_cost"] for x in trades),
        "avg_bars_held": in_mkt / len(trades) if trades else None,
        "days": days,
    }
