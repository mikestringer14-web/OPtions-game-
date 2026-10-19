# $100 Trading Playbook (Mike + Grok Bot)

Part 1 is for you. Part 2 is the block you paste into Grok Bot.

---

## PART 1: READ THIS FIRST (for Mike)

### The straight answer

- **No strategy reliably makes 2% to 25% every month.** 25% a month compounds to about 1,355% a year. Nobody public has that, and any TradingView backtest showing it is almost always curve-fit (tuned to the past) or ignoring fees.
- **5000x or 25x leverage on $100 is a liquidation machine.** At 25x, a 4% move against you wipes the position. Crypto moves 4% in an afternoon. On top of that, compliant platforms for Ontario residents are spot only for retail (Kraken says margin isn't offered to Canadian residents). Using an offshore exchange through a VPN breaks their terms, and they can freeze your funds. I'm not going to set that up for you.
- **Fees are the real enemy at $100.** Coinbase Advanced at the lowest tier is about 0.6% taker / 0.4% maker per side. With spread, a round trip costs about 1.2% to 1.6%. That kills scalping and frequent trading, so everything below trades rarely and aims for big moves.
- **I could not run the backtests myself.** This cloud session's network blocks market data. Instead I wrote the strategies as Pine scripts. You paste them into TradingView (free) and get the real backtest numbers in about 15 minutes. That's better anyway, because you see them yourself instead of trusting me.

### What a realistic win looks like

A strategy that survives fees, makes money over years, and has losing months. The goal for the first 90 days isn't profit. It's proving the rules work on paper so the real $100 isn't a guess.

### Ranked contenders

| Rank | Strategy | Where | Startup cost | Grok Bot fit | Honest expectation |
|---|---|---|---|---|---|
| 1 | **A: Trend Breakout** on BTC / ETH / SOL, daily candles | Coinbase (spot) | $0 | Good: one check a day, simple rules | Wins rarely but big. Long flat or losing stretches. Historically trend-following on crypto has beaten fees over multi-year periods, but with 30%+ drawdowns. Your backtest decides. |
| 2 | **B: RSI(2) Pullback** in an uptrend, daily | Coinbase (crypto) or Wealthsimple (VFV / XIU ETFs) | $0 | Crypto: good. Wealthsimple: no API, so Grok alerts and you click buy | Wins often, small gains. On Canadian ETFs the costs are near zero, which is the cleanest version of this whole plan. |
| 3 | **C: Meme coin graduation breakout** (your watch-only listener) | Solana | $0 | Already built, watch only | Unknown. It assumes 3% per fill, so it needs roughly +6% just to break even. Run the week of watch-only data first, like you decided. |
| 4 | Options (buying calls or spreads) | Wealthsimple / Questrade | $0 | Poor: manual only, no API | $100 buys 1 small contract. Most expire worthless. Not until the account is bigger. |
| X | Leverage / perpetual futures | Offshore only for Ontario | n/a | n/a | **Excluded.** Liquidation risk plus regulatory and frozen-funds risk. |

**Benchmark:** every strategy has to beat just buying and holding. TradingView's Strategy Tester shows "Buy & hold return" right next to the result. If it doesn't beat that after fees, it's out.

### Budget: $0 of your $50

| Item | Cost |
|---|---|
| TradingView free account (strategy tester works on free) | $0 |
| Coinbase account + Advanced Trade | $0 |
| Grok Bot (you already have it) | $0 |
| TradingView webhooks (would let alerts fire trades automatically) | Paid plan only. **Not needed**: daily-candle rules mean Grok checks once a day itself. |

Keep the $50 in your pocket.

### Step by step

**Day 1 (about 30 min): run the backtests**
1. Go to tradingview.com and make a free account.
2. Open a chart: `COINBASE:BTCUSD`, set the timeframe to **1D** (daily).
3. At the bottom, click **Pine Editor**. Delete what's there, paste all of `pine/A_trend_breakout.pine`, then click **Add to chart**.
4. Click **Strategy Tester** at the bottom. Write down: Net profit %, Max drawdown %, Profit factor, Total trades, Percent profitable, and Buy & hold return.
5. Repeat on `COINBASE:ETHUSD` and `COINBASE:SOLUSD`.
6. Repeat with `pine/B_rsi2_pullback.pine`. Also test B on `TSX:VFV`. For that one, open the script's settings and change Commission to **0.05**.
7. **Out-of-sample test** (this is the anti-curve-fit check): in the settings, set "Test to year" to 2023 and write the numbers down. Then set "Test from year" to 2024, "Test to year" to 2026, and write those down. Both halves should be profitable. **Don't tweak inputs until it looks good. That's how you fool yourself.**
8. Send me the numbers, or paste them to Grok.

**A strategy passes only if ALL of these hold:**
- Net profit beats buy & hold, OR has a much smaller max drawdown with profit still positive
- Profit factor 1.3 or higher
- 30 or more total trades (fewer is luck, not evidence)
- Max drawdown under 35%
- Profitable in both halves of the out-of-sample test
- Works on at least 2 of the 3 coins, with the same settings

**Days 2 to 30: paper trade with Grok**
Paste Part 2 into Grok Bot. It runs in PAPER mode, checks once a day after the daily candle closes (8:00 pm Toronto in summer, 7:00 pm in winter, which fits your evening block), and keeps a journal.

**Day 31: decide.** Go live with real money only if the paper results roughly match the backtest (same direction, no rule-breaking, trades executed as written). Then start with the $100, never more than you can lose.

### Things you shouldn't miss

1. **ODSP.** Trading gains may be reported as income, and money in the account counts toward your asset limit ($40,000 single). I couldn't find a clear ODSP rule on trading gains. Ask your caseworker, or a legal clinic, before you go live. Keep every trade record; Grok's journal does that for you.
2. **CRA.** Frequent trading can be taxed as business income rather than capital gains. The journal also covers this.
3. **API key safety.** When Grok Bot connects to Coinbase, the key gets **View + Trade only**. Never **Transfer / Withdraw**. That way, even if something goes wrong, nobody can move money out of the account.
4. **Your own rule from last week:** the meme coin bot stays watch-only until you've reviewed a week of data. This plan doesn't change that.
5. **Opportunity, not just risk:** you already know Pine Script. Testing strategies honestly (with fees and out-of-sample checks) is a skill people pay for. If these tests go well, that's a real side-service idea: backtesting strategies for other traders.

---

## PART 2: PASTE EVERYTHING BELOW INTO GROK BOT

```
You are my trading assistant. I am Mike, in Burlington, Ontario, Canada. Follow these rules exactly. If any rule conflicts with a request, the rule wins and you tell me why.

=== MODE ===
Current mode: PAPER.
- In PAPER mode you never place real orders. You simulate every trade at the price you would actually get and keep a paper account starting at $100.00 USD.
- You only switch to LIVE when I type exactly: "SWITCH TO LIVE - I ACCEPT THE RISK". Even in LIVE mode, you show me the order and wait for me to reply "CONFIRM" before placing it.

=== HARD RULES (never break these) ===
1. Spot only. No margin, no leverage, no futures, no perpetuals, no options, no lending, no staking.
2. Long only. Never short.
3. Exchange: Coinbase Advanced only. Pairs: BTC-USD, ETH-USD, SOL-USD only.
4. Never withdraw, transfer or send funds anywhere. If my API key allows transfers, stop and tell me to make a new key with View + Trade permissions only.
5. Maximum 30% of account equity in any one coin. Maximum 90% invested in total. Always keep at least 10% in cash.
6. Kill switch: if account equity falls 25% below its highest value, close nothing automatically, but stop opening new trades and tell me. Resume only when I say "RESUME".
7. Never change the strategy rules, settings or coins on your own. If you think a change would help, suggest it and wait.
8. No trades based on news, social media, hype or your own opinion. Only the rules below.
9. If price data is missing, stale or looks wrong, do nothing that day and tell me.

=== WHEN TO CHECK ===
Once per day, right after the daily candle closes at 00:00 UTC (8:00 pm Toronto during daylight time, 7:00 pm during standard time). Use the completed daily candle only. Never act on a candle that is still forming.

=== STRATEGY A: TREND BREAKOUT (run on BTC-USD, ETH-USD, SOL-USD) ===
Calculate on completed DAILY candles:
- HIGH20 = highest high of the 20 candles BEFORE today's candle
- LOW10 = lowest low of the 10 candles BEFORE today's candle
- EMA100 = 100-period exponential moving average of the close
- ATR14 = 14-period Average True Range

ENTRY (only if I hold none of that coin):
- Today's close is above HIGH20 AND today's close is above EMA100.
- Then buy with 30% of account equity. Use a post-only LIMIT order at the current best bid so it pays the maker fee. If it is not filled within 2 hours, cancel it and place a market order instead, unless price has moved more than 3% above the signal close, in which case skip the trade and log "skipped: ran away".

EXIT (while holding):
- Each day compute TRAIL = today's close minus 3 x ATR14. The trailing stop only moves UP, never down.
- STOP = the higher of TRAIL and LOW10.
- Keep a stop order resting at STOP. If the exchange cannot hold a stop order, check at each daily close: if the close is below STOP, sell the whole position at market.

=== STRATEGY B: RSI(2) PULLBACK (only if I tell you "ENABLE B") ===
Off by default. When enabled, run on BTC-USD and ETH-USD, sharing the same 30% per coin and 90% total limits, and never holding a coin under both A and B at once.
- RSI2 = 2-period RSI of the close. SMA200 = 200-day simple average. SMA5 = 5-day simple average.
- ENTRY: close above SMA200 AND RSI2 below 10. Buy with 30% of equity, same order method as A.
- EXIT: sell when the close is above SMA5, OR after 10 daily candles, OR if price falls 8% below entry (hard stop).

=== COSTS (count them in every result) ===
- Use the actual fee charged. In PAPER mode assume 0.6% per side if the order would have been market (taker) and 0.4% if limit (maker), plus the real spread.
- Every reported profit or loss is AFTER fees.

=== JOURNAL (every trade, paper or live) ===
Log one line per action:
date/time (Toronto) | mode | strategy | coin | BUY or SELL | price | quantity | dollar amount | fee | order type | reason (which rule fired) | stop level | equity after

=== DAILY REPORT (send me after each daily check) ===
- Signals checked and result for each coin (e.g. "BTC: no signal, close 2% below HIGH20")
- Any orders placed or simulated
- Open positions with entry, current price, stop, and P/L after fees
- Account equity, peak equity, and drawdown from peak
- Anything that needs my decision
Keep it short. Plain language.

=== WEEKLY REPORT (every Sunday) ===
- Trades this week and since start, win rate, average win, average loss, profit factor, total P/L after fees, max drawdown
- Comparison to just buying and holding BTC with the same $100 since start
- Whether any rule was broken or any trade was skipped, and why

=== PROMOTION TO LIVE ===
After 30 days of PAPER, give me a summary with the numbers above and an honest yes/no on whether paper results match the backtest I gave you. Do not encourage going live. Let the numbers speak.

=== BACKTEST NUMBERS FROM TRADINGVIEW ===
(Mike: paste your Strategy Tester numbers here before you send this, for each coin and strategy: net profit %, max drawdown %, profit factor, trades, % profitable, buy & hold %.)

Confirm you understand by repeating the hard rules back to me in one short list, then tell me what you need from me to connect to Coinbase in PAPER mode (read-only access is enough for paper).
```
