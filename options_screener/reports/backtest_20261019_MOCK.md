# Backtest 2026-05-01 to 2026-10-16

**Research only. Not financial advice. Options can lose 100%. Simulated results, not real trading.**

- Run: 2026-10-19 06:45 EDT | data: MOCK synthetic data (not market data)
- Mode: **MOCK**
- In-sample before 2026-08-27, out-of-sample from it | config hash b3e88b7adcd8a7b2
- Costs: USD 0.0/contract (min 0.0/order) + 0.1/contract fees; buys at the ask, sells at the bid

## GATE: FAIL

- data mode is MOCK: only a backtest on real historical option data can unlock paper
- OOS expectancy -4.58 USD/trade is not > 0 after costs
- bootstrap p5 -0.0616 is not > 0
- 2x-cost expectancy -7.27 USD/trade is not > 0
- OOS trades 8 < 100

| metric | OOS (with C) | OOS (without C) | full (with C) | full (without C) | OOS 2x costs | OOS +1 min delay |
|---|---|---|---|---|---|---|
| entries_attempted | 8 | 17 | 26 | 56 | 8 | 8 |
| filled | 8 | 16 | 26 | 52 | 8 | 8 |
| fill_rate | 1.00 | 0.94 | 1.00 | 0.93 | 1.00 | 1.00 |
| hit_rate_target | 0.38 | 0.25 | 0.54 | 0.42 | 0.38 | 0.38 |
| win_rate | 0.38 | 0.25 | 0.54 | 0.42 | 0.38 | 0.50 |
| avg_win | 6.56 | 5.29 | 10.89 | 9.95 | 4.01 | 4.25 |
| avg_loss | -11.26 | -29.43 | -12.37 | -29.15 | -14.03 | -25.43 |
| expectancy_usd | -4.58 | -20.75 | 0.15 | -12.61 | -7.27 | -10.59 |
| expectancy_ret | -0.03 | -0.05 | -0.02 | -0.04 | -0.05 | -0.02 |
| profit_factor | 0.35 | 0.06 | 1.03 | 0.25 | 0.17 | 0.17 |
| max_drawdown_usd | 38.71 | 332.09 | 70.82 | 658.75 | 58.13 | 87.83 |
| total_pnl | -36.60 | -331.93 | 4.03 | -655.63 | -58.13 | -84.73 |
| avg_minutes_to_fill | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| avg_minutes_held | 1.62 | 2.56 | 1.31 | 1.92 | 1.62 | 1.88 |
| trades_per_day | 0.22 | 0.44 | 0.22 | 0.44 | 0.22 | 0.22 |

Bootstrap of OOS net returns per trade: p5 -0.0616, median -0.0283, P(mean>0) 0.08

## In-sample tuning grid (chosen = highest IS expectancy with >= 20 trades)

| move_signal_min | stop % | filled | expectancy $ | PF |
|---|---|---|---|---|
| 0.4 | 10.0 | 18 | 2.02 | 1.38 |
| 0.4 | 15.0 | 18 | 2.26 | 1.44 |
| 0.4 | 20.0 | 18 | 2.26 | 1.44 |
| 0.45 | 10.0 | 18 | 2.02 | 1.38 |
| 0.45 | 15.0 | 18 | 2.26 | 1.44 |
| 0.45 | 20.0 | 18 | 2.26 | 1.44 |
| 0.55 | 10.0 | 18 | 2.02 | 1.38 |
| 0.55 | 15.0 | 18 | 2.26 | 1.44 |
| 0.55 | 20.0 | 18 | 2.26 | 1.44 |

Chosen: {'move_signal_min': 0.45, 'stop_pct': 15.0}

## Parameter perturbation (OOS)

| variant | filled | expectancy $ |
|---|---|---|
| target x0.8 | 8 | -2.44 |
| target x1.2 | 8 | -3.89 |
| stop x0.8 | 8 | -6.25 |
| stop x1.2 | 8 | -4.58 |
| time stop 10:20 | 8 | -4.58 |
| time stop 10:40 | 8 | -4.58 |

Profitable share: 0%

## OOS split: signal bucket

| bucket | filled | hit rate | expectancy $ | PF |
|---|---|---|---|---|
| score>=0.75 | 8 | 0.38 | -4.58 | 0.35 |

## OOS split: DTE

| bucket | filled | hit rate | expectancy $ | PF |
|---|---|---|---|---|
| DTE 1-3 | 2 | 0.00 | -16.93 | 0.00 |
| DTE 4-7 | 4 | 0.25 | -4.81 | 0.14 |
| DTE 8-21 | 2 | 1.00 | 8.24 | inf |

## OOS split: call vs put

| bucket | filled | hit rate | expectancy $ | PF |
|---|---|---|---|---|
| CALL | 5 | 0.40 | -0.35 | 0.91 |
| PUT | 3 | 0.33 | -11.62 | 0.05 |

## OOS split: earnings

| bucket | filled | hit rate | expectancy $ | PF |
|---|---|---|---|---|
| earnings | 8 | 0.38 | -4.58 | 0.35 |

## OOS split: fill-quality score

| bucket | filled | hit rate | expectancy $ | PF |
|---|---|---|---|---|
| FQ 1.00 | 8 | 0.38 | -4.58 | 0.35 |

## Single-position C$100 model (one trade per day, sized at the ask, fees + FX in CAD)

> **MOCK data: NOT evidence of a real edge.** These numbers only show the plumbing works.

| metric | value |
|---|---|
| sessions | 117 |
| days with an affordable A+B+C signal | 10 |
| days skipped only because unaffordable at C$100 | 26 |
| filled trades | 8 |
| hit rate +5% before stop / time stop | 0.25 |
| hit rate +10% before stop / time stop | 0.25 |
| expectancy per trade (CAD) | -6.25 |
| total (CAD) | -49.96 |
| worst day (CAD) | -11.67 |
| best day (CAD) | -0.31 |
| max drawdown on C$100 (CAD) | 49.96 (50.0%) |

### Move-potential proxy: legacy vs new

| measure | value |
|---|---|
| candidates (passed A+B) | 93 |
| avg NEW proxy rate (+5% before -15% stop / 10:30, BS with decay) | 0.75 |
| avg LEGACY proxy rate (best price within 60 min, no stop) | 0.81 |
| realized +5% hit rate in the simulation | 0.25 |
