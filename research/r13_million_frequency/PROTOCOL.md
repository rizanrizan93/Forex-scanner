# R13 million-configuration frequency research

Registered 24 November 2026 WIB before R13 price outcomes. Parent R12 evidence commit f00b7ccf77b0de35ae510f3322ec598499bd22ac. RESEARCH ONLY. Frozen V1, main, broker and bridge remain untouched.

## Scope and honest counts

The user requests hundreds of models and millions of configurations. Define **256 structural templates = 16 related families x 4 timeframes x 4 lookbacks**. They are not 256 independent ideas. BUY/SELL doubles this to 512 signal streams. Full Cartesian grid: 512 x 4 holding horizons x 4 stops x 4 targets x 3 H4 regimes x 4 sessions x 2 spread gates x 3 volatility gates = **2,359,296 parameter tuples**. Repeated signals, empty configurations and execution aliases are expected; record exact signal-stream hashes and all zero/failing scores. Do not claim millions of distinct profitable strategies.

Families: the 12 disclosed S5 families (breakout, retest break, sweep reclaim, sweep MSS, EMA20 reclaim, inside break, FVG retest, EMA50 dip, squeeze expansion, failed break, double sweep, TWAP reclaim) plus Donchian midpoint reclaim, RSI extreme reclaim, completed Asian range breakout and prior-day sweep. Reuse is explicit; several underlying concepts already failed S5-S12. This is a new expanded timeframe/regime/exit search, not an independent confirmation or an unchanged rerun of the old grid. It does not silently replace the registered R11B experiment or R12's delayed pullback policy.

TF minutes [5,15,30,60]; lookbacks [8,16,32,64]; sides [BUY,SELL]; holds [30,60,120,240] minutes; minimum stop [1,1.5,2,3] ATR (also beyond signal-bar extreme by .10ATR); targets [.75,1,1.5,2.5] initial R; H4 [ANY,WITH,AGAINST]; UTC sessions [ALL,ASIA01-06,LONDON06-10,US12-16]; observed repriced spread <=[.15,.35] ATR; volatility [ALL,LOW,HIGH] relative to median of prior 96 decision ATR values (minimum48). The entire grid is fixed now; no tuning after results.

All signals use completed decision bars, prior-only rolling extremes, completed H4 EMA20/80, and next M1 OPEN. Completed Asian range uses 01-06UTC only after 06UTC; prior-day range requires >=600 prior-day M1 observations. Entry UTC hour<16, weekdays only, max240min normal holding avoids scheduled21/22UTC rollover. Incomplete bars cannot trigger; future gaps never erase entries. No additional outcome-based loss pause. One active fixed1oz position per policy; next entry only >=5min after prior settlement, processed chronologically. Never count overlapping independent raw signals as filled trades.

## Data and execution

Pinned third-party Dukascopy-derived XAU bid/ask M1 and unchanged quote validation inherited from R11/R12. These are not FP Markets ticks or original Frozen data. Capture actual dates, monthly source SHA256, quote censoring and signal hashes on every annual job. No invented data or fallback price feed.

Screen uses doubled costs: widened bid/ask as R11B, commission .12USD/oz roundtrip and adverse slippage .10USD/oz each side. Initial risk based on actual cost-adjusted entry. Stops use adverse OPEN if gapped beyond stop; target fills capped at target. A true missing minute liquidates at next quote, retains loss and charges inherited3USD/oz/day/cost-unit rollover reserve. These are hypothetical costs, not broker certification.

Screen resolves an intraminute stop+target collision STOP first. Record this as one pessimistic OHLC scenario, not four paths. Compiled Numba replay must agree with an independent scalar reference in fixtures. Detailed finalists must be rerun separately at costs1/2 with A=O-L-H-C and B=O-H-L-C; spread admission, entries, exits, overlap and ledgers all reprice in each scenario. No PnL inversion, constant haircut or proxy compounding.

## Sequential stages, fixed before outcomes

1. Real-data development pilot, first60,000 valid2012 minutes. All2,359,296 tuples are actually scored for mechanics and compute budget. Pilot performance is not a selection gate. Pilot is a repeated subset, not additional independent evidence.
2. All tuples, independent annual2012-2018 screens. Retain full float64 score arrays (n,wins,netR,gainR,lossR,netUSD-flat1oz,sumR2), including failures, with exact deterministic grid order. Gates: N>=200, expectancy>.02R, PF_R>1.10, >=5 profitable years. Rank passing tuples by aggregate netR, ties by N, keep maximum64 for detailed replay. Empty results terminate selection honestly. The pipeline may stop after development; never imply millions were replayed in later periods if they were not.
3. Selected fixed64-or-fewer candidates only: detailed annual2019-2022 validation; both A2/B2 require N>=100, mean>.01R, PF_R>1.05, >=3 positive years. Evaluation2023-2025: N>=60, mean>0, >=2 positive years on both stress paths. 2026 Jan-Aug partial is separate, never used to select. All finalist outcomes remain disclosed including failures.
4. Passing candidates are INCONCLUSIVE, not ACCEPT. They require new forward shadow, family-wise evidence and exact native shared-wallet replay before production. No selection by evaluation profit or partial2026. All historical data is reused; no pristine OOS claim. Full trial count is 2,359,296 correlated tuples plus prior searches, never unadjusted significance.

No balance, floating equity DD, V1 incremental basket, margin/capacity or lot-feasibility claim arises from this fixed-ounce screen. Those fields stay null. The restored exact native CSV hashes from R12 do not substitute for unresolved signal tapes, macro vintage, reference control ledger or broker specifications.

## Compute and persistence

GitHub push-triggered research branch, read-only workflow permissions, max4 annual jobs concurrently,35min per annual job. Pilot precedes the full matrix. Full annual arrays and metadata are compressed artifacts with90-day retention; permanent source, protocol, final selection and run evidence are committed to the research branch. Do not modify or merge production. Report actual completed counts, stages and failures rather than requested grid size alone.
