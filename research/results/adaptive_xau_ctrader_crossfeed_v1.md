# Adaptive XAU Expansion — cTrader DEMO Cross-feed Evidence

Research only. Production/execution influence remains disabled.

## Purpose

Validate the XAUUSD D1 Expansion Breakout family that survived the public 2012–2026 Market-Adaptive Router V3 on an independent broker-native feed rather than the Yahoo `GC=F` proxy.

## Feed and construction

- Source: cTrader DEMO broker H1 history.
- Instrument: XAUUSD.
- H1 rows: 21,765.
- H1 coverage: 2023-01-02 23:00 UTC through 2026-08-31 23:00 UTC.
- H1 bars were resampled locally to D1 using three boundary sensitivities: 00:00, 21:00 and 22:00 UTC.
- Confirmation window: 2024-01-01 through 2026-08-31.
- Stress transaction cost in this cross-feed: 0.10R per trade.
- Same-bar ambiguity remains conservative: stop is evaluated before target.
- Candidate was selected before this cross-feed from the separate public-history adaptive study.

## Confirmation results under stress cost

| Daily boundary | Trades | Win rate | Net R | Expectancy | Profit factor | Return proxy at 0.5% risk | Max DD proxy |
|---|---:|---:|---:|---:|---:|---:|---:|
| 00:00 UTC | 19 | 57.89% | +14.30R | +0.7526R | 2.6250 | +7.33% | 1.10% |
| 21:00 UTC | 20 | 65.00% | +19.60R | +0.9800R | 3.5455 | +10.21% | 1.10% |
| 22:00 UTC | 20 | 65.00% | +19.60R | +0.9800R | 3.5455 | +10.21% | 1.10% |

All three daily-boundary variants were positive. The predefined cross-feed gate passed.

## Full broker-feed period

At the primary 00:00 UTC boundary, the full available broker-feed period produced 20 trades, 55.0% win rate, +13.20R after 0.10R stress cost, +0.66R expectancy and PF 2.3333. At 21:00/22:00 UTC the full period produced 21 trades, 66.67% win rate, +21.70R after stress cost, +1.0333R expectancy and PF 3.8182.

## Interpretation

This materially strengthens the XAU Expansion hypothesis because the positive result is reproduced on broker-native XAUUSD rather than only on the `GC=F` public proxy, and it survives both a doubled public-study cost assumption and daily-boundary sensitivity.

It does **not** make the overall Market-Adaptive Router production-ready. The V3 adaptive thresholds were designed after inspecting earlier research, and the broker confirmation sample is only 19–20 trades in the 2024–2026 confirmation window. The appropriate status is therefore `CROSS_FEED_CONFIRMED_CHALLENGER`, not production promotion.

Next gates should be purged/anchored walk-forward evaluation, parameter-neighborhood robustness rather than a single threshold set, H4/H1 timing refinement, and forward DEMO shadow accumulation. LIVE trading remains out of scope.