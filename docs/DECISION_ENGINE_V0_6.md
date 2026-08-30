# Decision engine v0.6

## Purpose

v0.6 adds deterministic research logic between market/macro inputs and the
existing execution layer. It does not activate execution.

## Macro

Canonical currency factors and weights:

- interest rate: 25
- central-bank bias: 20
- inflation: 15
- growth: 10
- labour: 10
- yield momentum: 10
- risk/commodity: 5
- positioning: 5

Factor values are signed -100..100. Missing factors remain missing. Invalid
values fail closed. Numeric macro scores require configured minimum evidence
coverage.

## Currency strength and pair ranking

Normalized pair momentum contributes positively to the base currency and
negatively to the quote currency. Currency-strength coverage records how many
configured pair relationships contributed.

Pair ranking uses:

```text
PAIR_EDGE =
  0.55 * relative_macro
+ 0.30 * relative_technical
+ 0.15 * cross_asset
```

Cross-asset evidence may be missing, but it is not replaced by zero. Top-level
edge weights are re-normalized over observed components and evidence coverage is
recorded separately. Pair ranking fails closed below minimum coverage.

## Technical / SMC primitives

- true range / ATR
- validated local swing pivots
- BOS by close beyond established swing
- displacement:
  - body >= 1.5x prior median body
  - range >= 1.2x ATR
  - directional close location >= 0.80
  - optional tick-activity confirmation
- FVG:
  - bullish: current low > high two bars earlier
  - bearish: current high < low two bars earlier
  - minimum gap >= 0.10 ATR
- liquidity sweep:
  - level must be established before the reclaim window
  - penetration plus reclaim required
  - simultaneous valid two-sided reclaims are AMBIGUOUS and invalid
- MSS confirmation requires aligned sweep + displacement + BOS

These are deterministic proxies for testable SMC/ICT structure. They are not
claims of access to centralized FX order flow.

## Conviction and states

Execution-conviction weights remain those in `config/scoring.yaml`.

A numeric score is produced only when minimum component coverage is reached.
States map by configured thresholds. Any hard guard forces `NO_TRADE`.

Required guard inputs are also fail-closed: omitting a canonical guard produces
`GUARD_INPUT_MISSING:<guard>`.

Additional internal blockers:

- `PAIR_DIRECTION_NEUTRAL`
- `PAIR_COVERAGE_BLOCK`

## Config safety

v0.6 startup validation locks:

- canonical 15-pair universe and timeframes
- macro/scoring keys and positive weights summing to 100
- canonical hard-guard set
- RESEARCH_ONLY risk mode
- risk-per-trade <= 0.50%
- max daily loss <= 1.0%
- two concurrent trades
- three-loss stop
- same-currency exposure <= 1.5 units
- OOS WR >= 55%
- PF >= 1.30
- expectancy >= 0.15R
- aggregate OOS sample >= 250
- walk-forward, costs, spread/slippage stress, multi-regime and demo-forward
  validation all mandatory

## Not yet implemented / not yet validated

- actual Fed/ECB/BoE/BoJ/SNB/BoC/RBA/RBNZ provider ingestion
- economic-calendar NEWS_BLOCK provider
- live cross-asset/yield evidence
- COT ingestion
- provider freshness/quorum orchestration
- full D1/H4/H1/M15/M5 live strategy orchestration
- broker-feed calibration with FP Markets and HFM
- real OOS / walk-forward performance

Execution therefore remains DISABLED.
