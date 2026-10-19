"""Evening screen. RESEARCH ONLY: reads data, writes a report, never places orders.

    python -m options_screener.screen --date next            # live IBKR paper connection, read-only
    python -m options_screener.screen --date next --mock     # synthetic data demo

A candidate must pass ALL THREE gates: (A) catalyst, (B) 5%+ move potential, (C) fill quality.
Gates run in that order so the expensive per-contract checks only happen for names that matter.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean
from typing import Optional

from . import config as config_mod
from . import fill_quality, market_calendar, plan, pricing, signals
from .models import TORONTO, Candidate
from .providers.base import AsOfView, LookaheadError, NullCatalysts, NullNews, ProviderUnavailable


@dataclass
class ScreenResult:
    asof: date
    target: date
    candidates: list = field(default_factory=list)      # passed A, B and C (ranked, top N)
    near_misses: list = field(default_factory=list)     # passed A and B, failed only C
    passed_ab: list = field(default_factory=list)       # everything that passed A and B (backtest "without C")
    rejected: Counter = field(default_factory=Counter)
    errors: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    gate_c_mode: str = "ENFORCED"


def previous_sessions(asof: date, n: int) -> list[date]:
    out, d = [], asof
    while len(out) < n:
        out.append(d)
        d = market_calendar.previous_session(d)
    return list(reversed(out))


def screen_day(view: AsOfView, asof: date, target: date, cfg: dict, catalysts=None, news=None,
               symbols: Optional[list[str]] = None, enforce_c: bool = True) -> ScreenResult:
    if not isinstance(view, AsOfView) or view.asof != asof:
        raise LookaheadError("screen_day must be given an AsOfView fixed at the as-of date")
    catalysts, news = catalysts or NullCatalysts(), news or NullNews()
    res = ScreenResult(asof=asof, target=target, gate_c_mode="ENFORCED" if enforce_c else "UNVERIFIED (skipped)")
    if catalysts.name == "none":
        res.missing.append("earnings calendar (no provider configured): catalyst gate can only use events/news")
    if news.name == "none":
        res.missing.append("news headlines (no provider configured)")
    if not view.has_quotes:
        res.missing.append("option quote history: fill-quality spreads are PROXY (bar high-low)")
    if not view.has_trade_counts:
        res.missing.append("per-print data: trade-frequency check is N/A")
    g, sig = cfg["gates"], cfg["signals"]
    move_days = previous_sessions(asof, sig["move_lookback_sessions"])
    fq_days = previous_sessions(asof, cfg["fill_quality"]["lookback_sessions"])

    for sym in symbols or cfg["universe"]["symbols"]:
        try:
            daily = view.daily_bars(sym, asof, 80)
            if len(daily) < 25 or daily[-1].ts.astimezone(TORONTO).date() != asof:
                res.rejected["no recent daily data"] += 1
                continue
            if mean(b.volume for b in daily[-20:]) < cfg["universe"]["min_underlying_avg_volume"]:
                res.rejected["underlying volume"] += 1
                continue
            try:
                earn = catalysts.earnings_dates(sym, asof, target)
            except ProviderUnavailable as e:
                earn = None
                _note(res, f"earnings provider: {e}")
            try:
                counts = news.daily_counts(sym, asof, 21)
            except ProviderUnavailable as e:
                counts = None
                _note(res, f"news provider: {e}")
            cat, cat_label, is_earn = signals.catalyst_score(sym, asof, target, earn, counts, cfg)
            if cat < g["catalyst_min"]:
                res.rejected["A: no catalyst"] += 1
                continue

            stats = view.option_stats(sym, asof)
            last = view.intraday_bars(sym, asof)
            mom, dirval = signals.momentum(daily, last)
            if abs(dirval) < g["direction_min_strength"]:
                res.rejected["no clear direction"] += 1
                continue
            direction = "bull" if dirval > 0 else "bear"
            iv = stats.iv if stats and stats.iv else pricing.realized_vol([b.close for b in daily])
            rate = signals.move_potential_rate([view.intraday_bars(sym, d) for d in move_days], iv, cfg)
            iv_score, iv_rank, _ = signals.iv_metrics(stats)
            scores = {
                "catalyst": cat,
                "unusual_volume": signals.unusual_volume_score(stats),
                "iv": iv_score,
                "momentum": mom,
                "move_potential": signals.clip(rate / 0.6) if rate is not None else None,
            }
            b_score = signals.weighted(scores, cfg, ["unusual_volume", "iv", "momentum", "move_potential"])
            gate_b = rate is not None and rate >= g["move_potential_min_rate"] and (b_score or 0) >= g["move_signal_min"]
            if not gate_b:
                res.rejected["B: move potential"] += 1
                continue

            chain = view.chain(sym, asof, target)
            right = "C" if direction == "bull" else "P"

            def assess(snap):
                bars = [view.option_bars(snap.contract, d) for d in fq_days]
                return fill_quality.evaluate(snap.contract, snap, bars, has_quotes=view.has_quotes,
                                             has_trade_counts=view.has_trade_counts, cfg=cfg, source=view.name)

            snap, fq = fill_quality.choose_contract(chain, right, target, cfg, assess)
            if snap is None:
                res.rejected["no eligible contract"] += 1
                continue
            combined = signals.weighted(scores, cfg, list(scores)) or 0.0
            cand = Candidate(symbol=sym, direction=direction, scores=scores, combined=round(combined, 4),
                             move_rate=rate, catalyst=cat_label, earnings=is_earn, iv_rank=iv_rank,
                             iv_crush_risk=is_earn, gate_a=True, gate_b=True,
                             gate_c=fq.passed or not enforce_c, snapshot=snap, fill=fq)
            if fq.substituted_from:
                cand.notes.append(f"ideal contract {fq.substituted_from} failed fill quality; using adjacent "
                                  f"{snap.contract.label()} which passed")
            if is_earn:
                cand.notes.append("IV-crush risk: earnings in the window; IV usually falls after the report")
            if not fq.verified:
                cand.notes.append("fill quality is PROXY (no quote history)")
            cand.plan = plan.build(cand, cfg)
            res.passed_ab.append(cand)
            if cand.gate_c:
                res.candidates.append(cand)
            else:
                cand.reject_reason = "C: " + ", ".join(fq.failed_checks)
                res.near_misses.append(cand)
        except LookaheadError:
            raise
        except Exception as e:  # one bad symbol never stops the run
            res.errors.append(f"{sym}: {type(e).__name__}: {str(e)[:160]}")
    res.candidates.sort(key=lambda c: c.combined, reverse=True)
    res.candidates = res.candidates[: cfg["contract"]["top_n"]]
    res.near_misses.sort(key=lambda c: c.combined, reverse=True)
    return res


def _note(res: ScreenResult, msg: str) -> None:
    if msg not in res.missing:
        res.missing.append(msg)


def build_live(cfg):
    from .providers import catalysts as cat_mod
    from .providers.ibkr import IBKRView

    view = IBKRView.connect_readonly(cfg)
    return view, cat_mod.from_env(), NullNews()


def main(argv=None) -> int:
    from . import report

    ap = argparse.ArgumentParser(description="Evening options screen (research only)")
    ap.add_argument("--date", default="next", help="'next' or YYYY-MM-DD (trading day to screen for)")
    ap.add_argument("--mock", action="store_true", help="use deterministic synthetic data (demo/tests)")
    ap.add_argument("--symbols", help="comma-separated override of the universe")
    args = ap.parse_args(argv)
    config_mod.load_env()
    cfg = config_mod.load()
    target = market_calendar.resolve_target(args.date)
    asof = market_calendar.previous_session(target)
    symbols = args.symbols.split(",") if args.symbols else None
    if args.mock:
        from .providers.mock import MockWorld

        world = MockWorld(symbols or MockWorld.DEFAULT_SYMBOLS, end=asof)
        inner, catalysts, news, source = world, world, NullNews(), "MOCK synthetic data (not market data)"
        symbols = world.symbols
    else:
        inner, catalysts, news = build_live(cfg)
        source = inner.name
    res = screen_day(AsOfView(inner, asof), asof, target, cfg, catalysts, news, symbols)
    md, js = report.write_screen(res, cfg, source=source, catalysts=catalysts.name, news=news.name,
                                 run_time=datetime.now(TORONTO), mock=args.mock)
    print(md.read_text())
    print(f"\nWrote {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
