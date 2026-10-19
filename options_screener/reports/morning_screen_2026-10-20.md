# Options morning screen for 2026-10-20 (as of close 2026-10-19)

**Research only. Not financial advice. Options can lose 100% of the premium paid. Nothing here places orders.**
> **MOCK DATA.** Generated from a deterministic synthetic market, not real quotes.

- Mode: RESEARCH (no orders) | Market data: MOCK | earnings: MOCK | news: none
- Budget: C$100 (~US$70.92 after FX) | ONE position | max loss = full premium + fees (up to C$100) | max premium/contract US$0.708
- FX: 1 CAD = 0.7200 USD (ASSUMPTION: config fallback) | FX cost buffer 1.5% per conversion (ASSUMPTION) | fee buffer US$0.10/contract/side (ASSUMPTION)
- Fill-quality gate: ENFORCED | Missing / degraded: news headlines (no provider configured)
- Run time: 2026-10-19 06:47 EDT (America/Toronto) | config hash b3e88b7adcd8a7b2

## Candidates (passed A + B + C): 0   (max 3 actionable, ranked)

NO TRADE — no verified opportunity meets the capital, liquidity, pricing, and defined-risk requirements.

## Research-only debit spread comparison (not executable at Wealthsimple)

Shown only to compare cost and max loss. Wealthsimple does not support multi-leg orders, so these are NOT actionable. `*` = uses a MODEL ESTIMATE price.

| ticker | type | long / short | debit | width | contracts | max loss CAD | max gain USD | breakeven |
|---|---|---|---|---|---|---|---|---|
| NVDA | put_debit_spread | NVDA 2026-10-23 99 PUT / NVDA 2026-10-23 98 PUT | 0.39 | 1 | 1 | 55.27 | 60.60 | 98.61 |
| SOFI | put_debit_spread | SOFI 2026-10-30 17 PUT / SOFI 2026-10-30 16 PUT | 0.41 | 1 | 1 | 58.09 | 58.60 | 16.59 |
| MSFT | put_debit_spread | MSFT 2026-10-23 310 PUT / MSFT 2026-10-23 305 PUT | 1.32 | 5 | 0 | n/a | n/a | 308.68 |

## Near-misses (failed ONLY fill quality or affordability): 3

| ticker | type | contract | score | failed | ask | 1 contract CAD | spread | 1st-hr vol | OI |
|---|---|---|---|---|---|---|---|---|---|
| NVDA | bear | NVDA 2026-10-23 99 PUT | 0.884 | unaffordable at C$100 (1 contract needs C$237.03) | 1.68 | 237.03 | 0.8% | 2463 | 15829 |
| SOFI | bear | SOFI 2026-10-30 17 PUT | 0.856 | C: median_seconds_between_prints | 0.69 | 97.43 | 1.6% | 793 | 5683 |
| MSFT | bear | MSFT 2026-10-23 310 PUT | 0.833 | unaffordable at C$100 (1 contract needs C$276.51) | 1.96 | 276.51 | 1.6% | 2148 | 3832 |

## Screen funnel

| reason | count |
|---|---|
| A: no catalyst | 12 |
| C: fill quality | 1 |
| no clear direction | 2 |
| no eligible contract | 1 |
| unaffordable at C$100 | 4 |
| passed everything | 0 |

## Post-market review template (thesis, entry, exit, result vs plan)

- Ticker / contract:
- Thesis (catalyst + direction) and was it right?:
- Entry: trigger time ET, limit price, filled price, revisions used (max 2), spread at entry:
- Exit: time ET, price, reason (target / stretch / stop / range reclaimed / spread / 10:30 time stop):
- Result: US$ and C$ after fees + FX, % of C$100:
- Result vs plan: followed every rule? what differed and why?:
- IV change entry -> exit, and did an earnings IV crush hit?:
- Lesson for tomorrow:
