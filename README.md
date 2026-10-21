# OPtions-game-
options trading simulator game 

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
`pytest` (114 tests, no network). The SnapTrade client is mocked. `tests/test_sdk_contract.py` also runs the real SDK's request validation with HTTP stubbed out, so argument and type mistakes are caught.

**Disclaimer:** this is a personal tool, not financial advice. Previews are estimates. You're responsible for anything you choose to place live.

---

## options_coach: Black-Scholes numbers for the Grok options coach

Two parts, both standard-library Python (no installs needed):

1. **`grok/GROK_SYSTEM_PROMPT.md`**: the instructions you paste into Grok. It makes Grok verify price, IV,
   earnings, news and X sentiment before claiming anything; steer your trade ideas with a modified plan and the
   reason in dollars instead of refusing; ask why you want a trade; and switch to fast mode with a protective
   order when things are moving.
2. **`options_coach/`**: a calculator that prints a numbers block to paste into Grok with your trade idea.

```
# one option: fair value, Greeks, prob ITM, expected move
python -m options_coach.cli price --type C --spot 150 --strike 155 --dte 30 --iv 32

# implied vol from a market price, compared with historical vol
python -m options_coach.cli iv --type P --spot 150 --strike 140 --dte 30 --price 1.85 --hv 25

# any multi-leg trade: max profit/loss, breakevens, prob of profit, position Greeks, what-if grid, flags
python -m options_coach.cli strategy --symbol XYZ --spot 150 --dte 30 --account 5000 +1C150@4.10 -1C160@1.30

# how many contracts fit your risk limit
python -m options_coach.cli size --account 5000 --risk-per-contract 280 --max-risk-pct 5
```

Leg format: `+1C150@4.10` = buy 1 call, strike 150, at 4.10. `-2P140@1.10` = sell 2 puts. `+100S@148.50` = 100
shares. Add `~45` to force a leg's IV to 45%. Leave off `@price` to have the model price the leg at `--iv`.
`--rate` defaults to 4%; set it to the current 3-month T-bill yield. Prices are European-style Black-Scholes,
so they slightly understate American options where early exercise matters.

Tests: `python -m pytest tests/test_options_coach.py`
