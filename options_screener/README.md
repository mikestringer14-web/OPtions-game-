# Options morning screener (RESEARCH + PAPER ONLY)

An evening / weekend screen for **single-leg long calls or puts** that might gain **+5% in option
price in the first 30-90 minutes after the open**, and whose recent trading history shows they can
actually be bought and sold quickly. It also includes a backtest with a strict PASS gate, and an
IBKR **paper**-account mode that stays locked until that gate passes.

> **Research only. Not financial advice. Options can lose 100% of the premium.** Nothing in this
> folder can send a live order. `paper.py` is the only order code. It runs only with `--paper`,
> only after a PASS backtest on real option data, and only against an IBKR paper account.

## What it does

**Evening screen.** A candidate must pass **all three** gates. Each gate is cheaper to compute than
the next, so they run in this order:

| Gate | What it checks | Data |
|---|---|---|
| **A: catalyst** | Earnings on the as-of day or the target day, scheduled events in `config.toml [events]`, or a news-count spike | Alpha Vantage earnings calendar (free key) or `data/earnings.csv`; news is pluggable |
| **B: move potential** | Share of the last 20 mornings where an ATM option would have gained 5% or more within 60 minutes of an opening-range break (min 40%), plus a weighted score of unusual options volume, IV rank and change, and momentum | IBKR bars and ticks. The move rate is an **underlying proxy** (delta × underlying move / option price) |
| **C: fill quality** | Per strike and expiry, over the previous 1 to 5 sessions: morning and closing spread, first-hour and full-day volume, active minutes, OI and OI change, seconds between prints, displayed depth, and round-trip cost as a share of the +5% target | IBKR TRADES + BID_ASK 1-minute bars (**VERIFIED**). Bars only gives **PROXY** |

It picks the contract with delta 0.35 to 0.60, 2 to 21 DTE and $300 or less per contract. If that
contract fails gate C, it tries nearby strikes and expiries and says so. The top 10 are ranked by
combined score. Names that failed **only** gate C are listed separately as near-misses.

**Plan per candidate:**
- **Entry:** after the first 5 minutes, and only when the underlying breaks the opening-range high (calls) or low (puts) and the live spread is still within the gate C limit. A limit order at mid, cancelled after 60 s. Never a market order, never chasing.
- **Target:** +5% (also showing +10%), exiting at or near the bid.
- **Exit early on any of:** -15%, the underlying moving back inside the opening range, the spread widening past 2× its historical median, or the **10:30 ET time stop**.

**Backtest.** For each past session, the screen runs on an **as-of view fixed at the prior close**.
Any read of a later date raises `LookaheadError`, and tests check this. Then the morning plan is
simulated on 1-minute bars, deliberately pessimistically:
- the limit only fills if a bar trades at or through it with volume of at least 10× our size;
- even then we pay the ask and receive the bid, plus IBKR commissions;
- within a bar, the stop is checked before the target.

Validation:
- a 70/30 time split (tuning on the first 70%, results reported on the last 30%);
- a bootstrap of trade returns;
- a 2× cost stress test and a 1-minute entry-delay test;
- parameter perturbation;
- splits by score, DTE, call vs put, earnings, and fill-quality bucket;
- **with versus without gate C**, to show whether the fill-quality gate actually helps.

## The PASS gate (exact)
`reports/PASS.json` is written **only if all** of these hold. Otherwise any existing PASS file is deleted.
1. Out-of-sample expectancy is above 0 USD per trade, after costs.
2. The bootstrap 5th percentile of the mean out-of-sample net return is above 0.
3. Expectancy at 2× costs is above 0.
4. The out-of-sample entry fill rate is 70% or higher.
5. There are at least 100 out-of-sample filled trades.
6. **The data mode is VERIFIED**, meaning real historical option bars **with quotes**. PROXY,
   BARS-ONLY and MOCK backtests can never PASS. This is stricter than the spec on purpose: a
   proxy result must not unlock trading.

Paper mode also checks that the PASS file's **config hash** matches `config.toml`. Changing any
gate, plan, cost or backtest setting relocks paper mode until a new backtest passes.

## Setup
```bash
cd options_screener
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt    # Python 3.11+
cp .env.example .env        # fill in locally; never commit it
cd .. && options_screener/.venv/bin/python -m options_screener.status
```

**IB Gateway (or TWS), paper account:**
1. Install IB Gateway and log in with your **paper trading username**. It's a separate login, shown in Client Portal under Settings, Paper Trading Account. Your paper account number starts with **DU**.
2. Go to Configure, Settings, API, Settings and turn on socket clients. The port must be **4002** (Gateway paper) or **7497** (TWS paper). Live ports 4001 and 7496 are refused.
3. The screen connects with `readonly=True`. For paper orders only, untick "Read-Only API" in the **paper** session.
4. In `.env`, set `IBKR_PORT`, `IBKR_CLIENT_ID` and `IBKR_PAPER_ACCOUNT` (your DU number, used only by `paper.py`).

**Market data subscriptions** (on your live IBKR account; shared with paper once you enable sharing in Client Portal):

