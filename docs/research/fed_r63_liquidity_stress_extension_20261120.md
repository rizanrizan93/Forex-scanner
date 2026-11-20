# R6.3 Research Extension — Liquidity Stress / Suspected Forced Selling (20 Nov 2026)

**Status: DRAFT RESEARCH, NOT VALIDATED ALPHA OR LIVE DEPLOYMENT.**
No changes to Frozen V1, cBots, cTrader execution, broker account, bridge, risk, or orders.

## Motivation
Nov 20 market reporting described a broad sell-off and *apparent*
forced liquidation. This is a plausible **hypothesis**, not proof that
particular XAU candles were caused by margin calls. A nominal yield
retreat is not sufficient to override H1/M15 price action, and
Treasury **daily** observations must not be mixed with fresh DXY ticks
as a timestamp-matched causal predictor.

## Observable state classifier
Using fully completed and contiguous M5 candles only, classify:
- `DOWNSIDE_DISPLACEMENT`: lower break of preceding 20-M5 range,
  >=2 bearish candles in 3, >=2.2x reference TR median decline in 3
  candles, and final candle range >=1.1x reference TR.
- `UPSIDE_DISPLACEMENT`: symmetric breakout to the upside.
- `SWEEP_LOW_RECLAIM`: low pierces the preceding 20-bar low by >0.1x
  median TR but closes back inside by >0.05x, with >=0.3x lower wick.
- `SWEEP_HIGH_REJECT`: mirror of the previous.
- `VOLATILITY_SPIKE`: last closed M5 range >=2.4x past TR median.
- `WIDE_SPREAD`: fresh bid/ask spread >0.2x reference M5 TR median.
- `NORMAL` or `UNKNOWN` for non-events/incomplete, stale or gapped data.

The 20-bar extremes and volatility references **exclude** the bar
being classified. Missing M5, future timestamps, non-contiguous
prices, or invalid OHLC fail closed to UNKNOWN. This can detect
**visible stress/sweeps**, NOT actual liquidation intent. A genuine
liquidation attribution needs reliable volume, COMEX open interest,
bid/ask liquidity, and position or margin-flow evidence.

## Decision policy
The original R6.3 macro/price conflict remains WAIT. If verified
R6.3 macro and M15/H1 align but closed M5 shows price stress, swing
reclaim or extreme spread, **veto** the directional WATCH to WAIT.
Keep watch-side as information to assess after new confirmation.
UNKNOWN also blocks that new agreement from being upgraded.
Even NORMAL only permits a descriptive WATCH, never an entry.
No restriction changes to executable cBots or Frozen V1.

## Tests and historical validity
New unit/regression cases cover both downside/upside displacement,
range sweeps, stale/future/gapped candles, risk veto, and non-
confirmation of the causal story. They are **synthetic**, not proof
that accuracy or profitability improved.

The previously audited R3/R4 69-FOMC-event 2019–2026 studies lack
paired, intraday point-in-time cash yields, DXY, XAU M1 and verified
margin/OI flows needed for A/B testing of this M5 guard. Do **not**
report a win rate for this overlay until a clean paired historical
replay quantifies per-side correct direction, coverage, false vetoes,
conditional expectancy, 1/3/6/24h adverse excursion, costs, and
holdout-year uncertainty.

### Required proper replay
1. Take **same timestamped R6.3 signals** before/after overlay.
2. Freeze thresholds before using 2025–2026 out-of-sample.
3. Audit fill/spread and closed bar timing: no ex-post FOMC labels.
4. Compare BUY/SELL separately, accuracy and coverage jointly,
   plus the number of prevented losses versus prevented winners.
5. Test COVID (Mar 2020), stress sessions, calm sessions and recent
   November 2026 without calibrating to the incident.
6. Only promote if after-cost out-of-sample evidence improves
   outcomes with adequate n and without selection/lookahead bias.

**Conclusion pending replay.** Current evidence supports only a
fail-closed operational *research* guard, not a claim of >80% accuracy.
