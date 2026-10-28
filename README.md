# OPtions-game-
options trading simulator game 

---

## Options toolkit: screener, probability engine, Grok partner

Three pieces, all read-only. Nothing here places a trade.

| Piece | What it does |
|---|---|
| `screener.py` | Every weekday it checks your watchlist and sends one card per ticker to Telegram: technicals, volatility, events, liquidity, a suggested structure, and that structure's odds and expected value. |
| `prob_engine.py` | The math. Prices options, finds breakevens, max profit and loss, probability of profit and expected value after fees, under two models (market IV and the stock's last 20 days). |
| `GROK_INSTRUCTIONS.md` | The system prompt for your Grok bot, so it reviews trades with the same rules and math and adds live news and X checks. |

### 1. One-time setup (cloud, free, runs on GitHub)

1. Make your Telegram bot if you don't have one: message `@BotFather` in Telegram, send `/newbot`, copy the token. Then message your new bot once, open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `chat` `id` number.
2. Optional: get a free Finnhub key at finnhub.io (adds the earnings calendar and fundamentals).
3. On GitHub, open this repo > Settings > Secrets and variables > Actions.
   - **Secrets** tab, add: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FINNHUB_API_KEY` (optional).
   - **Variables** tab, add: `WATCHLIST` (for example `NVDA,TSLA,AMD,META,PLTR`), `MAX_RISK_PER_TRADE` (dollars, for example `300`), `ACCOUNT_PROFILE` (`wealthsimple` or `moomoo`).
   - Optional variables: `COMMISSION` (per contract, per side) and `FX_FEE_PCT` (0.015 = 1.5%) if your real fees differ from the defaults, and `RISK_FREE_RATE` (0.04 = 4%).
4. Merge this branch into `main`. GitHub only runs scheduled jobs from the main branch.
5. Test it now: repo > Actions > daily-screener > Run workflow. Cards arrive in Telegram in a few minutes.

After that it runs by itself every weekday at 10:45 ET in summer, 9:45 ET in winter.

### 2. Running it on your own computer (needed for Moomoo data)

The cloud version uses free Yahoo data. Moomoo data is better (it comes from your broker), but Moomoo needs its OpenD program running and logged in on the same computer, which GitHub can't do.

1. Install Python 3.10 or newer from python.org (Windows: tick "Add Python to PATH").
2. Download this repo (green Code button > Download ZIP) and unzip it. Open a terminal in that folder.
3. Run these once:
   - Windows: `python -m venv .venv` then `.venv\Scripts\activate` then `pip install -r requirements.txt -r requirements-moomoo.txt`
   - Mac: `python3 -m venv .venv` then `source .venv/bin/activate` then `pip install -r requirements.txt -r requirements-moomoo.txt`
4. Copy `.env.example` to `.env` and fill in the screener section (Telegram, watchlist, max risk, `DATA_SOURCE=moomoo`).
5. Download OpenD from Moomoo's OpenAPI page, open it, log in with your Moomoo account. Leave it running. Your account needs a US options quote right; if the screener says a snapshot failed with a permission message, that is the cause.
6. Run it: `python screener.py`. Without Moomoo: `python screener.py --source yahoo`. Just a few tickers, no Telegram: `python screener.py --tickers NVDA,AMD --no-telegram`.
7. Schedule it:
   - Windows: Task Scheduler > Create Basic Task > Daily, weekdays, 10:15 AM > Start a program > browse to `scripts\run_screener_moomoo.bat`.
   - Mac: run `crontab -e` and add `15 10 * * 1-5 /full/path/to/repo/scripts/run_screener_moomoo.sh` (your computer must be awake and OpenD logged in).

### 3. Reading a screener card (illustrative numbers)

```
NVDA $182.40 | lean UP (+4)                       ticker, price, trend score (-5 to +5)
>50MA >200MA | EMA 9>21>50 | RSI 61 | ATR 2.9% | RVol 1.3 | Gap +0.4%
S/R 176.20 / 189.90                               nearest support / resistance
IV30 48% | IVR 34 IVP 41 | HV20 41 HV60 45 | IV/HV 1.17
Term Nov20 50 / Dec18 47 BACKWARDATION | Skew25 +3.1
EM wk Oct30 +/-6.10 (3.3%) strad 4.90 | mo Nov20 +/-16.80 (9.2%)
OI C 200(45.1k) 190(30.2k) 185(22.0k)             biggest open interest strikes (possible pins)
OI P 170(38.0k) 175(21.5k) 160(19.9k)
P/C vol 0.72 OI 0.85 | SI 1.1% DTC 0.9
Events Earn Nov19 (22d) ! | ExDiv Dec04 (37d) !   ! = inside 45 days
Fund RevG 70% EPSG 80% ROE 90% PE 45 ...          context only, never a timing signal
Liq ATM A
IDEA: bull call debit (IV rank 34, bull lean, IV not rich: debit spread)
Nov20 +185C / -200C | debit $455 | legs liq A
POP impl 37% / real 36% | EV impl $22 / real -$5
Max +$1,021 / -$479 | BE 189.79
P(50% of max) impl 45% / real 41%
EV is near zero in at least one model ...
>> MARGINAL: EV near zero under realized vol
```

- **IV30**: 30 day at-the-money implied volatility. **IVR / IVP**: IV rank and percentile. Free sources don't give IV history, so the toolkit saves one reading per day; it says `IVR building n/20d` until it has 20 days, and uses IV/HV in the meantime.
- **Term**: front month vs next month ATM IV. **Skew25**: 25 delta put IV minus 25 delta call IV, in vol points.
- **EM**: expected move to the weekly and monthly expiry (one standard deviation) with the straddle price as a cross check.
- **POP impl / real**: probability of profit at expiry using option IV / using the last 20 days of actual movement. **EV**: average dollar result after fees, FX and slippage. When the two disagree, the card says so in words. That gap is the edge signal.
- **Verdict**: ENTER CANDIDATE, MARGINAL, or THROW IT OUT. Liquidity F, max loss over your limit, or earnings inside the trade window is an automatic THROW IT OUT.
- These are model estimates, not promises.

### 4. Checking a specific trade before you place it

1. Copy `examples/bull_call_example.json` to a new file, for example `mytrade.json`.
2. Fill in the stock price (`spot`), the IV and 20 day HV, and one line per leg: `qty` 1 to buy or -1 to sell, `strike`, `dte` (days to expiry), `bid`, `ask`, `iv`, `oi`, `volume`. All of these are on the Moomoo option chain (see GROK_INSTRUCTIONS.md section A for where). If you already have a fill, add `"price": 4.55` to that leg.
3. Run `python prob_engine.py mytrade.json --max-loss-limit 300` (use your max risk).
4. You get the verdict, POP and EV under both models, max profit and loss, breakevens, the dominant Greek and the costs.

### 5. Using Grok

1. Open Grok > Customize (or a Grok Project's instructions) and paste the prompt from `GROK_INSTRUCTIONS.md` (between the two lines). Fill in your max risk and account size first. If Grok says it's too long for custom instructions, put it in a Project, or paste it as the first message of a chat.
2. For each trade, paste the INPUT block from section A with your legs filled in. Easiest: paste the screener card, then add the legs you want, your thesis in one line, and ENTERING / HOLDING / ADJUSTING / EXITING. If you ran `prob_engine.py`, paste that output too; Grok will use those numbers.
3. Read the card top to bottom: the VERDICT line first, then **Max loss** (is it inside your limit?), **Event risk** (anything inside the window you didn't plan for?), **What kills this trade**, and **Confidence**. Any `DATA MISSING` line tells you which Moomoo screen to check.
4. For open positions, Grok compares hold vs close now vs the best adjustment, with POP, EV and max further loss for each.

### 6. Tests

`python -m pytest` runs everything offline. `tests/test_prob_engine.py` checks Black-Scholes against textbook values (S=100, K=100, T=1, r=5%, vol 20%: call 10.4506, put 5.5735, plus Hull's dividend example), put-call parity, the IV solver round trip, spreads, condors, calendars and the Monte Carlo. `tests/test_screener.py` runs the whole screener on synthetic data, including a fake Moomoo connection.

---

## snaptrade_watch: SnapTrade + Wealthsimple, watch-only / dry-run

A small Python tool that connects to **SnapTrade** with your own API key, links your
**Wealthsimple (self-directed)** account through SnapTrade's Connection Portal, and reads your
accounts, balances, positions and orders. It can **preview** stock/ETF orders with SnapTrade's
order-impact check. **It does not place orders unless you deliberately turn that on and confirm
each order by hand.**

### What it does and doesn't do
| Does | Doesn't |
|---|---|
| Reads accounts, balances (CAD/USD), positions, open and recent orders, connections | Place, cancel or replace anything by default |
| Quotes on demand (max 10 symbols per call) | Poll in a tight loop |
| Dry-run previews via `get_order_impact` (`POST /trade/impact`), which never places an order | Options (any symbol or action), multi-leg orders, option impact |
| Optional live stocks/ETF orders behind a three-part gate | Crypto trading |
| JSON-lines audit log with redaction | Log or print your consumer key, userSecret, Telegram token or full account numbers |
| | Use SnapTrade's experimental endpoints |

### Personal vs commercial key
- **Personal API key (default, recommended).** Free, and meant for your own accounts. No user registration and no userSecret: the key itself identifies you.
- **Commercial API key (fallback),** e.g. a Build-plan test key. The tool registers one SnapTrade user once (`register`). The returned `userSecret` is shown only once, so it's saved to a `0600` file outside the repo and sent with every user-scoped call.

### Setup
1. Create a SnapTrade **Personal** account at https://dashboard.snaptrade.com/signup, verify your email, **turn on two-factor authentication** in the Dashboard, and create your Personal API key on the API Key page. (One Personal key per person; Personal is currently free.) You do this yourself; the code never signs up or creates accounts.
2. `git checkout claude/snaptrade-watch-only`
3. `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` (or `pip install -r requirements.txt`)
4. `cp .env.example .env`, fill in `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY`, leave `LIVE_TRADING=false`, then `chmod 600 .env`
5. `python -m snaptrade_watch.cli status`
6. Optional test with fake data: `python -m snaptrade_watch.cli link --broker SANDBOX`, open the URL within 5 minutes, then run `accounts` and `portfolio`.
7. `python -m snaptrade_watch.cli link` (a **read-only** connection first). Open the URL within 5 minutes, pick Wealthsimple, enter your credentials, and complete Wealthsimple's 2FA if asked.
8. `python -m snaptrade_watch.cli accounts && python -m snaptrade_watch.cli portfolio`
9. Dry-run a trade: `python -m snaptrade_watch.cli preview --account <last 4 of account> --side BUY --symbol XEQT --units 1 --type Limit --price 30 --tif Day`
10. Only after you've decided to allow live trading: re-link with trade access (`link --trade-connection --reconnect <connection id or last 4>`), set `LIVE_TRADING=true`, and use `place ... --live` with the typed confirmation. Start with **1 share and a Limit order**.

IDs are only ever printed as their last 4 characters. Every `--account`, `--reconnect` and `--order` option accepts that short suffix, and the tool looks up the full id itself. If more than one id matches, it refuses.

### Commands
```
status                              API check, auth mode, LIVE_TRADING state, cap, log path
register                            commercial mode only (one time; skipped if the secret file exists)
link [--trade-connection] [--broker WEALTHSIMPLETRADE|SANDBOX] [--reconnect ID]
connections                         lists connections and flags disabled ones
accounts
portfolio [--account ID] [--json]
quote SYMBOL[,SYMBOL...] --account ID
orders --account ID [--state all|open|executed] [--days N]
preview --account ID --side BUY|SELL --symbol XEQT (--units N | --notional 100)
        --type Market|Limit|Stop|StopLimit [--price P] [--stop S] --tif Day|GTC
place   (same as preview) --live    guarded: see the safety model
cancel  --account ID --order ID --live   guarded the same way
```

### Environment variables
| Variable | Default | Notes |
|---|---|---|
| `SNAPTRADE_CLIENT_ID` | (required) | |
| `SNAPTRADE_CONSUMER_KEY` | (required) | secret; never logged or printed |
| `SNAPTRADE_AUTH_MODE` | `personal` | or `commercial` |
| `SNAPTRADE_USER_ID` | | commercial only; a stable id like `mike-local-1`, never an email |
| `SNAPTRADE_USER_SECRET_FILE` | `~/.config/snaptrade-watch/user_secret` | commercial only; must be mode `0600` and owned by you |
| `LIVE_TRADING` | `false` | live is possible only if this is exactly `true` |
| `MAX_ORDER_VALUE_CAD` | `500` | larger orders are refused, even in dry-run |
| `CAP_USD_CAD_RATE` | `1.5` | a deliberately high USD-to-CAD rate, used only for the cap check |
| `LOG_FILE` | `./logs/snaptrade.jsonl` | gitignored |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | | optional; notifications are off if unset |

### Safety model
1. **Dry-run by default.** If `LIVE_TRADING` is missing, empty, `True`, `1`, `yes` or anything except exactly `true`, the tool is in dry-run mode. In dry-run, the only trading call it ever makes is the order-impact preview.
2. **Three-part live gate** (`orders.require_live_trading_allowed`): `LIVE_TRADING=true` in the environment, **and** the `--live` flag, **and** an interactive terminal where you type the exact phrase shown, e.g. `PLACE BUY 1 XEQT`. Piped input is refused. There's no `--yes` flag and no confirmation through environment variables.
3. **One place where orders are sent:** `orders._submit_live_order` sends the `trade_id` from a fresh preview (`place_order`), so what you confirm is exactly what gets sent. It re-checks the gate inside. `place_force_order` is never used.
4. **Never retried.** Wealthsimple has no idempotent `client_order_id`, so a retry could duplicate an order. If a place call fails or times out, the tool reads your recent orders, logs them, and tells you to check Wealthsimple. After every live order it reconciles against recent orders.
5. **Previews expire** after 5 minutes. If you take longer to confirm, it gets a fresh preview and asks again.
6. **Order cap:** `MAX_ORDER_VALUE_CAD`, checked before the preview and again with the brokerage's own price.
7. **Stocks and ETFs only.** Option actions (`BUY_TO_OPEN`, etc.), option-style symbols, crypto pairs and any non-stock/ETF security type are refused, before any API call.
8. **Audit log:** `logs/snaptrade.jsonl`, one JSON object per line: timestamp with offset, event, mode, last 4 of the account, symbol, side, quantity, order type, impact summary and result. Secrets are removed, and IDs are cut to their last 4 characters.

The confirmation screen shows what SnapTrade recommends you check: account, symbol (with exchange and currency), action, quantity, order type, limit/stop, time in force, estimated cash, commission and FX, and the impact source ("Brokerage preview"). **These are estimates. The brokerage sets the final price and fees.**

### Wealthsimple limits (from SnapTrade's institution matrix)
- Self-directed accounts only (not Wealthsimple Invest / robo).
- Whole shares or a dollar amount. No fractional share counts. A dollar amount only works with Market + Day.
- Order types: Market, Limit, Stop, StopLimit. Time in force: Day, GTC (no FOK or IOC).
- No idempotent orders, so a live place call is never retried automatically.
- Order history: 30 days, 50 orders at most.
- Connections last weeks, not forever. `connections` and `accounts` flag disabled ones; reconnect with `link --reconnect <id>`.
- The broker slug `WEALTHSIMPLETRADE` is checked against SnapTrade's brokerage list when you pass `--broker`.

### Rate limits
250 requests/min per client id, and on Personal keys possibly 10 requests/min per account, shared across balances, positions, orders, details, quotes and so on. The tool spaces calls to one account at least 6 seconds apart. On a 429 it waits for `X-RateLimit-Account-Reset` / `X-RateLimit-Reset` / `Retry-After`, or backs off exponentially with jitter (up to 5 tries) for **read** calls only. There is deliberately no polling loop: SnapTrade warns that frequent polling can get keys disabled.

### Troubleshooting
| Problem | Fix |
|---|---|
| Portal error **1066** | Invalid Wealthsimple credentials. Run `link` again. |
| Portal error **1006** | The 5-minute link expired. Run `link` again. |
| Portal error **1086** | Wrong 2FA/MFA code. Run `link` again and enter a fresh code. |
| Portal error **1012** | The portal session failed. Generate a new link with `link` and retry. If it repeats, check SnapTrade's status and error-code docs. |
| "Connection ... is DISABLED" | `python -m snaptrade_watch.cli link --reconnect <id>` |
| "Rate limited (429)" | Wait a minute. Don't run commands in a loop. |
| "userSecret ... permissions" | `chmod 600 <file>` (commercial mode) |
| "REFUSED (dry-run safety)" | Working as intended. See the safety model. |

### Tests
`pytest` (114 snaptrade_watch tests, no network; the whole repo has 170). The SnapTrade client is mocked. `tests/test_sdk_contract.py` also runs the real SDK's request validation with HTTP stubbed out, so argument and type mistakes are caught.

**Disclaimer:** this is a personal tool, not financial advice. Previews are estimates. You're responsible for anything you choose to place live.
