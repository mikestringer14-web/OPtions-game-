"""Daily paper trader. No API keys, no orders: public market data only.

Run once a day after the 00:00 UTC daily close (cron example in README):
    python -m rt.paper            # process new candles, write journal + report
    python -m rt.paper --status
    python -m rt.paper --resume   # clear a halt after you have reviewed it

How it stays identical to the backtest: every run replays the SAME engine over the full
history with trading allowed from the paper start date. The engine is deterministic, so
a re-run on the same data gives the same trades (no duplicate signals), and anything new
since the last run is appended to the journal. Real spreads are sampled at run time and
logged so they can be compared against the slippage assumption.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import data as data_mod
from . import engine
from .validate import build, load_config, ymd

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
TICKER = "https://api.exchange.coinbase.com/products/{}/ticker"


def _now():
    return datetime.now(timezone.utc)


def load_state():
    p = PAPER / "state.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_state(state):
    PAPER.mkdir(parents=True, exist_ok=True)
    tmp = PAPER / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(PAPER / "state.json")


def journal(event):
    PAPER.mkdir(parents=True, exist_ok=True)
    with open(PAPER / "journal.jsonl", "a") as f:
        f.write(json.dumps({"logged_at": _now().isoformat(timespec="seconds"), **event}, default=str) + "\n")


def alert(msg, state):
    state.setdefault("alerts", []).append({"at": _now().isoformat(timespec="seconds"), "msg": msg})
    PAPER.mkdir(parents=True, exist_ok=True)
    (PAPER / "ALERT.txt").write_text(msg + "\n")
    journal({"event": "alert", "msg": msg})


def halt(state, now):
    state["halted"] = True
    state["halt_windows"].append([int(now.timestamp()), None])


def sample_spread(product):
    try:
        r = requests.get(TICKER.format(product), timeout=10, headers={"User-Agent": "trading-research/1.0"})
        r.raise_for_status()
        j = r.json()
        bid, ask = float(j["bid"]), float(j["ask"])
        return {"bid": bid, "ask": ask, "half_spread_pct": (ask - bid) / ((ask + bid) / 2) / 2 * 100}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def fetch_bars(symbols, cfg, csv_dir=None):
    out = {}
    for s in symbols:
        if csv_dir:
            out[s] = data_mod.load_csv(Path(csv_dir) / f"{s}_1d.csv", s)
        else:
            out[s] = data_mod.fetch_coinbase_daily(s, cfg["data_start"])
            data_mod.save_csv(out[s], data_mod.DATA_DIR / f"{s}_1d.csv")
    return out


def run_once(cfg_all, bars=None, now=None, csv_dir=None, sample_spreads=True):
    now = now or _now()
    pcfg = cfg_all["paper"]
    symbols = cfg_all["symbols"]
    state = load_state() or {"started_at": now.strftime("%Y-%m-%d"), "seen_trades": 0, "seen_log": 0,
                             "halted": False, "halt_windows": [], "consecutive_errors": 0, "last_equity": None,
                             "alerts": []}
    start_ts = int(datetime.fromisoformat(state["started_at"]).replace(tzinfo=timezone.utc).timestamp())

    try:
        bars = bars or fetch_bars(symbols, cfg_all, csv_dir)
    except Exception as e:
        state["consecutive_errors"] += 1
        alert(f"data fetch failed ({state['consecutive_errors']}x): {type(e).__name__}: {e}", state)
        if state["consecutive_errors"] >= pcfg["max_consecutive_errors"] and not state["halted"]:
            halt(state, now)
            alert("HALTED: repeated data errors. Fix, then run with --resume.", state)
        save_state(state)
        return state

    stale = [s for s, b in bars.items() if not len(b) or (now.timestamp() - (b.t[-1] + 86400)) / 3600 > pcfg["max_data_age_hours"]]
    if stale:
        alert(f"stale or missing data for {stale}; nothing processed today", state)
        save_state(state)
        return state
    state["consecutive_errors"] = 0

    ecfg = {**cfg_all["engine"], "trade_start_ts": start_ts, "blocked_windows": state["halt_windows"]}
    res = engine.run(build(pcfg["strategy"], bars), ecfg)
    m = engine.metrics(res)

    new_trades = res["trades"][state["seen_trades"]:]
    new_log = res["log"][state["seen_log"]:]
    for t in new_trades:
        journal({"event": "paper_trade_closed", **t, "entry_date": ymd(t["entry_ts"]), "exit_date": ymd(t["exit_ts"])})
    for e in new_log:
        journal({"event": "engine_" + e["event"], **e})
    state["seen_trades"], state["seen_log"] = len(res["trades"]), len(res["log"])

    equity = res["equity"][-1][1] if res["equity"] else ecfg["initial_equity"]
    if state["last_equity"]:
        day_change = (equity / state["last_equity"] - 1) * 100
        if day_change <= -pcfg["daily_loss_halt_pct"] and not state["halted"]:
            halt(state, now)
            alert(f"HALTED: equity fell {day_change:.2f}% since last run. Review, then --resume.", state)
    if res["halted"] and not state["halted"]:
        halt(state, now)
        alert("HALTED: drawdown limit reached inside the strategy. Review, then --resume.", state)
    state["last_equity"] = equity

    spreads = {s: sample_spread(s) for s in symbols} if sample_spreads else {}
    intended = [{"symbol": s, "action": "BUY at next open", "signal_date": ymd(bars[s].t[p["signal_index"]])}
                for s, p in res["pending_entries"].items()]
    intended += [{"symbol": s, "action": "SELL at next open (rule exit)"} for s in res["pending_exits"]]
    positions = [{"symbol": s, "entry_date": ymd(p["entry_ts"]), "entry": p["fill"], "qty": p["qty"],
                  "stop": p["stop"], "last_close": res["last_close"].get(s),
                  "unrealized_net_usd": p["qty"] * res["last_close"].get(s, p["fill"]) * (1 - ecfg["fee_rate"]) - p["cost"]}
                 for s, p in res["open_positions"].items()]
    snap = {"event": "daily_snapshot", "date": now.strftime("%Y-%m-%d"), "equity": equity,
            "metrics_since_start": m, "positions": positions, "intended_orders": intended,
            "spreads": spreads, "halted": state["halted"]}
    journal(snap)
    write_report(snap, state)
    state["last_run"] = now.isoformat(timespec="seconds")
    save_state(state)
    return state


def write_report(snap, state):
    m = snap["metrics_since_start"]
    L = [f"# Paper trading report {snap['date']} (SIMULATED, no real orders)", "",
         f"Equity ${snap['equity']:.2f} | trades {m['trades']} | net {m['net_return_pct']:.2f}% | "
         f"max DD {m['max_drawdown_pct']:.2f}% | halted: {state['halted']}", "", "## Open positions"]
    L += [f"- {p['symbol']}: entry {p['entry']:.6g} on {p['entry_date']}, stop {p['stop']:.6g}, "
          f"last {p['last_close']:.6g}, unrealized after exit fee ${p['unrealized_net_usd']:.2f}"
          for p in snap["positions"]] or ["- none"]
    L += ["", "## Intended orders for next open"] + ([f"- {o['symbol']}: {o['action']}" for o in snap["intended_orders"]] or ["- none"])
    L += ["", "## Spreads now (compare to slippage assumption)"]
    L += [f"- {s}: half-spread {v['half_spread_pct']:.4f}%" if "half_spread_pct" in v else f"- {s}: {v.get('error')}"
          for s, v in snap["spreads"].items()] or ["- not sampled"]
    if state.get("alerts"):
        L += ["", "## Recent alerts"] + [f"- {a['at']}: {a['msg']}" for a in state["alerts"][-5:]]
    (PAPER / "daily_report.md").write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--csv-dir")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.status:
        print((PAPER / "daily_report.md").read_text() if (PAPER / "daily_report.md").exists() else "no report yet")
        return
    if args.resume:
        state = load_state()
        if state:
            if state["halt_windows"] and state["halt_windows"][-1][1] is None:
                state["halt_windows"][-1][1] = int(_now().timestamp())
            state["halted"], state["consecutive_errors"] = False, 0
            save_state(state)
            (PAPER / "ALERT.txt").unlink(missing_ok=True)
            journal({"event": "resumed_by_user"})
        print("resumed")
        return
    state = run_once(cfg, csv_dir=args.csv_dir)
    print((PAPER / "daily_report.md").read_text() if (PAPER / "daily_report.md").exists() else json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
