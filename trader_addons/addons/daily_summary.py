#!/usr/bin/env python3
"""Daily summary of the watch-only listener.

    python daily_summary.py                # today (America/Toronto)
    python daily_summary.py --date 2026-10-20
    python daily_summary.py --all          # everything logged so far

Returns are net of a cost per fill (default 3%) on BOTH the entry and the exit:
    net = exit * (1 - cost) / (entry * (1 + cost)) - 1
"""
import argparse
import sys
from collections import Counter

import addons_common as ac
import graduation_listener as gl

HORIZONS = {15: "+15m", 60: "+1h", 240: "+4h"}


def net_return(entry, exit_price, cost):
    if not entry or exit_price is None:
        return None
    return exit_price * (1 - cost) / (entry * (1 + cost)) - 1


def _on_day(ts, day):
    return day is None or str(ts).startswith(day)


def build_summary(day=None, cost=0.03):
    grads = [g for g in ac.read_jsonl(gl.graduations_path()) if _on_day(g.get("ts"), day)]
    safety, breakouts = [], []
    for g in grads:
        for rec in ac.read_jsonl(gl.data_path(g["mint"])):
            if rec.get("type") == "safety":
                safety.append(rec)
            elif rec.get("type") == "breakout":
                breakouts.append(rec)
    signals = [s for s in ac.read_jsonl(gl.signals_path()) if _on_day(s.get("ts"), day)]
    outcomes = {}
    for o in ac.read_jsonl(gl.outcomes_path()):
        outcomes[(o["signal_id"], o["horizon_min"])] = o

    passed = [s for s in safety if (s.get("result") or {}).get("pass")]
    fail_reasons = Counter()
    for s in safety:
        for r in (s.get("result") or {}).get("reasons") or []:
            # keep "source_error:goplus" whole, collapse "whale_holder:<owner>:<pct>" to its type
            fail_reasons[r if r.startswith("source_error") else r.split(":")[0]] += 1
    sources = Counter((s.get("result") or {}).get("source") for s in safety)

    rows = []
    for s in signals:
        row = {"signal": s, "horizons": {}}
        for h in HORIZONS:
            o = outcomes.get((s["signal_id"], h))
            price = o.get("price") if o else None
            row["horizons"][h] = {
                "status": o.get("status") if o else "pending",
                "price": price,
                "gross": (price / s["price"] - 1) if price is not None and s.get("price") else None,
                "net": net_return(s.get("price"), price, cost),
            }
        rows.append(row)

    return {
        "day": day or "all",
        "cost_per_fill": cost,
        "graduations": len(grads),
        "safety_checks": len(safety),
        "safety_passed": len(passed),
        "safety_pass_rate": (len(passed) / len(safety)) if safety else None,
        "safety_sources": dict(sources),
        "top_fail_reasons": fail_reasons.most_common(8),
        "breakouts": len(breakouts),
        "breakouts_blocked_by_safety": sum(1 for b in breakouts if not b.get("safety_pass")),
        "would_buy_signals": len(signals),
        "rows": rows,
    }


def _pct(v):
    return "   n/a" if v is None else f"{v * 100:+6.1f}%"


def render(s):
    out = []
    out.append(f"WATCH-ONLY DAILY SUMMARY ({s['day']}, America/Toronto)   cost/fill {s['cost_per_fill'] * 100:.1f}%")
    out.append("=" * 78)
    out.append(f"Graduations seen        {s['graduations']}")
    rate = "n/a" if s["safety_pass_rate"] is None else f"{s['safety_pass_rate'] * 100:.1f}%"
    out.append(f"Safety checks           {s['safety_checks']}  passed {s['safety_passed']}  pass rate {rate}")
    if s["safety_sources"]:
        out.append("  by source             " + ", ".join(f"{k}={v}" for k, v in s["safety_sources"].items()))
    if s["top_fail_reasons"]:
        out.append("  top fail reasons      " + ", ".join(f"{k} x{v}" for k, v in s["top_fail_reasons"]))
    out.append(f"Breakouts fired         {s['breakouts']}  (blocked by safety {s['breakouts_blocked_by_safety']})")
    out.append(f"Would-buy signals       {s['would_buy_signals']}")
    if s["rows"]:
        out.append("")
        out.append(f"{'time':8} {'mint':12} {'rng':>4} {'entry':>11} " +
                   " ".join(f"{lbl + ' net':>11}" for lbl in HORIZONS.values()))
        sums = {h: [] for h in HORIZONS}
        for r in s["rows"]:
            sig = r["signal"]
            cells = []
            for h in HORIZONS:
                hz = r["horizons"][h]
                if hz["net"] is not None:
                    sums[h].append(hz["net"])
                    cells.append(f"{_pct(hz['net']):>11}")
                else:
                    cells.append(f"{hz['status']:>11}")
            out.append(f"{sig['ts'][11:19]:8} {sig['mint'][:12]:12} {str(sig['range_minutes']) + 'm':>4} "
                       f"{sig['price']:>11.8g} " + " ".join(cells))
        out.append("")
        for h, lbl in HORIZONS.items():
            vals = sums[h]
            if vals:
                wins = sum(1 for v in vals if v > 0)
                out.append(f"{lbl:>4}: n={len(vals)}  avg net {_pct(sum(vals) / len(vals)).strip()}  "
                           f"win rate {wins / len(vals) * 100:.0f}%")
            else:
                out.append(f"{lbl:>4}: no completed outcomes yet")
    out.append("")
    out.append("Log only. No trades were placed.")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="Daily summary of watch-only listener data.")
    p.add_argument("--date", help="YYYY-MM-DD in America/Toronto (default today)")
    p.add_argument("--all", action="store_true", help="summarise everything logged")
    p.add_argument("--cost", type=float, default=0.03, help="cost per fill as a fraction (default 0.03)")
    args = p.parse_args(argv)
    day = None if args.all else (args.date or ac.now_local().date().isoformat())
    print(render(build_summary(day, args.cost)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
