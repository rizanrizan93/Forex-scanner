# XAU D1 Rolling Stability V1 — Findings

Status: **FAIL — preregistered stability gate not met.**

Contract: `XAU_D1_ROLLING_STABILITY_V1`  
Execution influence: `false`

## Purpose

Test whether the already-frozen XAUUSD `D1_TSMOM_60_200` edge is stable across rolling market regimes, not merely profitable in aggregate. This gate was preregistered before the rolling-window results were observed.

Frozen construction:
- 17:00 America/New_York D1 boundary, DST-aware
- close versus EMA200
- 60-day return same sign
- next D1 open
- 2 ATR14 stop
- 4 ATR14 target
- 30 D1-bar maximum hold
- STOP_FIRST ambiguity policy
- no parameter search or tuning

## Preregistered acceptance gate

At base $0.17 XAU cost:
- >=70% positive eligible 3Y windows
- >=80% positive eligible 5Y windows
- latest trailing 3Y > 0
- latest trailing 5Y > 0
- worst eligible 5Y expectancy >= -0.05R/trade

At stress $0.35:
- >=60% positive eligible 3Y windows
- >=70% positive eligible 5Y windows
- latest trailing 3Y > 0
- latest trailing 5Y > 0
- worst eligible 5Y expectancy >= -0.075R/trade

Minimum trade counts were 30 for 3Y windows and 50 for 5Y windows. At least 90% of windows had to be eligible.

## Result

All windows were eligible, so the failure is not caused by insufficient sample size.

### Base cost $0.17

- positive 3Y windows: **58.33%** — FAIL vs 70%
- positive 5Y windows: **60.00%** — FAIL vs 80%
- latest trailing 3Y: **+0.64969R/trade**, PF 2.9438 — PASS
- latest trailing 5Y: **+0.36447R/trade**, PF 1.8159 — PASS
- worst 5Y expectancy: **-0.05173R/trade** — narrowly FAIL vs -0.05

### Stress cost $0.35

- positive 3Y windows: **50.00%** — FAIL vs 60%
- positive 5Y windows: **60.00%** — FAIL vs 70%
- latest trailing 3Y: **+0.64752R/trade** — PASS
- latest trailing 5Y: **+0.36175R/trade** — PASS
- worst 5Y expectancy: **-0.05785R/trade** — PASS vs -0.075

Overall: `overall_pass_for_continued_demo=false`.

## Regime weakness

Examples at base cost:

3Y:
- 2014–2016: -0.07880R/trade
- 2015–2017: -0.14889R/trade
- 2019–2021: -0.01207R/trade
- 2020–2022: -0.04849R/trade
- 2021–2023: -0.19332R/trade

5Y:
- 2013–2017: -0.04927R/trade
- 2014–2018: -0.05173R/trade
- 2017–2021: -0.01360R/trade
- 2019–2023: -0.01022R/trade

The current/trailing regime is strong, but the long-history edge is materially regime-dependent.

## Interpretation alongside other evidence

This failure does not erase the positive evidence already observed:
- full long history is positive in aggregate
- broker-boundary sensitivity retained the edge
- actual cTrader broker replay 2020–2026 was strongly positive and cost robust
- current trailing 3Y/5Y windows are strong

However, a preregistered stability gate cannot be ignored because recent performance is attractive. The strategy is best classified as a **strong current-regime candidate with insufficient all-regime stability**, not a robust all-regime execution strategy.

## Decision

1. **Demote XAUUSD Five-Core from DEMO execution-authorized to shadow-only.**
2. Keep the frozen `D1_TSMOM_60_200` evaluator running for research and forward evidence.
3. Do not change strategy parameters post-hoc.
4. Do not disable shorts post-hoc despite their weaker historical diagnostic.
5. Do not invent a retrospective regime filter. Any regime filter must be independently preregistered and tested.
6. Continue unseen forward DEMO evidence collection.
7. Re-promotion requires a separate formal gate; LIVE remains prohibited.

Workflow run: `34665621590`  
Artifact ID: `10289385945`  
Artifact SHA-256: `592aa5a0d07509c0f888064762bed05d0068df77acb0cdcd757461d911110135`
