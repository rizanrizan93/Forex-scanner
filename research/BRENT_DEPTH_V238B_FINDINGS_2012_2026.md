# Brent Uni Depth V238B — Historical Transfer Benchmark 2012–2026

## Scope

V238B applies the existing XAU V225.2 causal Supply/Demand first-touch depth methodology to Brent using HistData BCOUSD without fitting Brent-specific entry thresholds.

- Historical pair: BCOUSD
- Current FP Markets broker reference after V238D: BRENT (SHADOW_REFERENCE only)
- History: 2012–2026
- Source: HistData M1, normalized to UTC
- Timeframes: H4 / H1 / M15
- Reaction ladder: 0.25 / 0.50 / 0.75 / 1.00 ATR
- First-touch only; causal availability and supersession
- Same-M1 ambiguity: conservative favorable reaction starts after the touch bar
- Policy: SHADOW_ONLY
- Execution influence: false
- Execution authority: false
- LIVE execution: false

## Overall Brent depth results

| TF | Touches | Reaction >=0.50 ATR | Wilson LB 95% | Median depth | P25 | P75 | IQR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 | 4,440 | 69.84% | 68.48% | 16.88% | 5.47% | 40.00% | 34.53 pp |
| H1 | 14,187 | 71.02% | 70.26% | 19.44% | 6.15% | 43.95% | 37.80 pp |
| M15 | 45,584 | 74.71% | 74.30% | 18.18% | 5.17% | 41.18% | 36.00 pp |

Total first-touch episodes: **64,211**.

## Reaction ladder and timing

| TF | >=0.25 ATR | >=0.50 ATR | >=0.75 ATR | >=1.00 ATR | Median time to 0.50 ATR |
| --- | ---: | ---: | ---: | ---: | ---: |
| H4 | 86.26% | 69.83% | 55.00% | 42.88% | 22 min |
| H1 | 84.17% | 71.01% | 59.09% | 49.02% | 11 min |
| M15 | 86.00% | 74.70% | 63.30% | 54.26% | 2 min |

Median candidate-to-first-touch time:
- H4: 247 minutes
- H1: 75 minutes
- M15: 19 minutes

Median MFE / MAE:
- H4: 0.848R / 0.385R
- H1: 0.973R / 0.639R
- M15: 1.137R / 0.720R

## Era stability

| Era | Episodes | H4 reaction | H1 reaction | M15 reaction |
| --- | ---: | ---: | ---: | ---: |
| 2012–2018 | 30,616 | 71.33% | 71.25% | 74.27% |
| 2019–2024 | 25,967 | 68.05% | 70.87% | 75.08% |
| 2025–2026 | 7,628 | 70.39% | 70.57% | 75.18% |

M15 is the most stable Brent layer across eras. H4 weakens in 2019–2024 but does not collapse.

## Brent vs EURUSD V235 vs XAU V225.2

| TF | Brent reaction | EURUSD reaction | XAU reaction | Brent median depth | EURUSD median | XAU median | Brent IQR | EURUSD IQR | XAU IQR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 | 69.84% | 71.95% | 71.37% | 16.88% | 17.07% | 20.03% | 34.53 pp | 33.55 pp | 37.72 pp |
| H1 | 71.02% | 72.25% | 70.96% | 19.44% | 19.51% | 20.88% | 37.80 pp | 36.55 pp | 37.75 pp |
| M15 | 74.71% | 75.15% | 74.29% | 18.18% | 19.51% | 20.37% | 36.00 pp | 36.46 pp | 36.97 pp |

Key comparisons:
- H4 Brent reaction is 2.11 pp below EURUSD and 1.53 pp below XAU.
- H1 Brent is essentially equal to XAU (+0.06 pp) but 1.23 pp below EURUSD.
- M15 Brent is 0.42 pp above XAU and only 0.44 pp below EURUSD.
- Brent median depth is shallower than XAU on all three timeframes.
- Brent M15 IQR is narrower than both EURUSD and XAU.

## Interpretation

V238B supports Brent as a legitimate transfer target for the Uni Depth framework, especially on M15. It does not show a universal advantage over EURUSD: EURUSD remains stronger on raw reaction probability, particularly H4/H1.

The important open question is execution. EURUSD V235 also looked strong at the reaction layer, but V236 V229-style execution was negative after structural SL/TP and costs. Therefore Brent should not receive execution authority from V238B alone.

## Next gate: V239

V239 reconstructs the V229 2+2 child execution architecture on BCOUSD using:

- frozen XAU V225.2 ladder to avoid full-sample Brent entry leakage
- L1/L2 pre-touch limits
- L3 reclaim + MSS retest
- L4 displacement + refined-pocket retest
- H4 structural stop
- structural opposing-zone targets
- conservative STOP_FIRST ordering
- Brent contract size: 1 lot = 1,000 barrels; 0.01 lot = 10 barrels
- base spread: 0.04 USD (4 pips)
- zero commodity commission
- base slippage assumption: 0.01 USD (1 pip)
- stress spread/slippage
- $100 initial balance, 1:100 leverage, margin-only and 50% margin-cap ledgers

V239 remains SHADOW_ONLY regardless of result.
