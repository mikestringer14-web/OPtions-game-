# data/ (gitignored except this file)

Drop CSVs here for backtests. All times are US/Eastern unless an offset is given.

| File | Columns |
|---|---|
| `underlying/<SYM>_1d.csv` | `date,open,high,low,close,volume` |
| `underlying/<SYM>_1m.csv` | `ts,open,high,low,close,volume` (ISO time, e.g. `2026-10-16T09:31:00-04:00`) |
| `options/<OCC>.csv` | `ts,open,high,low,close,volume[,trades,bid,ask,bid_size,ask_size]` |
| `earnings.csv` | `symbol,date` |

`<OCC>` is `SYMBOL + YYMMDD + C/P + strike*1000 (8 digits)`, e.g. `SPY261023C00580000`.
Option files with `bid,ask` columns are treated as quote data (VERIFIED); without them, PROXY.
`cache/` holds provider caches (past sessions only).
