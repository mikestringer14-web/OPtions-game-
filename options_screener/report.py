"""Markdown + JSON reports: reports/morning_screen_YYYY-MM-DD.md (+ .json)."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path

from . import sizing
from .config import REPORTS, config_hash

DISCLAIMER = ("**Research only. Not financial advice. Options can lose 100% of the premium paid. "
              "Nothing here places orders.**")
NO_TRADE = ("NO TRADE — no verified opportunity meets the capital, liquidity, pricing, and defined-risk "
            "requirements.")
MOCK_BANNER = "> **MOCK DATA.** Generated from a deterministic synthetic market, not real quotes."
MASSIVE_BANNER = "> **DELAYED / END-OF-DAY DATA (Massive free tier).** Not live quotes."


def _f(v, nd=2, pct=False):
    if v is None:
        return "n/a"
    return f"{v:.{nd}f}{'%' if pct else ''}"


def _jsonable(o):
    if is_dataclass(o):
        return {k: _jsonable(v) for k, v in asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return o


def banner(provider: str, data_asof, requested_asof) -> list[str]:
    """Data banner: MOCK for mock/synthetic, DELAYED/EOD for massive, nothing for anything else."""
    if provider in ("mock", "synthetic"):
        return [MOCK_BANNER]
    if provider == "massive":
        line = f"{MASSIVE_BANNER} Data received as of {data_asof or 'n/a (no bars received)'}."
        if data_asof is None or data_asof < requested_asof:
            line += f" This is OLDER than the requested close ({requested_asof})."
        return [line]
    return []


def tags(c) -> str:
    s, fq = c.snapshot, c.fill
    quote = "MODEL ESTIMATE" if s.ask_estimated else "MODEL ESTIMATE (synthetic chain)" if s.synthetic else "VERIFIED"
    out = [f"bid/ask {quote}",
           f"delta/IV {'derived MODEL ESTIMATE' if s.iv_source == 'derived' else ('MODEL ESTIMATE' if s.synthetic else 'VERIFIED')}",
           f"fill quality {'VERIFIED' if fq.verified else 'PROXY / UNVERIFIED'}",
           "move potential MODEL ESTIMATE (underlying proxy)",
           "earnings time " + ("VERIFIED" if c.earnings_time_verified else "UNVERIFIED") if c.earnings else "catalyst " + c.catalyst,
           "fees + FX buffer ASSUMPTION"]
    return "; ".join(out)


def candidate_row(i, c, target) -> str:
    s, k, fq, z = c.snapshot, c.snapshot.contract, c.fill, c.sizing
    return (f"| {i} | {c.symbol} | {'CALL' if k.right == 'C' else 'PUT'} | {k.strike:g} | {k.expiry} | "
            f"{k.dte(target)} | {_f(s.delta)} | {_f(s.bid)} | {_f(s.ask)}{'*' if s.ask_estimated else ''} | {_f(s.mid)} | "
            f"{_f(fq.median_spread_pct, 1, True)} | {_f(fq.first_hour_volume, 0)} | {_f(fq.open_interest, 0)} | "
            f"{fq.score:.2f} {fq.label} | {_f(c.iv_rank)} | {c.catalyst} | {c.combined:.3f} | {z.contracts} | "
            f"{_f(z.entry_cost_cad)} | {_f(z.pct_of_capital, 1, True)} | {_f(z.max_loss_cad)} |")


def fill_block(fq) -> list[str]:
    lines = [f"FillQuality ({fq.label}, source: {fq.source})"
             + (f", substituted from {fq.substituted_from}" if fq.substituted_from else "")
             + f": median spread {_f(fq.median_spread_pct, 2, True)} | first-hour volume {_f(fq.first_hour_volume, 0)} | "
             f"OI {_f(fq.open_interest, 0)} | prints/min {_f(fq.prints_per_min, 1)} | est. round-trip cost "
             f"{_f(fq.round_trip_cost_pct, 2, True)}"]
    for ch in fq.checks:
        lines.append(f"  - {ch.name}: {ch.status} (value {ch.value}, rule {ch.threshold})" + (f" [{ch.note}]" if ch.note else ""))
    return lines


def sizing_line(z, cfg) -> str:
    p = cfg["plan"]
    return (f"Size: {z.contracts} contract(s) at ask {z.ask:.2f} | entry US${z.entry_cost_usd:.2f} = C${z.entry_cost_cad:.2f} "
            f"({z.pct_of_capital:.1f}% of C${cfg['account']['capital_cad']:g}) | max loss C${z.max_loss_cad:.2f} (full premium + fees) | "
            f"at -{p['stop_pct']:g}% stop: -C${z.stop_loss_cad:.2f} | breakeven at expiry {z.breakeven:.2f} | "
            f"P/L at +5%: C${z.target_value_cad[5]:+.2f}, at +10%: C${z.target_value_cad[10]:+.2f} (after exit fee + FX)")


def scenario_line(c, cfg) -> str:
    parts = [f"{k}: {v['option']:.2f} ({v['ret_pct']:+.1f}%, C${v['pl_cad']:+.2f})" for k, v in (c.scenarios or {}).items()]
    return f"Scenarios at {cfg['plan']['time_stop']} ET (Black-Scholes, MODEL ESTIMATE): " + "; ".join(parts)


def spread_rows(cands) -> list[str]:
    rows = []
    for c in cands:
        d = c.debit_spread
        if not d:
            continue
        rows.append(f"| {c.symbol} | {d['kind']} | {d['long']} / {d['short']} | {d['debit']:.2f}{'*' if d['estimated'] else ''} | "
                    f"{d['width']:g} | {d['contracts']} | {_f(d['max_loss_cad'])} | {_f(d['max_gain_usd'])} | {d['breakeven']:.2f} |")
    return rows


POST_MARKET = [
    "## Post-market review template (thesis, entry, exit, result vs plan)", "",
    "- Ticker / contract:",
    "- Thesis (catalyst + direction) and was it right?:",
    "- Entry: trigger time ET, limit price, filled price, revisions used (max 2), spread at entry:",
    "- Exit: time ET, price, reason (target / stretch / stop / range reclaimed / spread / 10:30 time stop):",
    "- Result: US$ and C$ after fees + FX, % of C$100:",
    "- Result vs plan: followed every rule? what differed and why?:",
    "- IV change entry -> exit, and did an earnings IV crush hit?:",
    "- Lesson for tomorrow:",
]


def render_screen(res, cfg, *, source, catalysts, news, run_time, provider="mock", fx_rate=None) -> str:
    a = cfg["account"]
    rate = res.cad_usd or a["cad_usd_rate"]
    fx_tag = fx_rate.tag if fx_rate else "ASSUMPTION"
    fx_src = (f"{fx_rate.source}" + (f" {fx_rate.as_of}" if fx_rate.as_of != "n/a" else "")) if fx_rate else "config fallback"
    budget = sizing.usd_budget(cfg, rate)
    L = [f"# Options morning screen for {res.target} (as of close {res.asof})", "", DISCLAIMER]
    L += banner(provider, res.data_asof, res.asof)
    L += ["",
          f"- Mode: RESEARCH (no orders) | Market data: {source} | earnings: {catalysts} | news: {news or 'none'}",
          f"- Budget: C${a['capital_cad']:g} (~US${budget:.2f} after FX) | ONE position | max loss = full premium + fees "
          f"(up to C${a['capital_cad']:g}) | max premium/contract US${sizing.max_premium_per_contract(cfg, rate):.3f}",
          f"- FX: 1 CAD = {rate:.4f} USD ({fx_tag}: {fx_src}) | FX cost buffer {a['fx_cost_pct']:g}% per conversion (ASSUMPTION) | "
          f"fee buffer US${a['fee_per_contract_usd']:.2f}/contract/side (ASSUMPTION)",
          f"- Fill-quality gate: {res.gate_c_mode} | Missing / degraded: " + ("; ".join(res.missing) or "none"),
          f"- Run time: {run_time.strftime('%Y-%m-%d %H:%M %Z')} (America/Toronto) | config hash {config_hash(cfg)}"]
    if res.warnings:
        L.append("- Data warnings: " + "; ".join(res.warnings[:10]))
    n_max = cfg["strategies"]["max_actionable"]
    L += ["", f"## Candidates (passed A + B + C): {len(res.candidates)}   (max {n_max} actionable, ranked)", ""]
    if res.candidates:
        L += ["| # | ticker | type | strike | expiry | DTE | delta | bid | ask | mid | spread | 1st-hr vol | OI | fill quality | "
              "IV rank | catalyst | score | contracts | cost CAD | % of C$100 | max loss CAD |",
              "|" + "---|" * 21]
        L += [candidate_row(i, c, res.target) for i, c in enumerate(res.candidates, 1)]
        L += ["", f"ONE position only: take at most {a['max_new_trades_per_day']} of these per day "
              f"(max open positions {a['max_open_positions']}). `*` = MODEL ESTIMATE (no live quote)."]
        for i, c in enumerate(res.candidates, 1):
            p = c.plan
            L += ["", f"### {i}. {c.symbol} {c.direction.upper()}: {c.snapshot.contract.label()}",
                  sizing_line(c.sizing, cfg),
                  f"Plan: entry {p['entry_trigger']}; {p['entry_order']}; requires {p['entry_requires']}; no entry after "
                  f"{p['entry_deadline']} ET; target {p['target']}; stop {p['stop']}; exit if {p['invalidation']}; "
                  f"time stop {p['time_stop']}",
                  scenario_line(c, cfg),
                  "Why: " + ", ".join(f"{k} {_f(v)}" for k, v in c.scores.items())
                  + f" -> score {c.combined:.3f}; +5% before stop/time-stop rate {_f(c.move_rate)} "
                  f"(+10% {_f(c.move_stretch_rate)}; legacy optimistic proxy {_f(c.move_rate_legacy)})",
                  f"Tags: {tags(c)}"]
            if c.earnings:
                L.append("IV-crush note: earnings in the window. IV usually drops hard after the report; a correct "
                         "direction call can still lose money." + ("" if c.earnings_time_verified else
                                                                    " Report time UNVERIFIED (no BMO/AMC from the source)."))
            L += [f"Note: {n}" for n in c.notes]
            L += ["```", *fill_block(c.fill), "```"]
    else:
        L.append(NO_TRADE)
    L += ["", "## Research-only debit spread comparison (not executable at Wealthsimple)", "",
          "Shown only to compare cost and max loss. Wealthsimple does not support multi-leg orders, so these are "
          "NOT actionable. `*` = uses a MODEL ESTIMATE price.", ""]
    rows = spread_rows(res.candidates + res.near_misses)
    if rows:
        L += ["| ticker | type | long / short | debit | width | contracts | max loss CAD | max gain USD | breakeven |",
              "|---|---|---|---|---|---|---|---|---|", *rows]
    else:
        L.append("None (no candidate or near-miss had a usable next strike).")
    L += ["", f"## Near-misses (failed ONLY fill quality or affordability): {len(res.near_misses)}", ""]
    if res.near_misses:
        L += ["| ticker | type | contract | score | failed | ask | 1 contract CAD | spread | 1st-hr vol | OI |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for c in res.near_misses:
            fq, s = c.fill, c.snapshot
            L.append(f"| {c.symbol} | {c.direction} | {s.contract.label()} | {c.combined:.3f} | {c.reject_reason} | "
                     f"{_f(s.ask)}{'*' if s.ask_estimated else ''} | {sizing.one_contract_cad(s.ask, cfg, rate):.2f} | "
                     f"{_f(fq.median_spread_pct, 1, True)} | {_f(fq.first_hour_volume, 0)} | {_f(fq.open_interest, 0)} |")
    else:
        L.append("None.")
    L += ["", "## Screen funnel", "", "| reason | count |", "|---|---|"]
    funnel = dict(res.rejected)
    funnel.setdefault(sizing.UNAFFORDABLE, 0)
    L += [f"| {k} | {v} |" for k, v in sorted(funnel.items())]
    L.append(f"| passed everything | {len(res.candidates)} |")
    if res.errors:
        L += ["", "## Errors (symbol skipped, run continued)", ""] + [f"- {e}" for e in res.errors[:30]]
    L += ["", *POST_MARKET]
    return "\n".join(L) + "\n"


def write_screen(res, cfg, *, source, catalysts, news, run_time, mock=None, provider=None, fx_rate=None,
                 out_dir: Path = REPORTS):
    provider = provider or ("mock" if mock else "unknown")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"morning_screen_{res.target:%Y-%m-%d}"       # the banner inside says MOCK / DELAYED
    md = out_dir / f"{stem}.md"
    md.write_text(render_screen(res, cfg, source=source, catalysts=catalysts, news=news, run_time=run_time,
                                provider=provider, fx_rate=fx_rate))
    js = out_dir / f"{stem}.json"
    js.write_text(json.dumps({"asof": res.asof.isoformat(), "target": res.target.isoformat(), "provider": provider,
                              "data_asof": res.data_asof.isoformat() if res.data_asof else None,
                              "config_hash": config_hash(cfg), "gate_c_mode": res.gate_c_mode, "cad_usd": res.cad_usd,
                              "no_trade": not res.candidates,
                              "candidates": _jsonable(res.candidates), "near_misses": _jsonable(res.near_misses),
                              "funnel": dict(res.rejected), "missing": res.missing, "warnings": res.warnings,
                              "errors": res.errors}, indent=2, default=str))
    return md, js
