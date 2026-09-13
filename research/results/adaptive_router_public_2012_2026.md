# Adaptive Regime Router — Public Historical Backtest Evidence

Research only. No production/execution influence.

## Data coverage

- D1: 11 instruments, 40,717 daily bars in total, public Yahoo Finance chart data, from January 2012 through 11–13 September 2026 depending on instrument.
- H4: 11 instruments, 158,400 H4 bars in total, public `komo135/forex-historical-data` GitHub dataset, mostly November 2012 through 4 March 2022.
- D1 instruments: AUDUSD, EURCHF, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, USDCAD, USDCHF, USDJPY and XAUUSD proxy.
- Important: the Yahoo fallback for XAUUSD is `GC=F` gold futures, not broker-native XAUUSD spot.
- The H4 public timestamps are not assumed to be UTC, so the H4 expansion rule is a volatility-breakout proxy, not an exact London/New York session test.

## Frozen methodology

- Frozen rule version: `ADAPTIVE_ROUTER_PUBLIC_PROXY_V1`.
- No parameter optimization or in-sample search was performed before the run.
- Signals use information available at the bar close and enter at the next bar open.
- If SL and TP are both touched in one bar, SL is assumed first.
- Base costs: D1 0.05R per trade; H4 0.08R per trade.
- Stress costs: D1 0.10R; H4 0.15R.
- Equity-return illustrations use 0.5% account risk per trade and are a trade-sequence proxy, not a broker-margin/portfolio-concurrency simulation.

## Whole router results

| Panel | Trades | Win rate | Net R | Expectancy | Profit factor | Return proxy at 0.5% risk | Max DD proxy |
|---|---:|---:|---:|---:|---:|---:|---:|
| D1 base | 824 | 32.89% | -128.26R | -0.1557R | 0.7756 | -48.24% | 49.59% |
| D1 stress cost | 824 | 32.89% | -169.46R | -0.2057R | 0.7172 | -57.88% | 58.14% |
| H4 base | 8,742 | 35.72% | -480.68R | -0.0550R | 0.9189 | -92.65% | 94.50% |
| H4 stress cost | 8,742 | 35.34% | -1,092.62R | -0.1250R | 0.8272 | -99.66% | 99.71% |

Conclusion: the frozen Adaptive Regime Router proxy is not profitable as a universal strategy and should not be promoted.

## D1 family attribution — base costs

| Family | Trades | Win rate | Net R | Expectancy | Profit factor |
|---|---:|---:|---:|---:|---:|
| Expansion breakout | 90 | 40.00% | +16.16R | +0.1796R | 1.2879 |
| Liquidity sweep | 593 | 30.52% | -127.62R | -0.2152R | 0.7026 |
| Mean reversion | 58 | 37.93% | -11.50R | -0.1983R | 0.6773 |
| Trend pullback | 83 | 38.55% | -5.30R | -0.0639R | 0.8955 |

At D1 stress cost, Expansion Breakout remains positive: 90 trades, +11.66R, +0.1296R expectancy, PF 1.1982. The other three families remain negative.

## D1 whole-router performance by era

| Era | Trades | Net R | Expectancy | Profit factor |
|---|---:|---:|---:|---:|
| 2012–2018 | 439 | -104.80R | -0.2387R | 0.6691 |
| 2019–2022 | 240 | -22.04R | -0.0918R | 0.8639 |
| 2023–2026 | 145 | -1.42R | -0.0098R | 0.9847 |

The router improved materially in the recent era but still did not produce positive expectancy after the base cost assumption.

## Expansion Breakout diagnostic

All 90 D1 Expansion Breakout trades came from the XAUUSD daily proxy (`GC=F`). There were zero FX-pair Expansion Breakout trades after the router's priority rules, so this result is not evidence of a broad FX edge.

Base-cost XAU expansion results: 90 trades, 40.00% win rate, +16.16R, +0.1796R expectancy, PF 1.2879, 2.72% drawdown proxy and +8.13% return proxy at 0.5% risk per trade.

Stress-cost XAU expansion results: 90 trades, 40.00% win rate, +11.66R, +0.1296R expectancy, PF 1.1982, 3.24% drawdown proxy and +5.73% return proxy at 0.5% risk per trade.

### XAU expansion by era

| Era | Base Net R | Base expectancy | Base PF | Stress Net R | Stress expectancy | Stress PF |
|---|---:|---:|---:|---:|---:|---:|
| 2012–2018 | -1.25R | -0.0320R | 0.9525 | -3.20R | -0.0820R | 0.8837 |
| 2019–2022 | +2.55R | +0.1020R | 1.1518 | +1.30R | +0.0520R | 1.0739 |
| 2023–2026 | +14.86R | +0.5716R | 2.1355 | +13.56R | +0.5216R | 1.9871 |

The apparent XAU expansion edge is therefore regime-dependent and concentrated in 2023–2026 rather than stable across the full 2012–2026 history.

### Recent XAU expansion years — base costs

- 2023: 5 trades, +1.15R.
- 2024: 7 trades, +6.01R, PF 3.3223.
- 2025: 8 trades, +7.60R, PF 3.4127.
- 2026 YTD: 6 trades, +0.10R; under stress cost it becomes -0.20R.

This is promising as a recent-regime challenger, but not sufficient evidence for unconditional production promotion.

## H4 cross-check

H4 Expansion Breakout was negative across the 2012–2022 public panel: 2,830 trades, -114.02R, -0.0403R expectancy and PF 0.9426 at base cost. H4 XAU across all routed families was also negative: 786 trades, -41.00R and PF 0.9238.

This cross-timeframe failure is another reason not to label the D1 XAU result a universal edge.

## Decision

1. Reject the current all-regime Adaptive Router as a universal strategy.
2. Reject the simple Liquidity Sweep proxy despite the tiny positive live-demo sample; the long public backtest is strongly negative.
3. Do not promote generic Trend Pullback or Mean Reversion in their current frozen forms.
4. Keep D1 XAU Volatility/Expansion Breakout as the primary challenger because it remained profitable under doubled cost stress, especially in 2023–2026.
5. Before any production promotion, retest XAU Expansion on broker-native XAUUSD / independent public spot data, use walk-forward/OOS splits, and validate that the 2024–2025 concentration is not a regime-specific accident.
