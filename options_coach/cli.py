"""Command line: prints a numbers block you paste straight into the Grok options coach.

  python -m options_coach.cli price --type C --spot 150 --strike 155 --dte 30 --iv 32
  python -m options_coach.cli iv --type P --spot 150 --strike 140 --dte 30 --price 1.85
  python -m options_coach.cli strategy --spot 150 --dte 30 +1C150@4.10 -1C160@1.30 --account 5000
  python -m options_coach.cli size --account 5000 --risk-per-contract 280 --max-risk-pct 3
"""
import argparse
import sys
from datetime import datetime

from . import black_scholes as bs
from .strategy import Position, parse_leg

HEADER = "=== OPTIONS NUMBERS (Black-Scholes, European model) ==="
FOOTER = "=== END NUMBERS: verify live quotes, earnings date and news before acting ==="


def money(x):
    return "UNLIMITED" if x is None else f"${abs(x):,.2f}"


def pct(x):
    return f"{x * 100:.1f}%"


def stamp(args):
    return f"Generated {datetime.now():%Y-%m-%d %H:%M} | r={args.rate}% q={args.div}%"


def cmd_price(args):
    T = args.dte / 365
    g = bs.greeks(args.type, args.spot, args.strike, T, args.rate / 100, args.iv / 100, args.div / 100)
    em = bs.expected_move(args.spot, args.iv / 100, T)
    touch = bs.prob_touch(args.type, args.spot, args.strike, T, args.rate / 100, args.iv / 100, args.div / 100)
    return [
        HEADER, stamp(args),
        f"{args.type.upper()} {args.strike:g} | spot {args.spot:g} | {args.dte:g} DTE | IV {args.iv:g}%",
        f"Fair value      {g.price:.2f} per share (${g.price * 100:,.2f} per contract)",
        f"Delta {g.delta:+.3f} | Gamma {g.gamma:.4f} | Theta {g.theta:+.3f}/day | Vega {g.vega:.3f}/vol pt | Rho {g.rho:+.3f}",
        f"Prob finish ITM {pct(g.prob_itm)} | Prob touch ~{pct(touch)}",
        f"1-SD expected move by expiry: +/- ${em:.2f} ({args.spot - em:.2f} to {args.spot + em:.2f})",
        FOOTER,
    ]


def cmd_iv(args):
    T = args.dte / 365
    iv = bs.implied_vol(args.type, args.price, args.spot, args.strike, T, args.rate / 100, args.div / 100)
    g = bs.greeks(args.type, args.spot, args.strike, T, args.rate / 100, iv, args.div / 100)
    lines = [HEADER, stamp(args),
             f"{args.type.upper()} {args.strike:g} | spot {args.spot:g} | {args.dte:g} DTE | market price {args.price:g}",
             f"Implied vol     {iv * 100:.2f}%",
             f"Delta {g.delta:+.3f} | Gamma {g.gamma:.4f} | Theta {g.theta:+.3f}/day | Vega {g.vega:.3f}/vol pt",
             f"Prob finish ITM {pct(g.prob_itm)}"]
    if args.hv:
        ratio = iv * 100 / args.hv
        tag = "options look EXPENSIVE vs realized (favours selling premium)" if ratio > 1.2 else \
              "options look CHEAP vs realized (favours buying premium)" if ratio < 0.85 else "IV roughly in line with realized"
        lines.append(f"IV / HV = {ratio:.2f} ({tag})")
    lines.append(FOOTER)
    return lines


def flags_for(pos, max_p, max_l, pop, args):
    out = []
    if max_l is None:
        out.append("UNDEFINED RISK: loss is unlimited above the top strike. Needs a hedge leg or a hard stop.")
    if any(leg.kind == "P" and leg.qty < 0 for leg in pos.legs) and max_l is not None and max_l < -10 * abs(pos.cost or 1):
        out.append("Large downside: short puts can lose a lot more than the credit if the stock gaps down.")
    if pos.dte <= 7:
        out.append(f"{pos.dte:g} DTE: gamma risk is high, P/L can swing hard on small moves. Size down.")
    if pop < 0.30:
        out.append(f"Low probability of profit ({pct(pop)}). Only worth it if the payoff is large vs risk.")
    if max_p is not None and max_l not in (None, 0) and max_p / abs(max_l) < 0.25 and pop < 0.80:
        out.append("Reward/risk under 0.25 without a high win rate: the math is working against you.")
    if args.account and max_l is not None:
        risk_pct = abs(max_l) / args.account * 100
        if risk_pct > args.max_risk_pct:
            out.append(f"Max loss is {risk_pct:.1f}% of account, above your {args.max_risk_pct:g}% limit. Cut size.")
    for leg in pos.legs:
        if leg.kind == "C" and leg.qty < 0 and args.div > 0:
            out.append(f"{leg.label()}: short call + dividend stock, watch early assignment before ex-div.")
    out += pos.notes
    return out or ["None from the math. Still check earnings date, news and bid/ask spread."]


