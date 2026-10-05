# XAUUSD V396 Research Champion

Status: **FROZEN_RESEARCH_CHAMPION**  
Execution authority: **NONE**  
Live execution: **DISABLED**  
Research branch: `research/v390-xau-slr-raw`  
Raw workflow run: `37385315922`  
Raw workflow commit: `2f43bfd0c8e9b2533acc8b2d1218a8d1e14f60a1`

## Purpose

V396 is frozen because it is the first candidate in the V390–V396 raw research sequence to pass every predefined acceptance gate on strict rolling out-of-sample XAUUSD history. No production or live execution permission is implied by this status.

## Data and validation contract

- Instrument: XAUUSD
- Raw source: HistData M1
- Research span: 2012–2026
- Signal/execution research timeframe: M15 resampled from M1
- Strict OOS acceptance window: 2015–2025
- 2026: provisional only; excluded from acceptance
- Walk-forward: prior 3 calendar years select configuration -> next calendar year OOS
- Same-bar ambiguity: STOP_FIRST
- Base round-trip price cost: 0.40
- Stress round-trip price cost: 0.80
- Execution authority: false

## V396 logic

V396 retains the V395 cost-aware Donchian breakout/retest framework and adds two fixed, causal signal-quality requirements:

1. The net movement over the efficiency lookback, calculated from bars **before** the breakout candle, must point in the breakout direction.
2. The breakout close must finish at least **0.10 ATR** outside the prior Donchian boundary.

Other retained mechanics include EMA200/slope direction filter, efficiency/volatility regime filter, future retest entry only, ATR structural risk, pre-trade stress-cost-to-risk gate, 1.5R target, and STOP_FIRST execution accounting.

## Strict OOS result: 2015–2025

| Metric | V396 result | Acceptance |
|---|---:|---:|
| Trades | 859 | >=150 |
| Profit factor | **1.5571** | >=1.50 |
| Expectancy | **+0.2712R** | >=+0.20R |
| Win rate | 54.48% | informational |
| Max drawdown | **11.9261R** | <=15R |
| Stress PF | **1.3323** | >=1.20 |
| Stress expectancy | +0.1762R | informational |
| Positive OOS folds | **11/11** | >=70% |
| Median fold PF | **1.9005** | >=1.30 |
| Source integrity | PASS | required |

Acceptance result: **PASS (all gates)**.

## OOS folds

| OOS year | Trades | PF | Expectancy | Stress PF |
|---|---:|---:|---:|---:|
| 2015 | 22 | 2.3465 | +0.4667R | 1.8790 |
| 2016 | 12 | 3.8441 | +0.7776R | 3.2917 |
| 2017 | 3 | 99.0000* | +1.0879R | 99.0000* |
| 2018 | 4 | 3.6511 | +0.7494R | 2.9781 |
| 2019 | 13 | 1.9005 | +0.3569R | 1.5605 |
| 2020 | 114 | 1.0887 | +0.0522R | 0.9267 |
| 2021 | 75 | 1.6447 | +0.3011R | 1.3993 |
| 2022 | 123 | 2.2884 | +0.4976R | 1.9087 |
| 2023 | 89 | 1.4223 | +0.2123R | 1.1850 |
| 2024 | 194 | 1.4009 | +0.2088R | 1.1914 |
| 2025 | 210 | 1.5050 | +0.2541R | 1.3491 |

`*` PF=99 is the research summarizer's finite sentinel when the fold has no gross losing R; these tiny folds must not be interpreted as infinite economic edge.

The weak regime remains 2020. V396 passes because the full walk-forward edge is not dependent on excluding 2020 and all 11 base folds remain positive.

## 2026 provisional

The configuration selected using **only 2023–2025** is:

`D20_ER32_E0.20_V1.00_C0.30`

Meaning:

- Donchian length: 20 M15 bars
- efficiency lookback: 32 M15 bars
- minimum efficiency ratio: 0.20
- minimum volatility ratio: 1.00
- maximum stress cost / risk: 0.30R
- prior signed momentum alignment: required
- minimum breakout distance: 0.10 ATR

Provisional 2026 result at the research snapshot:

- Trades: 110
- PF: **1.5675**
- Expectancy: **+0.2770R**
- Win rate: 52.73%
- Max DD: 9.0879R
- Stress PF: **1.4841**

This is supportive validation, not part of the strict acceptance sample.

## Robustness audit

Post-run robustness was performed on the exact 859 selected OOS trades.

### IID trade bootstrap, 10,000 samples

- PF 5th percentile: ~1.394
- PF median: ~1.555
- PF 95th percentile: ~1.742
- Expectancy 5th percentile: ~+0.203R
- Expectancy median: ~+0.270R
- Probability PF > 1: 100% in sampled replicates
- Probability PF >= 1.5: ~70.4%

### Calendar-year block bootstrap, 5,000 samples

This preserves regime clustering within each sampled OOS year.

- PF 5th percentile: ~1.385
- PF median: ~1.557
- PF 95th percentile: ~1.859
- Expectancy 5th percentile: ~+0.200R
- Probability PF > 1: 100% in sampled replicates
- Probability PF >= 1.5: ~68.1%

### One-parameter neighbor perturbation

For every OOS fold, the selected walk-forward configuration was changed by one adjacent grid dimension without using that OOS year to choose the replacement.

| Perturbation | Trades | PF | Expectancy | DD | Stress PF | Positive years |
|---|---:|---:|---:|---:|---:|---:|
| Channel 20<->40 | 844 | 1.5373 | +0.2631R | 14.15R | 1.3135 | 11/11 |
| ER lookback 16<->32 | 680 | 1.6108 | +0.2918R | 13.50R | 1.3823 | 10/11 |
| Min efficiency 0.20<->0.30 | 744 | 1.5029 | +0.2493R | 10.73R | 1.2849 | 11/11 |
| Min vol ratio 0.80<->1.00 | 931 | 1.4916 | +0.2454R | 11.93R | 1.2751 | 11/11 |
| Cost cap 0.25<->0.30 | 788 | 1.6365 | +0.3010R | 7.91R | 1.4085 | 10/11 |

The neighbor surface is broadly positive and stress PF remains above 1.27 across these perturbations. This supports a parameter plateau rather than a single isolated optimum.

## Freeze decision

V396 is frozen as the current XAUUSD **Research Champion**. Do not continue tuning it merely to increase historical PF. Further work should focus on independent validation and forward/shadow/demo observation under unchanged rules.

Promotion beyond research requires, at minimum:

1. forward/shadow validation with fixed V396 rules;
2. broker-specific spread/slippage reconciliation against FP Markets cTrader;
3. confirmation that signal timestamps, entry fill semantics, and server-side SL/TP behavior match the research assumptions;
4. DEMO-only controlled execution before any consideration of live/manual use.
