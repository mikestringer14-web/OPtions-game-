# Options morning screener (RESEARCH ONLY, C$100, one position)

An evening / pre-market screen for **single-leg long calls or puts** that might gain **+5% (stretch
+10%) in option price between the open and 10:30 ET**, sized for **one position of up to C$100**,
and whose recent trading shows they can actually be bought and sold.

> **Research only. Not financial advice. Options can lose 100% of the premium.** No code path in
> this folder places, previews or routes an order, connects to a broker, or calls a trading
> endpoint. `paper.py` was removed. API keys are read from environment variables only and are
> never printed or logged.

## What it does

A candidate must pass **all three** gates **and** fit the budget:

| Step | What it checks | Data |
|---|---|---|
| **A: catalyst** | Earnings on the as-of or target day, events in `config.toml [events]`, or a news spike. BMO/AMC is shown only if the source says so, otherwise "time unverified" plus an IV-crush warning | Alpha Vantage (free key) or `data/earnings.csv` |
| **B: move potential** | Share of the last 20 mornings where an ATM option (Black-Scholes, 7 DTE, time decay each minute) would have hit **+5% before the -15% stop or the 10:30 ET time stop**, walking 1-minute bars forward (min 40%), plus unusual volume, IV rank/change and momentum | Underlying 1-minute bars (**MODEL ESTIMATE**). The old optimistic proxy is kept as `morning_option_move_proxy_legacy` for comparison only |
| **C: fill quality** | Per strike and expiry over the last 1-5 sessions: morning/close spread, first-hour and day volume, active minutes, OI and OI change, seconds between prints, depth, round-trip cost vs the +5% target | Option 1-minute bars; quotes give **VERIFIED**, bars only give **PROXY** |
| **Budget** | ASK in CAD incl. fees and FX must fit C$100, contract multiplier must be 100 | `sizing.py` |

