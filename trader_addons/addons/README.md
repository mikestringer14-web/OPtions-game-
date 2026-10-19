# Watch-only add-ons: safety fallback + graduation listener

These add-ons **only read public data and write log files**. They do not import or
change `buy.py`, `sell.py`, `sleeve_exit_loop.py`, `positions.json` or `trading_meta.json`,
they never open `wallet.json` or any key, and they cannot send a transaction.

## Install

```bash
cp -r addons /workspace/trader/          # this folder becomes /workspace/trader/addons
cd /workspace/trader/addons
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests -q      # expect: 52 passed
```

Optional env vars (all optional, all free):

| var | default | what it does |
|---|---|---|
| `HELIUS_API_KEY` | unset | Uses Helius free-tier RPC instead of the public RPC. Recommended: the public RPC rate-limits `getTokenLargestAccounts` hard. Only ever used as part of the RPC URL, and scrubbed from all logs. |
| `SOLANA_RPC_URL` | unset | Any other RPC URL (wins over Helius). |
| `DEXSCREENER_RPM` | 60 | Shared DexScreener limit for the whole process. |
| `RPC_RPM` / `SAFETY_API_RPM` | 120 / 30 | RPC limit, and the limit for RugCheck + GoPlus. |
| `SAFETY_MAX_HOLDER_PCT` | 15 | Whale threshold. |
| `SAFETY_MIN_LIQUIDITY_USD` | 50000 | Minimum liquidity on the top Solana pair. |
| `RUGCHECK_MAX_SCORE` | unset | Also fail RugCheck reports above this `score_normalised`. |
| `BREAKOUT_VOLUME_RATIO` | 1.0 | Breakout minute volume must be above this multiple of the range average. |

For the systemd service, put them in `addons/.env` (`chmod 600`).

## Safety check

```bash
.venv/bin/python safety_fallback.py <mint> [--pool <pool_address>]   # exit 0 = PASS, 1 = FAIL
```

1. RugCheck summary first (8s timeout). A usable report is the verdict: FAIL on any `danger` risk.
2. If RugCheck errors or returns junk, the fallback runs **all** of these and FAILS on any red flag:
   * On-chain mint (`getAccountInfo`): mint authority set, freeze authority set, plus Token-2022
     transfer fee / transfer hook / permanent delegate / non-transferable / default-frozen.
   * GoPlus: mintable, freezable, closable, non-transferable, balance-mutable, transfer fee/hook (and their "upgradable" flags).
   * Holders (`getTokenLargestAccounts` + `getTokenSupply`, owners via `getMultipleAccounts`):
     any wallet over 15%. Excluded: AMM pool accounts (from DexScreener and `--pool`), Raydium
     vault authorities, burn addresses.
   * DexScreener: top Solana pair liquidity under $50k, or no pair at all.
   * LP: for PumpSwap pools the LP mint is read on-chain and checked for burn. Any other DEX is `lp_lock_unknown` and FAILS.
3. Any source error (or even a bug) becomes `source_error:<name>` and a FAIL. Missing data never passes.

Every check is appended to `logs/safety_checks.jsonl`.

## Graduation listener

```bash
./run_listener.sh start     # background supervisor, restarts the listener if it crashes
./run_listener.sh status    # running? + heartbeat (warns if older than 150s)
./run_listener.sh logs      # tail the listener log
./run_listener.sh stop
```

Or as a systemd user service: see the comments in `graduation-listener.service`.

What it does per graduation:

| when | what | where |
|---|---|---|
| event | mint, pool, signature, raw event | `logs/graduations.jsonl`, `data/<mint>.jsonl` |
| every minute, minutes 1 to 30 | price, liquidity, mcap, cumulative + 5m volume, buys/sells | `data/<mint>.jsonl` (`type: snapshot`) |
| ~2 min and ~10 min | `check_token` result | `data/<mint>.jsonl` (`type: safety`) |
| breakout of the 5/10/15m range | every breakout, with `safety_pass` | `data/<mint>.jsonl` (`type: breakout`) |
| breakout AND latest safety PASS | would-buy line, `watch_only: true` | `logs/watch_signals.jsonl` |
| +15m / +1h / +4h after a would-buy | price at that time | `logs/signal_outcomes.jsonl` |

Other logs: `logs/listener.log` (rotating), `logs/listener_heartbeat.txt` (every minute),
`logs/supervisor.log`.

Notes on the data:
* DexScreener has no 1-minute candles, so the "close" is the price at each snapshot and the
  range high/low are the max/min of those closes. Per-minute volume is the change in the
  pair's 24h volume, which is cumulative for a pair that's under a day old.
* Snapshots for many mints are batched (30 mints per request), so 60 req/min covers a lot.
* After a crash the listener resumes any open 30-minute windows and pending follow-ups from the files.

## Daily summary

```bash
.venv/bin/python daily_summary.py                 # today, America/Toronto
.venv/bin/python daily_summary.py --date 2026-10-20
.venv/bin/python daily_summary.py --all --cost 0.03
```

Shows graduations seen, safety pass rate (with top fail reasons), breakouts fired and how many
safety blocked, and each would-buy at +15m/+1h/+4h net of 3% per fill on entry AND exit:
`net = exit*(1-0.03) / (entry*(1+0.03)) - 1`. A coin that goes nowhere shows about **-5.8%**.

## How to confirm it's watch-only

```bash
cd /workspace/trader/addons
# 1. no trading, key or bot-file references in the code
grep -rniE "wallet\.json|jup\.ag|jupiter|swap|sendTransaction|Keypair|private.?key|positions\.json|trading_meta|import (buy|sell)" *.py *.sh
# 2. the tests enforce it too (test_watch_only.py)
.venv/bin/python -m pytest tests/test_watch_only.py -q
# 3. the bot files are untouched
cd .. && git status --short buy.py sell.py sleeve_exit_loop.py positions.json trading_meta.json
```

The only hits should be `PumpSwap` (the DEX name, used to read the pool's LP mint for the
burn check) in `safety_fallback.py`. Anything else showing up is worth a look. In
`addons_common.py`, HTTP is GET-only to `api.rugcheck.xyz`, `api.gopluslabs.io` and
`api.dexscreener.com`, and RPC refuses everything except `getAccountInfo`,
`getMultipleAccounts`, `getTokenLargestAccounts` and `getTokenSupply`.
