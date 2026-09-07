# Forex Scanner DEMO Strategy Lab

## Purpose

The DEMO account is a controlled research environment for discovering which repeatable combinations of market state, session, execution quality and strategy logic produce positive expectancy after realistic broker friction.

SMC/ICT and wave-aware logic are research features and challenger strategy families. They are not universal admission requirements.

## Strategy families

The initial observation-only hypothesis set is:

1. `TREND_MOMENTUM` — higher-timeframe directional alignment with lower-timeframe continuation/displacement.
2. `SESSION_BREAKOUT` — directional expansion during liquid London/New York windows.
3. `PULLBACK_TREND` — controlled retracement inside an established trend followed by continuation evidence.
4. `MEAN_REVERSION` — exhaustion/reclaim logic restricted to range or weak-trend regimes.
5. `LIQUIDITY_SWEEP` — sweep/reclaim/MSS/BOS/displacement logic as an independent challenger.

Multiple hypotheses may be active on the same immutable signal snapshot. This is deliberate: later attribution must estimate which factors or interactions matter rather than forcing every trade into one discretionary label.

## Phase 1: observation only

`demo_strategy_lab.py` may score and label hypotheses, but it must not change:

- signal state,
- conviction score,
- score floor,
- entry/SL/TP geometry,
- risk sizing,
- correlation policy,
- position capacity,
- broker execution,
- reversal/stacking policy.

Every hypothesis payload carries `policy_effect=OBSERVATION_ONLY`.

## Durable experiment record

For every candidate that reaches durable signal telemetry, retain enough point-in-time evidence to study:

- strategy-family hypothesis scores and evidence,
- symbol/direction,
- D1/H4/H1/M15/M5 state where available,
- regime and session,
- trend/structure strength,
- BOS/MSS/displacement/FVG/sweep evidence,
- ATR and volatility regime,
- spread and spread/ATR when captured,
- entry mode, pullback depth, entry drift,
- planned RR and geometry,
- guard decisions and data quality,
- high-impact news/macro proximity when available,
- execution status and broker-native outcome,
- realized P&L,
- holding time,
- sampled MAE/MFE in account currency with explicit `SINCE_FIRST_OBSERVED` semantics until exact broker-risk normalization exists,
- exit efficiency and structural state at exit.

Rejected opportunities should also be sampled after the decision horizon where feasible. This allows analysis of whether a guard prevented a loser or discarded a winner.

## Research hierarchy

Internet/academic evidence is a prior, not production truth. The promotion path is:

`external evidence -> shadow hypothesis -> broker DEMO evidence -> cohort attribution -> walk-forward validation -> bounded DEMO calibration -> possible strategy promotion`.

Never promote a strategy based on in-sample win rate alone.

## Comparison dimensions

Attribution should compare at least:

- direction accuracy by +5m/+15m/+30m/+60m horizons where durable data exists,
- realized expectancy and P&L,
- win rate,
- MFE/MAE sequencing and magnitudes,
- holding time,
- exit efficiency,
- spread/volatility sensitivity,
- session/regime dependence,
- pair-specific dependence,
- entry drift and fast-lane capture quality,
- loss streaks and drawdown contribution.

## Safety contract

The Strategy Lab does not supersede the canonical DEMO risk/execution contract. Existing hard guards, server-side protection, idempotency/retry behavior, uncertain-outcome quarantine and broker reconciliation remain authoritative.