| Subscription | Cost (IBKR's pricing page; check current) | Why |
|---|---|---|
| OPRA Top of Book (US options L1) | USD 1.50/month, non-pro | Option quotes, greeks, volume, OI |
| US Securities Snapshot & Futures Value Bundle | USD 10/month, waived with USD 30+ commissions | Usually required alongside US data. Confirm with IBKR |

Without these you get delayed data or errors. The screen keeps running and lists what was missing.

**IBKR pacing** (`ratelimit.py`, from IBKR's historical data limitations page):
- max 50 open requests;
- no identical request within 15 s;
- fewer than 6 requests per contract in 2 s;
- 60 requests per 10 minutes for bars of **30 s or less**, with BID_ASK counting twice.

For bars of 1 minute and up (all this screen uses), IBKR replaced the hard cap with a soft
throttle. So the limiter keeps the per-request rules and applies `IBKR_SOFT_REQ_PER_10MIN`
(default 300) instead of 60. Lower it if you see pacing errors.

## Run
```bash
python -m options_screener.screen --date next          # evening/weekend: next session (skips weekends + NYSE holidays)
python -m options_screener.screen --date next --mock   # synthetic demo, no gateway needed
python -m options_screener.backtest --start 2024-01-01 --end 2026-09-30 --underlying ibkr
python -m options_screener.backtest --start 2026-03-01 --end 2026-09-30 --mock
python -m options_screener.status                     # mode, providers, gate status
python -m options_screener.paper --report options_screener/reports/screen_YYYYMMDD.md --paper   # needs PASS
```
Run these from the repo root. Reports go to `options_screener/reports/` (gitignored, except the sample).
`--date next` resolves Friday evening, Saturday and Sunday to Monday, and skips NYSE holidays via `exchange_calendars`.

## Data sources and what costs money

| Source | Used for | Cost |
|---|---|---|
| IBKR TWS API (paper) | Live screen: chains, quotes, greeks/IV, bars for **listed** options and underlyings | Free with an account; data subscriptions above |
| Alpha Vantage `EARNINGS_CALENDAR` | Upcoming earnings (CSV, 3-month horizon) | Free API key. **No time of day**, so "after close / before open" can't be confirmed; the report says so |
| `data/earnings.csv` | Historical earnings dates for backtests | Free (you supply it) |
| **Massive (formerly Polygon)** options | **Backtests**: 1-minute bars of expired contracts (Options Basic and up, 2 years history); quotes for VERIFIED spreads need **Options Advanced** | **Paid**, check massive.com pricing. Set `HISTORICAL_OPTIONS_PROVIDER=massive`, `MASSIVE_API_KEY`, `MASSIVE_HAS_QUOTES=true` (only with Advanced) and `MASSIVE_RPM` |
| CSV (`data/options/*.csv`) | Backtests from files you export | Free; see `data/README.md` |
| ThetaData | Not implemented. Its endpoints weren't verified for this build, so the adapter refuses rather than guesses | |

Bars-only Massive (no quotes) gives a **BARS-ONLY** backtest. Fill quality is then PROXY, and the gate can't pass.

## Known limitations (read before trusting anything)
- **IBKR has no data for expired options.** Real backtests need a paid historical source or your own CSVs. Without one, the backtest is an **underlying-proxy approximation**, gate C is **UNVERIFIED**, and the gate can't pass.
- **Backtest chains are synthetic.** Strikes are on a grid, expiries are Fridays, and delta and price come from Black-Scholes. A generated contract may not have existed. Historical OI, depth and ticker-level option volume/IV aren't available, so those checks and signals are N/A and the score re-weights. Real history must come from the provider's bars for that exact OCC symbol, or the trade is "no data".
- **IV crush.** Earnings candidates are flagged. Implied volatility usually collapses after the report, which can wipe out a correct directional move.
- **Morning spreads are wide.** The first minutes after the open often have 2-3× normal spreads. The entry waits 5 minutes and re-checks the live spread.
- **The round-trip gate is strict.** It allows a total cost of 40% of +5% = **2%**. With one contract, IBKR's USD 1.00 order minimum plus fees is about USD 2.10 round trip, so **options under about USD 1.05 can never pass**, even with no spread at all. In practice it favours liquid, tight names (SPY/QQQ, mega caps).
- **The move-potential rate is a proxy** from underlying bars (ATM, 7 DTE, constant IV).
- **The paper-account check** relies on paper accounts starting with **DU**. That's what Client Portal shows, but IBKR's API docs don't publish it as a rule, so it's enforced as a refusal. Confirm your account number.
- `providers/ibkr.py`, `providers/massive.py` and the paper loop haven't been run against a live gateway or a paid key here. Tests use mocks. Verify them against your setup first (`status`, then a `--mock`-free screen on a weekend).
- Massive authentication uses an `Authorization: Bearer` header. If your key is rejected, check Massive's auth docs.

## Files
`screen.py` (gates A/B/C, ranking), `signals.py`, `fill_quality.py`, `plan.py`, `report.py`,
`backtest.py`, `sim.py`, `stats.py`, `paper.py` (**only** order code), `status.py`, `ratelimit.py`,
`market_calendar.py`, `pricing.py`, `providers/` (`ibkr`, `massive`, `csv_provider`, `catalysts`,
`historical`, `synthetic`, `mock`, `base` with the as-of guard), `tests/`.

Tests: `cd options_screener && .venv/bin/python -m pytest tests -q`. They are offline, with mocked APIs.