def cmd_strategy(args):
    legs = [parse_leg(x) for x in args.legs]
    pos = Position(legs, args.spot, args.dte, args.rate / 100, args.div / 100, args.iv / 100 if args.iv else None)
    g = pos.greeks()
    max_p, max_l = pos.max_profit_loss()
    pop = pos.prob_of_profit()
    em = pos.expected_move()
    cost = pos.cost
    lines = [HEADER, stamp(args),
             f"Underlying {args.symbol or ''} spot {args.spot:g} | {args.dte:g} DTE | distribution vol {pct(pos.iv)}",
             "", "LEGS"]
    for leg in legs:
        iv = "" if leg.kind == "S" else f" | IV {pct(leg.iv)}"
        lines.append(f"  {leg.label():<26} @ {leg.premium:.2f}{iv}")
    lines += [
        "", "RISK / REWARD (at expiry)",
        f"  Net {'DEBIT paid' if cost > 0 else 'CREDIT received'}: ${abs(cost):,.2f}",
        f"  Max profit:  {money(max_p)}",
        f"  Max loss:    {money(max_l)}",
        f"  Breakevens:  {', '.join(f'{b:g}' for b in pos.breakevens()) or 'none'}",
        f"  Prob of profit: {pct(pop)}",
        f"  Expected P/L at expiry at {pct(pos.iv)} vol: ${pos.expected_pnl_at_expiry():,.2f}"
        " (near 0 = fair; positive = edge in your favour at that vol, negative = edge against you)",
        f"  1-SD expected move: +/- ${em:.2f} ({args.spot - em:.2f} to {args.spot + em:.2f})",
        "", "POSITION GREEKS (whole position, dollars)",
        f"  Delta {g['delta']:+.1f} (acts like {g['delta']:+.0f} shares) | Gamma {g['gamma']:+.2f}",
        f"  Theta {g['theta']:+.2f}/day | Vega {g['vega']:+.2f} per IV point | Rho {g['rho']:+.2f}",
    ]
    if args.account:
        lines.append(f"  Account ${args.account:,.0f}: max loss = "
                     + ("UNLIMITED" if max_l is None else f"{abs(max_l) / args.account * 100:.1f}% of account"))

    fwd = min(args.days_forward if args.days_forward is not None else round(args.dte / 2), args.dte)
    moves, rows = pos.scenario_grid(fwd)
    lines += ["", f"WHAT-IF P/L in {fwd:g} days (rows = IV change, columns = stock move)",
              "  IV chg | " + " | ".join(f"{m:+d}%".rjust(8) for m in moves)]
    for shift, vals in rows:
        lines.append(f"  {shift * 100:+5.0f}  | " + " | ".join(f"{v:8,.0f}" for v in vals))
    lines += ["", "FLAGS"] + [f"  - {f}" for f in flags_for(pos, max_p, max_l, pop, args)] + [FOOTER]
    return lines


def cmd_size(args):
    budget = args.account * args.max_risk_pct / 100
    n = int(budget // args.risk_per_contract) if args.risk_per_contract > 0 else 0
    return [HEADER,
            f"Account ${args.account:,.0f} | max risk {args.max_risk_pct:g}% = ${budget:,.2f} per trade",
            f"Max loss per contract/spread ${args.risk_per_contract:,.2f} -> size: {n} contract(s)",
            "0 means this trade is too big for the account at this risk level. Use a narrower spread." if n == 0 else
            f"Total at risk: ${n * args.risk_per_contract:,.2f}",
            FOOTER]


def build_parser():
    p = argparse.ArgumentParser(prog="options_coach", description="Black-Scholes numbers for the Grok options coach")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--spot", type=float, required=True, help="current stock price")
        sp.add_argument("--dte", type=float, required=True, help="calendar days to expiry")
        sp.add_argument("--rate", type=float, default=4.0, help="risk-free rate %% (use the current 3-month T-bill)")
        sp.add_argument("--div", type=float, default=0.0, help="dividend yield %%")

    sp = sub.add_parser("price", help="fair value and Greeks for one option")
    common(sp)
    sp.add_argument("--type", required=True, choices=["C", "P", "c", "p"])
    sp.add_argument("--strike", type=float, required=True)
    sp.add_argument("--iv", type=float, required=True, help="implied vol %%, e.g. 32")
    sp.set_defaults(func=cmd_price)

    sp = sub.add_parser("iv", help="implied vol from a market price")
    common(sp)
    sp.add_argument("--type", required=True, choices=["C", "P", "c", "p"])
    sp.add_argument("--strike", type=float, required=True)
    sp.add_argument("--price", type=float, required=True, help="option mid price per share")
    sp.add_argument("--hv", type=float, help="historical/realized vol %% to compare against")
    sp.set_defaults(func=cmd_iv)

    sp = sub.add_parser("strategy", help="full numbers for a multi-leg trade")
    common(sp)
    sp.add_argument("legs", nargs="*", help="legs like +1C150@4.10 -1C160@1.30 (see strategy.py)")
    sp.add_argument("--iv", type=float, help="vol %% for probabilities (your forecast); default: average solved IV")
    sp.add_argument("--symbol", default="")
    sp.add_argument("--days-forward", type=float, help="days ahead for the what-if grid (default half the DTE)")
    sp.add_argument("--account", type=float, help="account size in dollars")
    sp.add_argument("--max-risk-pct", type=float, default=5.0, help="max %% of account to risk per trade")
    sp.set_defaults(func=cmd_strategy)

    sp = sub.add_parser("size", help="how many contracts fit your risk limit")
    sp.add_argument("--account", type=float, required=True)
    sp.add_argument("--risk-per-contract", type=float, required=True, help="max loss of one contract or spread, $")
    sp.add_argument("--max-risk-pct", type=float, default=5.0)
    sp.set_defaults(func=cmd_size)
    return p


def main(argv=None):
    # legs start with + or -, which argparse would read as options; this keeps them as values
    argv = list(sys.argv[1:] if argv is None else argv)
    args, extra = build_parser().parse_known_args(argv)
    if extra:
        if args.cmd != "strategy":
            build_parser().error(f"unrecognized arguments: {' '.join(extra)}")
        args.legs = list(args.legs or []) + extra
    if args.cmd == "strategy" and not args.legs:
        build_parser().error("strategy needs at least one leg, e.g. +1C150@4.10")
    try:
        print("\n".join(args.func(args)))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
