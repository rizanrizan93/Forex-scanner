# XAU Expansion V4 — Broker Cross-feed and Adaptive Edge Gate

Research only. Production/execution influence remains disabled.

## Independent cTrader DEMO cross-feed

The two parameter configurations selected by the public walk-forward study were replayed on broker-native cTrader DEMO XAUUSD H1 history, resampled independently to D1. The feed contains 21,765 H1 bars from 2023-01-02 23:00 UTC through 2026-08-31 23:00 UTC. Confirmation is 2024-01-01 through 2026-08-31. Three daily boundaries were tested: 00:00, 21:00 and 22:00 UTC. Results below use 0.10R stress cost.

### Current stricter configuration S2R2T2H0

This configuration uses strict expansion conditions, 1.25 ATR stop, 2.6R target, full EMA20/EMA50/EMA200 directional confirmation and a 7-bar maximum hold.

| D1 boundary | Trades | Win rate | Net R | Expectancy | Profit factor | Max DD proxy |
|---|---:|---:|---:|---:|---:|---:|
| 00:00 UTC | 13 | 53.85% | +10.1496R | +0.7807R | 2.7457 | 1.80% |
| 21:00 UTC | 15 | 60.00% | +12.1922R | +0.8128R | 3.1153 | 0.68% |
| 22:00 UTC | 14 | 57.14% | +10.7972R | +0.7712R | 2.8733 | 0.94% |

All three variants are positive, so the predefined broker cross-feed gate passes. Severe 0.15R cost also remains positive: 00:00 UTC +9.4996R / PF 2.5537; 21:00 UTC +11.4422R / PF 2.8870; 22:00 UTC +10.0972R / PF 2.6652.

### Earlier strict-signal configuration S2R0T0H0

The earlier fold-selected configuration also remains positive on all three broker boundaries at 0.10R cost: 00:00 +8.2R / PF 1.9318; 21:00 +13.8R / PF 3.0909; 22:00 +12.1R / PF 2.8333.

The V3-like center configuration S1R1T1H1 is likewise positive on all three boundaries. This indicates that the recent broker-native XAU expansion edge is a parameter neighborhood rather than a single-point artifact.

## Exploratory trailing edge gate

A separate exploratory overlay was tested after observing the weak 2021–2022 public fold. At each signal it looks only at the last eight shadow trades whose outcomes were already completed; trading is allowed only when their 0.10R-cost expectancy is positive and PF exceeds 1.0. Shadow outcomes continue to update even while execution would be suspended.

The gate completely avoided the weak 2021–2022 F3 period, but it also skipped profitable trades in F1 and F2. Aggregate 0.10R OOS changed as follows:

| Variant | Trades | Net R | Expectancy | Profit factor | Max DD proxy |
|---|---:|---:|---:|---:|---:|
| Ungated V4 | 51 | +8.5377R | +0.1674R | 1.2743 | 4.37% |
| 8-trade edge gate | 32 | +7.0377R | +0.2199R | 1.3700 | 3.60% |

At 0.15R severe cost the gated version remains +5.4377R, +0.1699R expectancy and PF 1.2723, versus ungated +5.9877R, +0.1174R and PF 1.1836.

The edge gate therefore improves risk-adjusted quality and avoids the historical failure regime, but reduces total net R and was designed after F3 was observed. It is not eligible for promotion without a new untouched forward/holdout period.

## Current V4 conclusion

The strongest supported component is `S2R2T2H0` XAUUSD D1 Expansion Breakout. It survived purged anchored public walk-forward and then reproduced strongly on independent broker-native XAUUSD across three daily boundaries and severe transaction-cost stress. The adaptive eight-trade no-trade gate is promising as a drawdown-control challenger, but should remain shadow-only because it is post-hoc and over-restrictive in earlier folds.

Current status: `V4_CROSSFEED_CONFIRMED_RESEARCH_CHALLENGER`. No LIVE or production execution authority is granted.
