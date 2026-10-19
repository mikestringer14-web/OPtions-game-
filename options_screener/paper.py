"""PAPER trading. The ONLY module in options_screener that may create, place or cancel orders.

    python -m options_screener.paper --report reports/screen_YYYYMMDD.md --paper

Refuses unless ALL of these hold:
  1. the --paper flag is given;
  2. reports/PASS.json exists, says PASS, came from a VERIFIED backtest, and its config hash matches
     the current config (any change to gates/plan/costs re-locks paper mode);
  3. the TWS/Gateway port is a paper port (7497 TWS, 4002 Gateway);
  4. every account the gateway reports starts with "DU", and IBKR_PAPER_ACCOUNT is set, starts with
     "DU" and is one of them. ("DU" = IBKR paper account numbers as shown in Client Portal; confirm
     yours there. IBKR's API docs do not publish this rule, so it is enforced as a hard refusal.)
Orders: buy-to-open single-leg calls/puts only, limit at mid, cancel after the timeout, never
market, never auto-retry. Every event goes to logs/paper_trades.jsonl.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Optional

from . import config as config_mod
from .config import LOGS, PAPER_PORTS, PASS_FILE, config_hash, env
from .models import ET

PAPER_PREFIX = "DU"


class PaperRefused(RuntimeError):
    pass


def check_pass(cfg: dict, pass_file: Path = PASS_FILE) -> dict:
    if not pass_file.exists():
        raise PaperRefused("paper mode is locked: no PASS file (run the backtest; it must PASS on real option data)")
    data = json.loads(pass_file.read_text())
    if data.get("verdict") != "PASS":
        raise PaperRefused("PASS file does not say PASS")
    if data.get("mode") != "VERIFIED":
        raise PaperRefused(f"PASS came from a {data.get('mode')} backtest; only VERIFIED data unlocks paper")
    if data.get("config_hash") != config_hash(cfg):
        raise PaperRefused("config changed since the PASS backtest; re-run the backtest")
    return data


def verify_paper_account(ib, port: int, expected: str) -> str:
    if port not in PAPER_PORTS:
        raise PaperRefused(f"port {port} is not a paper port {sorted(PAPER_PORTS)}")
    if not expected or not expected.startswith(PAPER_PREFIX):
        raise PaperRefused("IBKR_PAPER_ACCOUNT must be set to your paper account (starts with DU)")
    accounts = list(ib.managedAccounts() or [])
    if not accounts:
        raise PaperRefused("gateway reported no accounts")
    live = [a for a in accounts if not a.startswith(PAPER_PREFIX)]
    if live:
        raise PaperRefused("gateway session includes a non-paper account; log in to the PAPER account only")
    if expected not in accounts:
        raise PaperRefused("IBKR_PAPER_ACCOUNT is not one of the gateway's accounts")
    return expected


class PaperLog:
    def __init__(self, path: Path = LOGS / "paper_trades.jsonl"):
        self.path = path

    def write(self, event: str, **fields) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(ET).isoformat(timespec="seconds"), "event": event, "paper": True, **fields}
        rec.pop("account", None)                       # never log account numbers
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def load_candidates(report: Path) -> list[dict]:
    js = report.with_suffix(".json")
    if not js.exists():
        raise PaperRefused(f"{js} not found (the screen writes it next to the .md)")
    data = json.loads(js.read_text())
    if data.get("mock"):
        raise PaperRefused("this is a MOCK report; refusing to paper-trade synthetic candidates")
    return data["candidates"]


def _round_tick(px: float) -> float:
    return round(round(px / 0.01) * 0.01, 2)


class PaperTrader:
    def __init__(self, ib, account: str, cfg: dict, log: PaperLog, now: Callable[[], datetime] = lambda: datetime.now(ET)):
        self.ib, self.account, self.cfg, self.log, self.now = ib, account, cfg, log, now

    def _quote(self, contract):
        t = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(2)
        self.ib.cancelMktData(contract)
        bid, ask = t.bid, t.ask
        if not (bid and ask and bid > 0 and ask > 0):
            return None
        return bid, ask

    def _wait_fill(self, trade, seconds: float) -> bool:
        waited = 0.0
        while waited < seconds:
            if trade.orderStatus.status == "Filled":
                return True
            self.ib.sleep(1)
            waited += 1
        return trade.orderStatus.status == "Filled"

    def trade(self, cand: dict, option_contract, stock_contract, trigger: Callable[[], Optional[bool]],
              exit_signal: Callable[[float, float, float], Optional[str]]) -> dict:
        """One candidate. `trigger()` -> True when the opening-range break confirms direction, None when
        the entry deadline passed. `exit_signal(mid, spread_pct, entry_mid)` -> reason or None."""
        from ib_async import LimitOrder

        c, p, fq = self.cfg["contract"], self.cfg["plan"], self.cfg["fill_quality"]
        snap = cand["snapshot"]["contract"]
        if snap["right"] not in ("C", "P"):
            raise PaperRefused("only single-leg calls/puts")
        dte = (date.fromisoformat(str(snap["expiry"])) - self.now().date()).days
        if dte < 1 and not c["allow_0dte"]:
            raise PaperRefused("0DTE is disabled")
        while True:
            fired = trigger()
            if fired is None:
                self.log.write("no_trigger", symbol=cand["symbol"])
                return {"status": "no_trigger"}
            if fired:
                break
            self.ib.sleep(15)
        q = self._quote(option_contract)
        if q is None:
            self.log.write("no_quote", symbol=cand["symbol"])
            return {"status": "no_quote"}
        bid, ask = q
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        if spread_pct > fq["max_morning_spread_pct"]:
            self.log.write("skipped_spread", symbol=cand["symbol"], spread_pct=round(spread_pct, 2))
            return {"status": "skipped_spread"}
        lmt = _round_tick(mid)
        order = LimitOrder("BUY", c["contracts"], lmt, account=self.account, tif="DAY")
        placed = self.now()
        trade = self.ib.placeOrder(option_contract, order)
        self.log.write("entry_placed", symbol=cand["symbol"], contract=snap, limit=lmt, bid=bid, ask=ask, mid=mid)
        if not self._wait_fill(trade, p["fill_timeout_seconds"]):
            self.ib.cancelOrder(order)
            self.log.write("entry_cancelled_no_fill", symbol=cand["symbol"], waited_s=p["fill_timeout_seconds"])
            return {"status": "no_fill"}
        fill_px = trade.orderStatus.avgFillPrice
        self.log.write("entry_filled", symbol=cand["symbol"], fill_price=fill_px, mid_at_placement=mid,
                       fill_vs_mid=round(fill_px - mid, 4), seconds_to_fill=(self.now() - placed).total_seconds())
        th, tm = (int(x) for x in p["time_stop"].split(":"))
        reason = None
        while reason is None:
            if self.now().time() >= time(th, tm):
                reason = "time_stop"
                break
            q = self._quote(option_contract)
            if q:
                b, a = q
                m = (b + a) / 2
                reason = exit_signal(m, (a - b) / m * 100, mid)
            if reason is None:
                self.ib.sleep(5)
        q = self._quote(option_contract)
        exit_lmt = _round_tick(q[0]) if q else _round_tick(mid * 0.5)
        exit_order = LimitOrder("SELL", c["contracts"], exit_lmt, account=self.account, tif="DAY")
        exit_trade = self.ib.placeOrder(option_contract, exit_order)
        self.log.write("exit_placed", symbol=cand["symbol"], reason=reason, limit=exit_lmt)
        if not self._wait_fill(exit_trade, p["fill_timeout_seconds"]):
            self.log.write("EXIT_NOT_FILLED", symbol=cand["symbol"], reason=reason,
                           note="not retried automatically; close it manually in the paper account")
            return {"status": "exit_unfilled", "reason": reason}
        out = exit_trade.orderStatus.avgFillPrice
        self.log.write("exit_filled", symbol=cand["symbol"], reason=reason, fill_price=out, entry_fill=fill_px,
                       pnl_per_contract=round((out - fill_px) * 100, 2))
        return {"status": "closed", "reason": reason, "entry": fill_px, "exit": out}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PAPER trading only (requires a PASS backtest)")
    ap.add_argument("--report", required=True)
    ap.add_argument("--paper", action="store_true", help="required: confirms PAPER mode")
    args = ap.parse_args(argv)
    config_mod.load_env()
    cfg = config_mod.load()
    try:
        if not args.paper:
            raise PaperRefused("--paper flag is required")
        check_pass(cfg)
        cands = load_candidates(Path(args.report))
        from ib_async import IB

        port = int(env("IBKR_PORT", "4002"))
        if port not in PAPER_PORTS:
            raise PaperRefused(f"port {port} is not a paper port")
        ib = IB()
        ib.connect(env("IBKR_HOST", "127.0.0.1"), port, clientId=int(env("IBKR_CLIENT_ID", "18")), timeout=15)
        account = verify_paper_account(ib, port, env("IBKR_PAPER_ACCOUNT"))
    except PaperRefused as e:
        print(f"REFUSED: {e}")
        return 3
    print(f"PAPER mode on {account[:2]}****: {len(cands)} candidates, handled one at a time.")
    trader = PaperTrader(ib, account, cfg, PaperLog())
    try:
        for cand in cands:
            stock, opt = _contracts(ib, cand)
            res = trader.trade(cand, opt, stock, _trigger_fn(ib, stock, cand, cfg), _exit_fn(ib, stock, cand, cfg))
            print(cand["symbol"], res)
    finally:
        ib.disconnect()
    return 0


def _contracts(ib, cand):
    from ib_async import Option, Stock

    k = cand["snapshot"]["contract"]
    stock = Stock(cand["symbol"], "SMART", "USD")
    opt = Option(cand["symbol"], str(k["expiry"]).replace("-", ""), float(k["strike"]), k["right"], "SMART")
    ib.qualifyContracts(stock, opt)
    return stock, opt


def _today_bars(ib, stock):
    bars = ib.reqHistoricalData(stock, endDateTime="", durationStr="3600 S", barSizeSetting="1 min",
                                whatToShow="TRADES", useRTH=True, formatDate=2)
    today = datetime.now(ET).date()
    return [b for b in bars if b.date.astimezone(ET).date() == today]


def _opening_range(bars, minutes):
    rng = [b for b in bars if b.date.astimezone(ET).time() < time(9, 30 + minutes)]
    return (max(b.high for b in rng), min(b.low for b in rng)) if rng else None


def _trigger_fn(ib, stock, cand, cfg):
    p = cfg["plan"]
    dh, dm = (int(x) for x in p["entry_deadline"].split(":"))

    def trigger():
        now = datetime.now(ET).time()
        if now >= time(dh, dm):
            return None
        if now < time(9, 30 + p["entry_after_minutes"]):
            return False
        bars = _today_bars(ib, stock)
        orng = _opening_range(bars, p["entry_after_minutes"])
        if not orng or not bars:
            return False
        last = bars[-1].close
        return last > orng[0] if cand["direction"] == "bull" else last < orng[1]
    return trigger


def _exit_fn(ib, stock, cand, cfg):
    p = cfg["plan"]
    hist_spread = (cand.get("fill") or {}).get("median_spread_pct") or cfg["fill_quality"]["proxy_spread_pct"]

    def exit_signal(mid, spread_pct, entry_mid):
        if mid >= entry_mid * (1 + p["target_pct"] / 100):
            return "target"
        if mid <= entry_mid * (1 - p["stop_pct"] / 100):
            return "stop"
        if spread_pct > hist_spread * p["spread_widen_multiple"]:
            return "spread_widened"
        bars = _today_bars(ib, stock)
        orng = _opening_range(bars, p["entry_after_minutes"])
        if orng and bars:
            last = bars[-1].close
            if (cand["direction"] == "bull" and last < orng[0]) or (cand["direction"] == "bear" and last > orng[1]):
                return "range_reclaimed"
        return None
    return exit_signal


if __name__ == "__main__":
    raise SystemExit(main())
