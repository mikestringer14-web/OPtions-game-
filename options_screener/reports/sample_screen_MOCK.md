# Options morning screen for 2026-10-20 (as of close 2026-10-19)

**Research only. Not financial advice. Options can lose 100% of the premium paid. Nothing here places orders.**

> **MOCK DATA.** Generated from a deterministic synthetic market, not real quotes. It shows the report format only.

- Run time: 2026-10-19 04:29 EDT (America/Toronto)
- Mode: RESEARCH (no orders)
- Market data: MOCK synthetic data (not market data) | earnings: MOCK | news: none
- Fill-quality gate: ENFORCED  |  config hash fec2f3f387b77120
- Missing / degraded: news headlines (no provider configured)

## Candidates (passed A catalyst + B move potential + C fill quality): 1

| # | ticker | type | strike | expiry | DTE | delta | mid | spread | 1st-hr vol | OI | fill quality | IV rank | catalyst | score | entry trigger | target | stop | time stop |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | NVDA | PUT | 100 | 2026-10-23 | 3 | -0.46 | 2.13 | 0.8% | 2511 | 16966 | 1.00 VERIFIED | 0.90 | earnings 2026-10-19 (after close if reported then; time not in source) | 0.884 | after 9:35 ET, underlying breaks the 5-min opening-range LOW | +5.0% (mid 2.24); stretch +10.0% (2.34); exit with a limit at/near the bid | -15.0% (mid 1.81) | 10:30 ET, never hold past it |

### 1. NVDA BEAR: NVDA 2026-10-23 100 PUT
Score breakdown: catalyst 1.00, unusual_volume 0.90, iv 0.29, momentum 0.87, move_potential 1.00 -> combined 0.884; move-potential rate 0.75 (underlying PROXY)
Why: catalyst = earnings 2026-10-19 (after close if reported then; time not in source); direction = bear; IV rank 0.90
Plan: entry trigger: after 9:35 ET, underlying breaks the 5-min opening-range LOW; entry order: BUY limit at mid (est 2.13); cancel after 60s; never market, never chase; entry requires: live spread <= 5.0% of mid; entry deadline: 10:15; target: +5.0% (mid 2.24); stretch +10.0% (2.34); exit with a limit at/near the bid; stop: -15.0% (mid 1.81); invalidation: underlying back inside the opening range (low reclaimed), or spread > 2.0x historical median (1.6%); time stop: 10:30 ET, never hold past it; est cost per contract: 215.05; est round trip commission: 2.1
Note: IV-crush risk: earnings in the window; IV usually falls after the report
```
FillQuality (VERIFIED, source: MOCK)
  median spread 0.80% | first-hour volume 2511 | OI 16966 | prints/min 5.0 | est. round-trip cost 1.79%
  - morning_spread_pct: PASS (value 0.8, rule <= 5.0) [quotes]
  - close_spread_pct: PASS (value 0.8, rule <= 8.0) [quotes]
  - first_hour_volume: PASS (value 2511, rule >= 500)
  - day_volume: PASS (value 10164, rule >= 2000)
  - active_first_hour_minutes: PASS (value 55, rule >= 50 of 55)
  - open_interest: PASS (value 16966, rule >= 1000)
  - oi_drop_pct: PASS (value -4.535, rule <= 30.0)
  - median_seconds_between_prints: PASS (value 12.0, rule <= 15.0) [from per-minute print counts]
  - displayed_depth: PASS (value 189, rule >= 10)
  - round_trip_cost_pct: PASS (value 1.786, rule <= 2.00 (40% of +5.0%))
```

## Near-misses (failed ONLY the fill-quality gate): 2

| ticker | type | contract | score | failing check(s) | spread | 1st-hr vol | OI |
|---|---|---|---|---|---|---|---|
| MSFT | bear | MSFT 2026-10-23 310 PUT | 0.833 | round_trip_cost_pct | 1.6% | 2148 | 3832 |
| XOM | bull | XOM 2026-11-06 135 CALL | 0.801 | morning_spread_pct, close_spread_pct, first_hour_volume, day_volume, active_first_hour_minutes, open_interest, median_seconds_between_prints, displayed_depth, round_trip_cost_pct | 12.0% | 71 | 258 |

## Screen funnel

| reason | count |
|---|---|
| A: no catalyst | 6 |
| no clear direction | 2 |
| no eligible contract | 1 |
