"""Evening / pre-market screen. RESEARCH ONLY: reads data, writes a report, never places orders,
never connects to a broker.

    python -m options_screener.screen --date next --provider mock        # deterministic demo data
    python -m options_screener.screen --date next --provider synthetic   # mock underlying + BS proxy options
    python -m options_screener.screen --date next --provider massive     # Massive FREE tier (end-of-day)

A candidate must pass ALL THREE gates: (A) catalyst, (B) 5%+ move potential, (C) fill quality,
AND fit the C$100 one-position budget at the ASK incl. fees and FX ("unaffordable at C$100").
"""
from __future__ import annotations

import argparse
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean
from typing import Optional

from . import config as config_mod
from . import fill_quality, market_calendar, plan, pricing, signals, sizing
from .models import TORONTO, Candidate
from .providers.base import AsOfView, LookaheadError, NullCatalysts, NullNews, ProviderUnavailable


@dataclass
class ScreenResult:
    asof: date
    target: date
    candidates: list = field(default_factory=list)      # passed A, B, C and affordable (ranked, max N actionable)
    near_misses: list = field(default_factory=list)     # passed A and B, failed ONLY fill quality or ONLY affordability
    passed_ab: list = field(default_factory=list)       # everything that passed A and B (backtest "without C")
    rejected: Counter = field(default_factory=Counter)
    errors: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    gate_c_mode: str = "ENFORCED"
    cad_usd: Optional[float] = None
    data_asof: Optional[date] = None                    # latest daily bar actually received


def previous_sessions(asof: date, n: int) -> list[date]:
    out, d = [], asof
    while len(out) < n:
        out.append(d)
        d = market_calendar.previous_session(d)
    return list(reversed(out))


def _hours_to_expiry(day: date, hhmm: str, expiry: date) -> float:
    a = signals.at_et(day, hhmm)
    b = signals.at_et(expiry, "16:00")
    return max(0.0, (b - a).total_seconds() / 3600)


def scenarios(cand: Candidate, spot: float, target: date, cfg: dict, cad_usd: float, move_pct: float = 1.0,
              iv_shift: float = 0.05) -> dict:
    """Black-Scholes value at the 10:30 ET time stop on the target day: underlying up / down /
    flat, IV up / down. Entry at the ask. MODEL ESTIMATE, not a forecast."""
    snap, sz = cand.snapshot, cand.sizing
    k = snap.contract
    iv = snap.iv or 0.3
    t = pricing.year_fraction(_hours_to_expiry(target, cfg["plan"]["time_stop"], k.expiry) / 24)
    cases = {f"underlying +{move_pct:g}%": (spot * (1 + move_pct / 100), iv),
             f"underlying -{move_pct:g}%": (spot * (1 - move_pct / 100), iv),
             "flat": (spot, iv), f"IV +{iv_shift * 100:g}pt": (spot, iv + iv_shift),
             f"IV -{iv_shift * 100:g}pt": (spot, max(0.05, iv - iv_shift))}
    out = {}
    for name, (s, v) in cases.items():
        px = pricing.price(s, k.strike, t, v, k.right)
        out[name] = {"option": round(px, 3), "ret_pct": round((px / snap.ask - 1) * 100, 1) if snap.ask else None,
                     "pl_cad": sizing.pl_cad_at(px, sz, cfg, cad_usd) if sz and sz.affordable else None}
    return out


def debit_spread(cand: Candidate, chain: list, cfg: dict, cad_usd: float) -> Optional[dict]:
    """RESEARCH ONLY comparison: buy the chosen strike, sell the next strike further OTM, same expiry.
    Not executable at Wealthsimple (no multi-leg orders)."""
    long = cand.snapshot
    k = long.contract
    same = [s for s in chain if s.contract.expiry == k.expiry and s.contract.right == k.right]
    further = [s for s in same if (s.contract.strike > k.strike if k.right == "C" else s.contract.strike < k.strike)]
    if not further or long.ask is None:
        return None
    short = min(further, key=lambda s: abs(s.contract.strike - k.strike))
    proxy = cfg["fill_quality"]["proxy_spread_pct"]
    short_bid = short.bid if short.bid is not None else (short.last or 0) * (1 - proxy / 200)
    debit = round(long.ask - short_bid, 2)
    width = abs(short.contract.strike - k.strike)
    a = cfg["account"]
    fee2 = 2 * a["fee_per_contract_usd"]
    if debit <= 0 or debit >= width:
        return None
    budget = sizing.usd_budget(cfg, cad_usd)
    n = math.floor(budget / (debit * 100 + fee2))
    kind = "call_debit_spread" if k.right == "C" else "put_debit_spread"
    return {"kind": kind, "long": k.label(), "short": short.contract.label(), "debit": debit, "width": width,
            "contracts": n, "max_loss_cad": sizing.usd_to_cad_cost(n * (debit * 100 + fee2), cfg, cad_usd) if n else None,
            "max_gain_usd": round(n * ((width - debit) * 100 - 2 * fee2), 2) if n else None,
            "breakeven": round(k.strike + debit if k.right == "C" else k.strike - debit, 2),
            "estimated": long.ask_estimated or short.bid is None,
            "label": "research only: not executable at Wealthsimple (no multi-leg)"}


