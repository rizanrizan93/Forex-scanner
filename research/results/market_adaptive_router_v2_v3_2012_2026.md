# Market-Adaptive Router V2/V3 — Public Historical Evidence

Research only. No production or execution influence.

## Data

- 11 D1 instruments: AUDUSD, EURCHF, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, USDCAD, USDCHF, USDJPY, and XAUUSD proxy.
- 40,717 daily bars in aggregate, January 2012 through September 2026 depending on instrument.
- Public Yahoo Finance chart data; XAUUSD fallback is `GC=F` gold futures proxy rather than broker-native spot XAUUSD.
- Base transaction-cost assumption: 0.05R per completed candidate trade.
- 607 non-overlapping shadow candidates were generated across the four market states: EXPANSION, TREND, RANGE, TRANSITION.

## V2 online adaptive selector

V2 used only candidate outcomes that had already completed before the current signal. It combined a 3-year setup+regime window, a 1-year recent window, optional symbol history, and an uncertainty penalty. It could select at most two new positions on a signal date.

| Metric | V2 |
|---|---:|
| Selected trades | 72 |
| Win rate | 31.94% |
| Net R | -8.5913R |
| Expectancy | -0.1193R |
| Profit factor | 0.8312 |
| Return proxy at 0.5% risk | -4.37% |
| Max DD proxy | 9.94% |

By era:

| Era | Trades | Net R | Expectancy | PF |
|---|---:|---:|---:|---:|
| 2012–2018 | 0 | — | — | — |
| 2019–2022 | 47 | -17.7028R | -0.3767R | 0.5183 |
| 2023–2026 | 25 | +9.1115R | +0.3645R | 1.6444 |

Family attribution:

- Expansion Breakout: 32 trades, +5.3615R, +0.1675R expectancy, PF 1.2623.
- Liquidity Sweep: 30 trades, -7.2566R, -0.2419R expectancy, PF 0.6709.
- Mean Reversion: 10 trades, -6.6962R, -0.6696R expectancy, PF 0.2028.

V2 therefore adapted materially better in 2023–2026 but still admitted too many historically weak family/regime combinations.

## V3 hierarchical market-adaptive selector

V3 added generic hierarchical gates rather than hard-coding a preferred instrument: five-year family edge, five-year regime edge, one-year recent veto, symbol-specific veto when enough observations exist, and a confidence penalty. Only shadow trades whose exits preceded the current signal were visible to the selector.

Selection reasons across 607 shadow candidates: 148 cold-start rejects, 428 family vetoes, 4 regime vetoes, 4 symbol vetoes, and 23 selected trades.

| Metric | V3 |
|---|---:|
| Selected trades | 23 |
| Win rate | 43.48% |
| Net R | +8.4115R |
| Expectancy | +0.3657R |
| Profit factor | 1.6427 |
| Return proxy at 0.5% risk | +4.22% |
| Max DD proxy | 1.57% |

By era:

| Era | Trades | Net R | Expectancy | PF |
|---|---:|---:|---:|---:|
| 2012–2018 | 0 | — | — | — |
| 2019–2022 | 1 | -1.05R | -1.05R | 0.0 |
| 2023–2026 | 22 | +9.4615R | +0.4301R | 1.7859 |

All 23 selected V3 trades were XAUUSD-proxy Expansion Breakout trades. This was not hard-coded as an XAU-only rule: the hierarchical gates eliminated the other family/regime/instrument combinations because their trailing evidence failed the adaptive thresholds.

For 2023–2026 specifically, V3 selected 22 trades with 45.45% win rate, +9.4615R, +0.4301R expectancy, PF 1.7859, +4.77% return proxy at 0.5% account risk per trade, and 1.05% max drawdown proxy.

## Interpretation

The adaptive concept works substantially better than the universal router because it can stay inactive when evidence is weak and only activate a family/regime combination after sufficient positive trailing evidence. However, V3 is exploratory: its hierarchical thresholds were designed after observing V1/V2, so the 2012–2026 result is not a pristine untouched holdout.

The strongest hypothesis is now: a market-adaptive router should include a no-trade state and should promote only family/regime combinations with persistent multi-horizon evidence. In this public D1 sample, the only combination that survives is XAU volatility/expansion breakout, concentrated mainly from 2023 onward.

Before any production use, the next required tests are independent broker-native XAUUSD spot data, purged walk-forward / anchored OOS evaluation, spread/slippage stress, H4/H1 timing refinement, and forward-demo shadow validation. Production influence remains disabled.