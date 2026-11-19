# RIZAN Fed Macro R3 — 80% directional precision falsification

**Status:** RESEARCH-ONLY, branch `research/fed-macro-80pct-r3-20261120`,
draft PR #891, based on R2 draft #890; production and cBot LIVE
unchanged.

## Research question

Can confirmation by intraday US2Y, US10Y and DXY improve
**separately measured BUY and SELL direction accuracy to at least 80%**
for XAUUSD on D1, D3, D5 and D10, compared with a Fed surprise-only
and unconditional market baseline?

Important: 80% is a target, **not a promised empirical result**.
Raw 80% with n=5 is insufficient; models that pass by cherry-picking
events, years or sides cannot be deployed.

## Fixed source / feature contract

- Sources: sealed 69 real XAUUSD M1 event ledgers from 2019–2026 R1
  experiment, with official SF Fed USMPD historical market-response
  inputs and SHA256, no re-labeling of outcomes. Canonical R1 run:
  https://github.com/rizanrizan93/Forex-scanner/actions/runs/44621561755
- `MP2`: implied change in next-FOMC policy rate, source **percentage
  points**, converted to **basis points x100**.
- `UST2Y`: change in nominal cash 2-year yield in source percentage
  points -> bps.
- `UST10Y`: nominal cash 10-year yield change in source percentage
  points -> bps.
- `DXY`: source index **percent return**, left as percent (NOT bps).
- Official source methodology:
  https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/
- Features are **ex-post completed FOMC statement/press/full-window
  market changes**; these were computed and published by researchers
  retrospectively. They are NOT an archived real-time feed or features
  known before the policy announcement. NO historical PIT trading
  accuracy is established.

## Eight predeclared direction-symmetric filters (no tuning)

| Model | Entry search requires directional agreement |
|---|---|
| MP2_ONLY | MP2 magnitude >=2bp |
| MP2_AND_2Y | MP2 >=2bp, UST2Y >=1bp |
| MP2_AND_USD | MP2 >=2bp, DXY >=0.05% |
| MP2_2Y_USD | MP2 >=2bp, UST2Y >=1bp, DXY >=0.05% |
| MP2_2Y_10Y_USD | above + UST10Y >=1bp |
| YIELD_2Y_10Y_USD | UST2Y >=1bp, UST10Y >=1bp, DXY >=0.05% |
| YIELD_2Y_USD | UST2Y >=1bp, DXY >=0.05% |
| STRONG_MP2_2Y_USD | MP2 >=3bp, UST2Y >=2bp, DXY >=0.10% |

All-positive -> search SELL, all-negative -> search BUY; conflict,
missing data or moves below thresholds -> WAIT. Missing values never
filled. Raw rate actions HIKE/CUT, statement tone and numeric policy
*surprise* remain separate; a rate hike can be dovish relative to
expected policy and should not be mislabeled.

## Validation

- Years: 2019–22 exploratory; 2023–24 already research-touched;
  2025–26 also research-touched; aggregate all 2019–26 **descriptive**.
  None of these folds is a pristine untouched holdout.
- Horizons: D1/D3/D5/D10 are closes after respective *fully observed
  following weekday UTC trading sessions*. Missing or partial
  sessions: CENSORED, not wins/losses. XAU cost modeled fixed
  $0.50/oz, no verified commission/slippage/overnight carry.
- End exposures crossing another FOMC are excluded for a separate
  overlap-controlled analysis. Report selected_n, evaluated_n,
  censored_n, overlap exclusions, year counts, Wilson 95% CI,
  mean/median signed terminal returns separately for BUY and SELL.
- 8 models x 4 horizons x 2 sides = **64 overlapping comparisons**.
  Selecting only a highest observed rate is multiple testing, NOT
  validation. No best-model promotion without later frozen
  prospective replication, genuine at-time features and all costs.
- Diagnostic threshold: >=80% observed directional accuracy in
  **each side with >=30 independent events each**, Wilson lower
  >=70%, positive cost-adjusted expectancy. Existing production
  release gate also must pass; an eventual confidence claim of
  >=80% would need a much higher lower-bound confidence requirement.

## Non-negotiable production lock

No script can merge code, send cTrader orders, change bridge/CBots,
remove Frozen V1 or Manual R3, or alter account/risk. Any >=80%
subset based on ex-post USMPD or already-examined 2019–26 prices
is a discovery only, never a live trading instruction.

## Reproduce

- `scripts/replay_fed_macro_80pct_r3.py`
- `tests/test_fed_macro_80pct_r3.py`
- `.github/workflows/fed_macro_80pct_r3.yml`
- PR #891 is draft and targets R2 research branch #890 (not main).