def screen_day(view: AsOfView, asof: date, target: date, cfg: dict, catalysts=None, news=None,
               symbols: Optional[list[str]] = None, enforce_c: bool = True, cad_usd: Optional[float] = None) -> ScreenResult:
    if not isinstance(view, AsOfView) or view.asof != asof:
        raise LookaheadError("screen_day must be given an AsOfView fixed at the as-of date")
    catalysts, news = catalysts or NullCatalysts(), news or NullNews()
    cad_usd = cad_usd if cad_usd is not None else cfg["account"]["cad_usd_rate"]
    res = ScreenResult(asof=asof, target=target, gate_c_mode="ENFORCED" if enforce_c else "UNVERIFIED (skipped)",
                       cad_usd=cad_usd)
    if catalysts.name == "none":
        res.missing.append("earnings calendar (no provider configured): catalyst gate can only use events/news")
    if news.name == "none":
        res.missing.append("news headlines (no provider configured)")
    for d in getattr(view.inner, "degraded", []):
        _note(res, d)
    if not view.has_quotes:
        _note(res, "option quote history: fill-quality spreads are PROXY (bar high-low)")
    if not view.has_trade_counts:
        res.missing.append("per-print data: trade-frequency check is N/A")
    g, sig = cfg["gates"], cfg["signals"]
    move_days = previous_sessions(asof, sig["move_lookback_sessions"])
    fq_days = previous_sessions(asof, cfg["fill_quality"]["lookback_sessions"])

    for sym in symbols or cfg["universe"]["symbols"]:
        try:
            daily = view.daily_bars(sym, asof, 80)
            if daily:
                last_day = daily[-1].ts.astimezone(TORONTO).date()
                res.data_asof = max(res.data_asof or last_day, last_day)
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
            mp = signals.move_potential([view.intraday_bars(sym, d) for d in move_days], iv, cfg)
            rate = mp["rate"]
            if mp["gaps"]:
                res.warnings.append(f"{sym}: {mp['gaps']} gap(s) in 1-minute bars over the move-potential lookback")
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
            pool = fill_quality.eligible(chain, right, target, cfg, res.rejected)
            if not pool:
                res.rejected["no eligible contract"] += 1
                continue
            sized = {id(s): sizing.size(s.ask, s.contract.strike, right, cfg, cad_usd, s.multiplier) for s in pool}
            affordable = [s for s in pool if sized[id(s)].affordable]

            def assess(snap, sized=sized):
                bars = [view.option_bars(snap.contract, d) for d in fq_days]
                return fill_quality.evaluate(snap.contract, snap, bars, has_quotes=view.has_quotes,
                                             has_trade_counts=view.has_trade_counts, cfg=cfg, source=view.name,
                                             n=max(1, sized[id(snap)].contracts))

            if affordable:
                snap, fq = fill_quality.choose_contract(affordable, right, target, cfg, assess)
            else:
                snap = min(pool, key=lambda s: s.ask)       # the cheapest in-band contract, for the near-miss list
                fq = assess(snap)
            combined = signals.weighted(scores, cfg, list(scores)) or 0.0
            time_ok = not (is_earn and "time unverified" in cat_label)
            cand = Candidate(symbol=sym, direction=direction, scores=scores, combined=round(combined, 4),
                             move_rate=rate, catalyst=cat_label, earnings=is_earn, iv_rank=iv_rank,
                             iv_crush_risk=is_earn, gate_a=True, gate_b=True,
                             gate_c=fq.passed or not enforce_c, snapshot=snap, fill=fq, sizing=sized[id(snap)],
                             move_rate_legacy=mp["legacy_rate"], move_stretch_rate=mp["stretch_rate"],
                             earnings_time_verified=time_ok)
            if fq.substituted_from:
                cand.notes.append(f"ideal contract {fq.substituted_from} failed fill quality; using adjacent "
                                  f"{snap.contract.label()} which passed")
            if is_earn:
                cand.notes.append("IV-crush risk: earnings in the window; IV usually falls after the report")
            if is_earn and not time_ok:
                cand.notes.append("earnings time UNVERIFIED (the source gives no BMO/AMC): the IV crush may land "
                                  "before or during the morning window")
            if not fq.verified:
                cand.notes.append("fill quality is PROXY (no quote history)")
            if snap.ask_estimated:
                cand.notes.append("ask is a MODEL ESTIMATE (no live quote on this data tier): contracts / cost are DEGRADED")
            if snap.iv_source == "derived":
                cand.notes.append("IV and delta derived by Black-Scholes from the end-of-day close")
            cand.plan = plan.build(cand, cfg)
            cand.debit_spread = debit_spread(cand, chain, cfg, cad_usd)
            spot = daily[-1].close
            if cand.sizing.affordable:
                cand.scenarios = scenarios(cand, spot, target, cfg, cad_usd)
            res.passed_ab.append(cand)
            if not cand.sizing.affordable:
                need = sizing.one_contract_cad(snap.ask, cfg, cad_usd)
                cand.reject_reason = f"{sizing.UNAFFORDABLE} (1 contract needs C${need:.2f})"
                res.rejected[sizing.UNAFFORDABLE] += 1
                if cand.gate_c:
                    res.near_misses.append(cand)
            elif cand.gate_c:
                res.candidates.append(cand)
            else:
                cand.reject_reason = "C: " + ", ".join(fq.failed_checks)
                res.rejected["C: fill quality"] += 1
                res.near_misses.append(cand)
        except LookaheadError:
            raise
        except Exception as e:  # one bad symbol never stops the run
            res.errors.append(f"{sym}: {type(e).__name__}: {str(e)[:160]}")
    res.candidates.sort(key=lambda c: c.combined, reverse=True)
    res.candidates = res.candidates[: min(cfg["contract"]["top_n"], cfg["strategies"]["max_actionable"])]
    res.near_misses.sort(key=lambda c: c.combined, reverse=True)
    return res


