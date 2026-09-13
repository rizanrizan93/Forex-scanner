# Four-Pair Public-History Strategy Search — 2026-09-13

Research only. `execution_influence=false`. Nothing in this branch grants DEMO or LIVE order authority.

## Data and test contract

Public price source: Dukascopy Bank BID H1 fetched with `dukascopy-python==4.0.1`.

Coverage: 2012-01-01 through 2026-09-01 (exclusive end); approximately 97k H1 bars per instrument for EURUSD, GBPUSD, USDJPY and AUDUSD.

Robustness conventions:

- conservative same-bar handling: `STOP_FIRST`;
- transaction-cost proxy: 1.2 pip base, 2.0 pip stress, 3.0 pip severe;
- four era buckets: 2012-2015, 2016-2019, 2020-2023, 2024-Aug 2026;
- moving-block bootstrap on trade outcomes (block 5, 600 replications);
- V1/V2 candidate sets are deliberately small family searches, not exhaustive parameter optimization;
- V3 is a causal adaptive experiment using only source trades that had fully exited before the new signal.

The public feed is BID OHLC, therefore the pip cost is a conservative friction proxy rather than exact FP Markets/cTrader execution. Any eventual DEMO candidate still needs broker-feed replay/cross-feed confirmation.

## Best result per pair

| Pair | Best current public-history candidate | 2-pip stress trades | Exp R/trade | PF | Net R | Max DD R | Era result | Bootstrap 95% lower | Interpretation |
|---|---|---:|---:|---:|---:|---:|---|---:|---|
| USDJPY | `D1_DONCHIAN55_200` | 103 | +0.242858 | 1.478663 | +25.014339 | 12.109552 | 4/4 positive | -0.022384 | Strongest lead, WATCH rather than clean pass because block-bootstrap lower CI is slightly below zero. |
| GBPUSD | `H4_MEAN_REVERT_Z2_TO_SMA20` | 89 | +0.188315 | 1.391260 | +16.760037 | 6.231488 | 4/4 positive | -0.054428 | Promising mean-reversion lead; stable across eras but CI still crosses zero. |
| EURUSD | `H4_MEAN_REVERT_Z175_TO_SMA20` | 53 | +0.039988 | 1.074684 | +2.119383 | 7.977591 | 3/4 positive | -0.210501 | Rejected: weak aggregate edge and 2024-2026 turns negative. |
| AUDUSD | `CAUSAL_ADAPTIVE_ROUTER_V3` | 261 | +0.029655 | 1.051487 | +7.740036 | 18.718570 | 2/4 positive | -0.108651 | WATCH only; adaptive rule improves full-history sign, but edge is thin and still regime-dependent. |

## USDJPY detail

The V1 `D1_DONCHIAN55_200` rule is the best USDJPY result found in this search. It uses D1 close above/below the prior 55-day channel together with EMA200 directional alignment; next-bar entry; 2 ATR stop; 4 ATR target; maximum 30 D1 bars; no overlap.

At 2-pip stress it produced 103 trades, +0.242858R/trade, PF 1.478663, +25.014339R and 12.109552R maximum drawdown. Every multi-year era is positive. The 2024-Aug2026 era remains +0.211882R/trade with PF 1.399298. At 3-pip severe friction the full result remains approximately +0.235718R/trade and PF 1.460899.

The moving-block bootstrap lower 95% bound is -0.022384R, so this is not classified as a clean statistical pass. It is nevertheless materially stronger than the old H4 compression lead.

The generic causal adaptive V3 for USDJPY is positive and 4/4 eras positive, but weaker: 214 trades, +0.051048R/trade, PF 1.089753, +10.924196R, severe-cost expectancy +0.037691R. It does not improve on the static D1 Donchian lead.

## GBPUSD detail

V1 trend, momentum and session-breakout families did not survive the full history robustly. V2 changed the exit family rather than tuning V1 parameters and found `H4_MEAN_REVERT_Z2_TO_SMA20`.

Rule: on H4, require 20-bar z-score <= -2 with RSI14 <=30 and ADX14 <20 for LONG, or z-score >= +2 with RSI14 >=70 and ADX14 <20 for SHORT. Enter next H4 open. Initial stop is 1.5 ATR. Target is the signal-time SMA20. Maximum hold is 12 H4 bars; same-bar ambiguity is STOP_FIRST.

At 2-pip stress: 89 trades, +0.188315R/trade, PF 1.391260, +16.760037R, max DD 6.231488R. All four era buckets are positive; 2024-Aug2026 is +0.157124R/trade, PF 1.281395 over 18 trades. At 3-pip severe friction it remains +0.168590R/trade, PF 1.342641, +15.004539R.

The block-bootstrap lower bound is still -0.054428R, so status remains WATCH. The generic adaptive V3 is worse and rejected: 740 trades, -0.069377R/trade, PF 0.894986. The static H4 mean-reversion candidate is the better lead.

## EURUSD detail

No tested family produces a robust full-history edge. The least-bad candidate is `H4_MEAN_REVERT_Z175_TO_SMA20`: 53 trades, +0.039988R/trade, PF 1.074684 and +2.119383R at 2-pip stress, but its 2024-Aug2026 era is -0.026551R/trade with PF 0.943390. Its bootstrap interval is wide and crosses zero substantially.

The causal adaptive V3 also fails: 121 trades, -0.089287R/trade, PF 0.835775, -10.803668R, only one of four eras positive, and 2024-Aug2026 expectancy -0.394866R with PF 0.393357.

Conclusion: EURUSD should remain NO_TRADE in the current Five-Core design until a different independent alpha family is identified and validated.

## AUDUSD detail

No static V1/V2 candidate passes across the entire 2012-2026 history. A notable regime signal appears in V2 `H4_MEAN_REVERT_Z2_TO_SMA20`: full-history 2-pip stress is slightly negative (-0.005773R/trade, PF 0.988856, 111 trades), but 2024-Aug2026 alone is +0.451961R/trade, PF 2.583184 over 24 trades with a positive recent-era bootstrap lower bound (+0.118721R).

That motivated the frozen generic V3 causal adaptive router. It only enables a source family when the previous 12 completed shadow trades have positive stress expectancy and PF>1, and the prior 24-trade expectation is also positive. It never reads future outcomes.

AUDUSD V3 improves the full-history result to 261 trades, +0.029655R/trade, PF 1.051487 and +7.740036R, with 2024-Aug2026 +0.122737R/trade and PF 1.267221. However only two of four eras are positive, 3-pip severe expectancy falls to +0.009297R, and the full-history bootstrap lower bound is -0.108651R. Therefore it is a research WATCH, not a promotion candidate.

## Research decision

Current priority order for broker-specific confirmation is:

1. USDJPY `D1_DONCHIAN55_200`.
2. GBPUSD `H4_MEAN_REVERT_Z2_TO_SMA20`.
3. AUDUSD adaptive/regime mean-reversion remains shadow research only.
4. EURUSD remains NO_TRADE and requires a genuinely new alpha family rather than more tuning of the rejected families.

V1 workflow run: `34759772825`.
V2 workflow run: `34759952708`.
V3 workflow run: `34760054278` (all four matrix jobs successful).