Sizing (all in `config.toml [account]`):
```
usd_budget               = capital_cad * cad_usd_rate * (1 - fx_cost_pct/100)     # C$100 -> ~US$70.92 at 0.72
max_premium_per_contract = (usd_budget - fee_per_contract_usd) / 100              # ~US$0.708 per share
contracts                = floor(usd_budget / (ask*100 + fee))                     # must be >= 1
```
Anything that doesn't fit is rejected as **"unaffordable at C$100"**. The report shows, per
candidate: contracts, entry cost USD and CAD, % of C$100, max loss CAD (full premium + fees), CAD
lost at the -15% stop, breakeven at expiry, P/L at +5% and +10% after the exit fee and FX.
`cad_usd_rate` is a fallback: the screen first tries the Bank of Canada Valet API (free, no key,
cached daily, https://www.bankofcanada.ca/valet/docs). Max 3 actionable candidates are listed;
take **one** of them at most (`max_open_positions = 1`, `max_new_trades_per_day = 1`).
Debit spreads are shown in a separate **research-only** table: Wealthsimple has no multi-leg orders.

If nothing qualifies the report prints exactly:
`NO TRADE — no verified opportunity meets the capital, liquidity, pricing, and defined-risk requirements.`
Filters are never loosened to force a trade.

**Plan per candidate:** after 9:35 ET on a 5-minute opening-range break, BUY limit between mid and
ask, never above the max debit, cancel after 60 s, at most 2 revisions; target +5%, stretch +10%,
stop -15%; exit if the range is reclaimed or the spread blows out; time stop 10:30 ET.
Each candidate also gets a Black-Scholes scenario line at 10:30 ET (underlying +1% / -1% / flat,
IV +5 / -5 points), labelled MODEL ESTIMATE. Fields are tagged VERIFIED / MODEL ESTIMATE /
ASSUMPTION / UNVERIFIED.

## Setup
```bash
cd options_screener
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt     # Python 3.11+, no ib_async needed
cp .env.example .env            # put MASSIVE_API_KEY=... here locally; never commit it
cd .. && options_screener/.venv/bin/python -m options_screener.status
```

Environment variables (all optional, all read from the environment or `.env`):

| Variable | Used for |
|---|---|
| `MASSIVE_API_KEY` | `--provider massive` (Massive free tier). Sent only in an `Authorization: Bearer` header |
| `ALPHAVANTAGE_API_KEY` | Earnings calendar (no time of day, so earnings time shows as unverified) |
| `HISTORICAL_OPTIONS_PROVIDER` | Backtests from your own data: `csv`, `massive` or `none` |

## Morning commands (run from the repo root)
```bash
# evening before / early morning: screen the next session (skips weekends + NYSE holidays)
options_screener/.venv/bin/python -m options_screener.screen --date next --provider massive
# a specific day
options_screener/.venv/bin/python -m options_screener.screen --date 2026-10-20 --provider massive
# demo / plumbing check (NOT market data)
options_screener/.venv/bin/python -m options_screener.screen --date 2026-10-20 --provider mock
options_screener/.venv/bin/python -m options_screener.screen --date 2026-10-20 --provider synthetic
# backtest with the single-position C$100 model
options_screener/.venv/bin/python -m options_screener.backtest --start 2026-05-01 --end 2026-10-16 --provider mock
```
Output: `options_screener/reports/morning_screen_YYYY-MM-DD.md` (+ `.json`), also printed.
`--offline` skips the FX lookup. `data.provider` in `config.toml` sets the default provider.

## Data providers and their limits

| Provider | What it is | Banner |
|---|---|---|
| `mock` | Deterministic synthetic market with synthetic quotes. Report format only | MOCK DATA |
| `synthetic` | Mock underlying, options priced only by Black-Scholes (no quotes, no OI) | MOCK DATA |
| `massive` | **Massive (formerly Polygon.io) FREE tier**, end-of-day data | DELAYED / END-OF-DAY DATA, with the real as-of date |

**Massive free tier, verified from the official docs (Oct 2026):**
- Stocks custom bars (daily + 1-minute, end-of-day): https://massive.com/docs/rest/stocks/aggregates/custom-bars
- Options contracts reference (strike, expiry, type, `shares_per_contract`): https://massive.com/docs/rest/options/contracts/all-contracts
- Options custom bars (1-minute aggregates with trade counts `n`): https://massive.com/docs/rest/options/aggregates/custom-bars
- Previous-day bar: https://massive.com/docs/rest/options/aggregates/previous-day-bar
- **Not on the free tier:** the option chain snapshot (OI, greeks, IV, quotes), https://massive.com/docs/rest/options/snapshots/option-chain-snapshot, and quotes (Options Advanced).
- **Rate limit: 5 requests per minute**, counted separately for stocks, options and reference data: https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis

What that means here (nothing the free tier lacks is invented):
- **bid/ask:** none. The ask used for sizing is a **MODEL ESTIMATE** (EOD close + `proxy_spread_pct`/2). Affordability is DEGRADED and marked `*`.
- **IV and delta:** **derived** by Black-Scholes from the option's end-of-day close.
- **Open interest, displayed size, ticker option volume, IV history:** n/a (free tier). The OI, OI-collapse and depth checks show N/A and the unusual-volume / IV-rank signals are DEGRADED.
- **First-hour option volume:** from the previous sessions' 1-minute bars (end-of-day history), never live.
- Requests go through one 5/min limiter per bucket and a disk cache (`data/cache/massive`, past dates only). An HTTP 429 waits 60 s and retries once. The default universe is `[data] massive_symbols` (15 names) because of the limit. Expect a few minutes per run: about 2 stock calls per symbol, 1 reference call and up to 8 option calls per symbol that reaches gate C.

## Backtest
For each past session the screen runs on an as-of view fixed at the prior close (lookahead raises
`LookaheadError`), then the morning plan is simulated on 1-minute bars: fills need volume at the
limit, entries pay the ask, exits get the bid, the stop is checked before the target.
The report has the original validation (70/30 split, bootstrap, 2x costs, 1-minute delay,
perturbation, with vs without gate C) plus the **single-position C$100 model**: one trade per day,
sized at the prior close's ask, exits per the plan; hit rates for +5% and +10% before the stop /
time stop, CAD expectancy per trade, worst day, max drawdown on C$100, and the legacy vs new proxy
comparison. **Mock and synthetic results are not evidence of a real edge.** The PASS gate needs
VERIFIED (real historical quotes) data and can never pass on mock, synthetic or proxy data.

## Known limitations (read before trusting anything)
- **Data delay.** The free tier is end-of-day. Nothing here is a live quote. Check the live bid/ask in Wealthsimple before doing anything.
- **One trade can lose the full C$100.** A long option can expire worthless; the stop is a plan, not a guarantee (gaps, wide spreads, no fill).
- **IV crush.** After earnings, IV usually collapses and can wipe out a correct direction call.
- **Cheap options have wide % spreads.** The options that fit C$100 (under ~US$0.71) often have a 1-cent tick that is 2-10% of the price, so they often fail the round-trip gate (2% total).
- **FX eats small targets.** With the 1.5% buffer each way, a +5% option move nets only about +1.5% in CAD after fees, before the bid/ask spread; the report shows the exact CAD figure.
- The Massive adapter is tested against recorded-format fixtures (`tests/fixtures/massive`, built from the documented response schema), not a live key.
- `providers/ibkr.py` is kept but optional and unused; nothing imports it and `ib_async` is not a requirement.

## Files
`screen.py` (gates, budget, ranking), `sizing.py` (C$100 math), `fx.py` (Bank of Canada rate),
`signals.py`, `fill_quality.py`, `plan.py`, `report.py`, `backtest.py`, `sim.py`, `stats.py`,
`status.py`, `ratelimit.py`, `market_calendar.py`, `pricing.py`, `providers/` (`massive`, `mock`,
`historical` incl. `synthetic_market`, `synthetic`, `csv_provider`, `catalysts`, `base` with the
as-of guard, optional `ibkr`), `tests/`.

Tests: `cd options_screener && .venv/bin/python -m pytest tests -q` (offline, mocked APIs).
Lint: `.venv/bin/ruff check . --exclude .venv --select F,B,E9`.
