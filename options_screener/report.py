"""Markdown + JSON reports."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path

from .config import REPORTS, config_hash

DISCLAIMER = ("**Research only. Not financial advice. Options can lose 100% of the premium paid. "
              "Nothing here places orders.**")


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


def candidate_row(i, c, target) -> str:
    s, k, fq, p = c.snapshot, c.snapshot.contract, c.fill, c.plan
    return (f"| {i} | {c.symbol} | {'CALL' if k.right == 'C' else 'PUT'} | {k.strike:g} | {k.expiry} | "
            f"{k.dte(target)} | {_f(s.delta)} | {_f(s.mid)} | {_f(fq.median_spread_pct, 1, True)} | "
            f"{_f(fq.first_hour_volume, 0)} | {_f(fq.open_interest, 0)} | {fq.score:.2f} {fq.label} | "
            f"{_f(c.iv_rank)} | {c.catalyst} | {c.combined:.3f} | {p['entry_trigger']} | {p['target']} | "
            f"{p['stop']} | {p['time_stop']} |")


def fill_block(fq) -> list[str]:
    lines = [f"FillQuality ({fq.label}, source: {fq.source})"
             + (f", substituted from {fq.substituted_from}" if fq.substituted_from else ""),
             f"  median spread {_f(fq.median_spread_pct, 2, True)} | first-hour volume {_f(fq.first_hour_volume, 0)} | "
             f"OI {_f(fq.open_interest, 0)} | prints/min {_f(fq.prints_per_min, 1)} | est. round-trip cost "
             f"{_f(fq.round_trip_cost_pct, 2, True)}"]
    for ch in fq.checks:
        lines.append(f"  - {ch.name}: {ch.status} (value {ch.value}, rule {ch.threshold})" + (f" [{ch.note}]" if ch.note else ""))
    return lines


def render_screen(res, cfg, *, source, catalysts, news, run_time, mock=False) -> str:
    L = [f"# Options morning screen for {res.target} (as of close {res.asof})", "",
         DISCLAIMER, ""]
    if mock:
        L += ["> **MOCK DATA.** Generated from a deterministic synthetic market, not real quotes. "
              "It shows the report format only.", ""]
    L += [f"- Run time: {run_time.strftime('%Y-%m-%d %H:%M %Z')} (America/Toronto)",
          "- Mode: RESEARCH (no orders)",
          f"- Market data: {source} | earnings: {catalysts} | news: {news}",
          f"- Fill-quality gate: {res.gate_c_mode}  |  config hash {config_hash(cfg)}"]
    if res.missing:
        L.append("- Missing / degraded: " + "; ".join(res.missing))
    L += ["", f"## Candidates (passed A catalyst + B move potential + C fill quality): {len(res.candidates)}", ""]
    if res.candidates:
        L += ["| # | ticker | type | strike | expiry | DTE | delta | mid | spread | 1st-hr vol | OI | fill quality | "
              "IV rank | catalyst | score | entry trigger | target | stop | time stop |",
              "|" + "---|" * 19]
        L += [candidate_row(i, c, res.target) for i, c in enumerate(res.candidates, 1)]
        for i, c in enumerate(res.candidates, 1):
            L += ["", f"### {i}. {c.symbol} {c.direction.upper()}: {c.snapshot.contract.label()}",
                  "Score breakdown: " + ", ".join(f"{k} {_f(v)}" for k, v in c.scores.items())
                  + f" -> combined {c.combined:.3f}; move-potential rate {_f(c.move_rate)} (underlying PROXY)",
                  f"Why: catalyst = {c.catalyst}; direction = {c.direction}; IV rank {_f(c.iv_rank)}",
                  "Plan: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in c.plan.items())]
            L += [f"Note: {n}" for n in c.notes]
            L += ["```", *fill_block(c.fill), "```"]
    else:
        L.append("No contract passed all three gates. That is a normal outcome: sit out.")
    L += ["", f"## Near-misses (failed ONLY the fill-quality gate): {len(res.near_misses)}", ""]
    if res.near_misses:
        L += ["| ticker | type | contract | score | failing check(s) | spread | 1st-hr vol | OI |", "|---|---|---|---|---|---|---|---|"]
        for c in res.near_misses:
            fq = c.fill
            L.append(f"| {c.symbol} | {c.direction} | {c.snapshot.contract.label()} | {c.combined:.3f} | "
                     f"{', '.join(fq.failed_checks)} | {_f(fq.median_spread_pct, 1, True)} | {_f(fq.first_hour_volume, 0)} | "
                     f"{_f(fq.open_interest, 0)} |")
    else:
        L.append("None.")
    L += ["", "## Screen funnel", "", "| reason | count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(res.rejected.items())]
    if res.errors:
        L += ["", "## Errors (symbol skipped, run continued)", ""] + [f"- {e}" for e in res.errors[:30]]
    return "\n".join(L) + "\n"


def write_screen(res, cfg, *, source, catalysts, news, run_time, mock=False, out_dir: Path = REPORTS):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"screen_{res.target:%Y%m%d}" + ("_MOCK" if mock else "")
    md = out_dir / f"{stem}.md"
    md.write_text(render_screen(res, cfg, source=source, catalysts=catalysts, news=news, run_time=run_time, mock=mock))
    js = out_dir / f"{stem}.json"
    js.write_text(json.dumps({"asof": res.asof.isoformat(), "target": res.target.isoformat(), "mock": mock,
                              "config_hash": config_hash(cfg), "gate_c_mode": res.gate_c_mode,
                              "candidates": _jsonable(res.candidates), "near_misses": _jsonable(res.near_misses),
                              "missing": res.missing, "errors": res.errors}, indent=2, default=str))
    return md, js