def _note(res: ScreenResult, msg: str) -> None:
    if msg not in res.missing:
        res.missing.append(msg)


def build_provider(name: str, cfg: dict, asof: date, symbols: Optional[list[str]] = None):
    """(view, catalysts, news, symbols). No provider here can reach a broker."""
    from .providers import catalysts as cat_mod

    if name == "mock":
        from .providers.mock import MockWorld

        world = MockWorld(symbols or MockWorld.DEFAULT_SYMBOLS, end=asof)
        return world, world, NullNews(), world.symbols
    if name == "synthetic":
        from .providers.historical import synthetic_market

        view, world = synthetic_market(cfg, asof, symbols)
        return view, world, NullNews(), view.symbols
    if name == "massive":
        from .providers.massive import MassiveView

        return MassiveView(asof, cfg), cat_mod.from_env(), NullNews(), symbols or cfg["data"]["massive_symbols"]
    raise ValueError(f"unknown provider {name!r}; choose one of {config_mod.PROVIDERS}")


def main(argv=None) -> int:
    from . import fx, report

    ap = argparse.ArgumentParser(description="Morning options screen (research only, no orders)")
    ap.add_argument("--date", default="next", help="'next' or YYYY-MM-DD (trading day to screen for)")
    ap.add_argument("--provider", choices=config_mod.PROVIDERS, help="overrides [data] provider in config.toml")
    ap.add_argument("--mock", action="store_true", help="shorthand for --provider mock")
    ap.add_argument("--symbols", help="comma-separated override of the universe")
    ap.add_argument("--offline", action="store_true", help="skip the Bank of Canada FX lookup (use the config rate)")
    args = ap.parse_args(argv)
    config_mod.load_env()
    cfg = config_mod.load()
    provider = "mock" if args.mock else (args.provider or cfg["data"]["provider"])
    target = market_calendar.resolve_target(args.date)
    asof = market_calendar.previous_session(target)
    symbols = args.symbols.split(",") if args.symbols else None
    try:
        inner, catalysts, news, symbols = build_provider(provider, cfg, asof, symbols)
    except ProviderUnavailable as e:
        print(f"Provider {provider} unavailable: {e}. Nothing was screened.")
        return 2
    rate = fx.get_rate(cfg, use_network=not args.offline)
    res = screen_day(AsOfView(inner, asof), asof, target, cfg, catalysts, news, symbols, cad_usd=rate.cad_usd)
    md, js = report.write_screen(res, cfg, source=inner.name, catalysts=catalysts.name, news=news.name,
                                 run_time=datetime.now(TORONTO), provider=provider, fx_rate=rate)
    print(md.read_text())
    print(f"\nWrote {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
