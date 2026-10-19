# Low-capital trading research + paper trading system

Status: **research phase. No strategy has passed validation yet. Nothing here places orders.**

The code is built and tested (29 tests). It has **not** been run on real market data yet,
because the cloud session that built it can't reach market data. You run step 1 below on
your own computer and the real report is generated there.

---

## 1. Feasibility assessment

Labels: **[verified]** = checked against a source this session. **[secondary]** = from
third-party reporting only. **[from research memory]** = well-known published research, not
re-checked this session. **[assumption]** = my estimate, stated so you can change it.

### Q1. What can Grok actually do?
- Chat, research, write and explain code. **[verified via xAI docs]** The xAI API offers server-side tools, including a Python code-execution sandbox, and function calling to your own code. ([docs.x.ai tools](https://docs.x.ai/developers/tools/overview))
- Scheduled "Tasks" / "Automations" in the Grok app that run a prompt on a schedule and notify you. **[secondary]** ([MindStudio](https://mindstudio.ai/blog/grok-automations-scheduled-tasks-email-triggers), [TestingCatalog](https://www.testingcatalog.com/grok-set-to-gain-tasks-feature-for-periodical-execution.md))
- Trading through a connected Coinbase account. **[secondary]** ([HokaNews](https://www.hokanews.com/2026/09/grok-bot-can-execute-crypto-trades-247.html), [Composio](https://composio.dev/toolkits/coinbase/framework/grok-bot)). I couldn't verify how permissions, approval or error handling work.
- **Not established:** running a continuous process, storing credentials securely, or enforcing risk limits reliably.
- **Decision:** Grok is the analyst and reporter. Deterministic Python does the signals, sizing, limits and kill switches. See `GROK_OPERATING_PROMPT.md`.

### Q2. Cheapest practical architecture: $0
```
Coinbase public candles (free, no key) --> Python on your Linux box (cron, once a day)
    --> rt/validate.py : backtest + validation report with go/no-go gates
    --> rt/paper.py    : daily paper trading, journal, kill switches, spread sampling
    --> paper/daily_report.md --> you paste to Grok --> analysis + weekly review
TradingView free: load pine/ scripts to eyeball the same rules on a chart (cross-check)
```
TradingView webhooks need a paid plan ([CrossTrade](https://crosstrade.io/blog/tradingview-plan-for-webhook-alerts)), but nothing here needs them. Daily rules run from cron.

### Q3. What can you access from Ontario?
| Instrument | Platform | Status |
|---|---|---|
| Spot crypto | Coinbase, Kraken (registered restricted dealer) | Accessible. Kraken says margin isn't offered to Canadian residents. **[verified]** ([Kraken](https://support.kraken.com/ca/sections/360006010651-margin-trading-limitations-restrictions)). Check Coinbase's Ontario status on the OSC's registered crypto platform list. |
| Crypto perps / leverage | Compliant platforms | Not available to Ontario retail on compliant platforms **[secondary]** ([CoinPerps](https://www.coinperps.com/learn/best-crypto-futures-platforms-in-canada)). **Excluded.** |
| Canadian ETFs / stocks | Wealthsimple, Questrade, IBKR Canada | Accessible. IBKR has an API and paper trading, but sources say you need a live account to get paper access, and one old report says API orders on the TSX were rejected **[secondary]** ([QuantConnect forum](https://www.quantconnect.com/forum/discussion/7303/canadians-not-allowed-to-use-interactive-brokers-api-anymore/)). |
| Listed options | Wealthsimple, Questrade, IBKR | Accessible, but $100 is too small (see Q7). |

### Q4. Which candidates have credible evidence and can be tested free?
- **Time-series momentum / trend following:** a long published history across asset classes, and crypto-specific momentum studies too **[from research memory]**: Moskowitz, Ooi & Pedersen 2012, "Time Series Momentum"; Liu & Tsyvinski, "Risks and Returns of Cryptocurrency". Testable here: strategies A and C.
- **Long-term moving-average timing:** Faber 2007, "A Quantitative Approach to Tactical Asset Allocation" **[from research memory]**. Testable: strategy C.
- **Short-term reversal inside an uptrend (RSI(2)):** a practitioner result (Connors), mostly on equity indices **[from research memory]**. Testable: strategy B.
- **Meme coin graduation breakout:** no credible evidence. Your watch-only listener is collecting data to test it.

### Q5. Data and execution assumptions
- **Data:** Coinbase Exchange daily candles, no key needed, about 300 candles per request **[secondary]** ([Coinbase docs](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles.md)). UTC days. The still-forming candle is always dropped. Gaps are reported.
- **Fees:** 0.60% taker per side, the lowest Coinbase Advanced tier **[secondary]** ([fee schedule](https://conductatlas.com/platform/coinbase/coinbase-fee-schedule/advanced-trade-makertaker-fee-schedule)). Change `fee_rate` in `config.json` if your tier differs.
- **Slippage:** 0.10% per side **[assumption]**. The paper trader samples the live spread daily, so this gets checked against reality.
- **Fills:** next day's open (never the signal candle's close). Stops fill at the stop, or at the open if price gaps through it. Orders under $1 are skipped.
- **Not modelled:** CAD to USD conversion. Budget roughly 1% once, when you fund the account **[assumption]**. Also taxes.

### Q6. $50 limit: yes, $0
| Item | Cost |
|---|---|
| Python, these scripts, Coinbase public data | $0 |
| TradingView free (Pine strategy tester) | $0 |
| Grok (you have it); xAI API not needed | $0 |
| Coinbase account for later | $0 |
| **Total** | **$0** (mandatory). Optional: nothing. |

### Q7. What stops a $100 account from working economically?
- **Costs:** a round trip needs about a 1.41% price move just to break even (0.6% fee + 0.1% slippage, each side). That kills scalping and frequent trading.
- **Position size:** at 0.5% risk per trade with a 10 to 15% stop, a position is only about $3 to $5. That's above Coinbase's minimum, but a 30% winning trade makes about $1. So **account-level returns are small by design.**
- **Raising risk to get bigger returns grows drawdowns faster than returns.** The report's risk-level table shows this for each strategy.
- **Options:** one contract plus commission can be most of the account, so there's no way to manage risk.

### Q8. What return targets are plausible?
- **Monthly 2 to 25% is not a defensible target.** Hitting it would need leverage or very concentrated bets, with a high chance of ruin.
- **Defensible research target:** positive out-of-sample expectancy after costs, with max drawdown at or under 20%. At 0.5 to 1% risk per trade, that likely means **low single-digit to low double-digit % per year** on the account.
- **The real upside of a $100 phase is proving an edge cheaply,** so that adding capital later is a decision based on evidence.

---

## 2. Candidate ranking (all UNVALIDATED until you run step 1)

Scoring, 1 to 5, with weights: evidence 25%, cost sensitivity 20%, catastrophic-loss risk 15%, Ontario access 15%, automation fit 10%, capital efficiency 10%, setup complexity 5%.

| Rank | Candidate | Market | Score | Why |
|---|---|---|---|---|
| 1 | **A: Trend Breakout** (20-day high + EMA100 filter, 3x ATR trail) | BTC/ETH/SOL spot, Coinbase | 3.9 | Strongest evidence family. Few trades, so low cost drag. Fully automatable daily. |
| 2 | **C: SMA-200 Trend Filter** | BTC/ETH/SOL spot | 3.7 | Simplest and cheapest, but very few trades, so it may fail the 30-trade gate on 3 coins. |
| 3 | **B: RSI(2) Pullback** | Canadian ETFs (VFV/XIU) on Wealthsimple; crypto as a second test | 3.4 | Near-zero costs on ETFs. Wealthsimple has no API, so it's manual. On crypto, costs hurt it. |
| 4 | Meme graduation breakout | Solana | 2.0 | No evidence yet, about 6% round-trip costs, rug risk. Watch-only data collection continues. |
| Rejected | Perps/leverage; scalping; market making; funding/basis; options at $100 | | | Not accessible from Ontario, costs over 1.41% per round trip, needs infrastructure, or account too small. |

**First strategy to test: A on BTC-USD, ETH-USD and SOL-USD.**

---

## 3. Run it (on your Linux box)

```bash
cd trading_research
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests -q                 # expect: 29 passed

# Step 1: real backtest + validation (downloads Coinbase daily candles to data/)
.venv/bin/python -m rt.validate --strategy A_trend_breakout
.venv/bin/python -m rt.validate --strategy C_sma_trend_filter
.venv/bin/python -m rt.validate --strategy B_rsi2_pullback
# ETFs: export daily data from TradingView (chart > Export chart data) as data/VFV.csv, then
.venv/bin/python -m rt.validate --strategy B_rsi2_pullback --symbols VFV --csv-dir data
# (also set fee_rate 0.0 and slippage_rate 0.0005 in a copy of config.json, pass it with --config)
```

Each run writes `reports/<strategy>_<time>.md` and `.json`. Every individual backtest (there are about 100 per report) is appended to `reports/param_log.jsonl`, so the number of tries is on record.

**Step 2: paper trade, only for a strategy whose verdict is PASS.** Set `paper.strategy` in `config.json`, then add a cron job for 00:20 UTC (8:20 pm Toronto in summer, 7:20 pm in winter):
```bash
crontab -e
20 0 * * * cd /path/to/trading_research && .venv/bin/python -m rt.paper >> paper/cron.log 2>&1
```
`python -m rt.paper --status` shows the latest report. `--resume` clears a halt after you've reviewed it.

**Kill switches (in code, not Grok):** stale or missing data means it does nothing that day and raises an alert. Three fetch errors in a row halt it. A daily loss of 3% or more halts it. A drawdown of 25% or more halts it. Halts block new entries until you run `--resume`, and the halted period stays blocked in the record.

---

## 4. Go / no-go gates (fixed in `config.json` BEFORE testing)

| Gate | Threshold | Why |
|---|---|---|
| Out-of-sample trades (2023 onward, pooled) | at least 30 | Fewer is anecdote. |
| Out-of-sample expectancy per trade (R) | above 0 | It has to make money after costs. |
| Out-of-sample profit factor | at least 1.2 | A cushion for costs being worse live. |
| Bootstrap 5th percentile of mean R | above 0 | About 95% confident the edge isn't luck. |
| Max drawdown (0.5% risk) | at most 20% | Something you can live through. |
| Profit factor with 1.5x costs | at least 1.05 | Survives worse fills. |
| Expectancy with 2x costs | above 0 | Not living on a knife edge. |
| Expectancy with entries delayed 1 extra day | above 0 | Not dependent on perfect timing. |
| Parameters each moved ±20%, share profitable | at least 70% | Not curve-fit to one setting. |
| Coins profitable out-of-sample | at least 2 of 3 | Not one lucky coin. |
| Calendar years profitable | at least 50% | Works across regimes. |

Sanity check already done: on pure random-walk data (no edge exists), the gates returned **FAIL**, as they should. If a strategy fails, the answer is more research or more paper trading, not lower gates.

**Before any live money (separate from the gates):** at least 60 days and 20 closed paper trades with results consistent with the backtest; a Coinbase API key with View + Trade only (no transfer), IP-restricted, stored in an environment variable, never pasted into a chat; and your ODSP caseworker has confirmed how trading income is treated.

---

## 5. Files
- `rt/data.py`: Coinbase daily candles, CSV import (including TradingView exports), data quality checks
- `rt/indicators.py`: SMA, EMA, Wilder ATR/RSI, prior-bar highs and lows (no lookahead)
- `rt/strategies.py`: A, B and C as deterministic rules
- `rt/engine.py`: portfolio backtester (fills, gaps, fees, slippage, sizing, caps, halts)
- `rt/validate.py`: the full protocol, the gates and the markdown report
- `rt/paper.py`: daily paper trader with journal, report, spreads and kill switches
- `config.json`: every editable risk, cost and gate number
- `GROK_OPERATING_PROMPT.md`: Grok's role, limits and escalation rules
- `../trading_playbook/pine/`: the same A and B rules for TradingView
