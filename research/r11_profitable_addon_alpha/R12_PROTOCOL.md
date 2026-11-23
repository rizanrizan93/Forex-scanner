# R12: V1 additional frequency through higher-timeframe pullbacks

Registered 24 November 2026 WIB before obtaining R12 price outcomes. Research only; no production or core changes. Parent R11B commit 26bf8396b6e703d650e703fca48d556252782f03.

## Why another experiment

R11B artifact 14777662661 from run 45082778115 shows 0/256 development passes, despite 16 positive pooled stress configurations. Increasing its spread threshold again is prohibited by its protocol. R12 is a disclosed new, outcome-informed experiment, not an independent confirmation: two related EMA reclaim hypotheses on M15/M30, testing whether a simpler multi-stage pullback with larger price scale has sufficient opportunities after unchanged R11B spread admission and costs. Earlier studies already tested EMA reclaims; no novel-family or untouched historical holdout claim.

## Fixed policy before results

- 32 correlated configurations: M15/M30 x EMA20/EMA50 x BUY/SELL x hold120/240 minutes x target1.5/2.5R. No loss pause, one independent active position plus five-minute embargo, no pyramiding, no extra units or lot increase.
- Completed H4 EMA20/80 direction must agree. No separate H1 alignment. EMA50/20 on decision timeframe is only an entry reference, not a macro forecast.
- A complete bar touches EMA within 0.10 ATR and closes on the trend side, after prior close was on that side of the then-known EMA. Lock this bar's high/low, invalidation and ATR. At least one later complete bar must close beyond its extreme by 0.05 locked ATR, with directional body >0.15 current ATR. Expire after four bars, reset on missing bars, H4 change, or close beyond invalidation. Pending state cannot move its anchor. New setup only after previous setup resolves or expires.
- Stop anchored beyond pullback extreme by0.10ATR with minimum1.25 decision ATR as in R11B replay. Enter next M1 open at decision timestamp. Entry UTC hour<16; maximum240min avoids scheduled21/22UTC rollover, but actual gaps are retained and charged by inherited engine.
- Same vendor/source pins, bid/ask validation, commission/slippage1x/2x, spread<=0.35ATR, paths A/B, retained gap losses, fixed1oz standalone ledgers as R11B. This is not a native Frozen portfolio replay.
- Annual2012-2025, 2026 Jan-Aug partial. Development2012-2018: both stress paths N>=100, expectancy>0.02R, PF>1.10, >=5 positive years. Validation2019-2022: N>=50, expectancy>0.01R, PF>1.05, >=3 positive years. Evaluation2023-2025: N>=30, expectancy>0, >=2 positive years. 2026 partial never used to select. Stop research tuning after outcomes; report failures and all policies.
- Expanding walk-forward selects only from earlier years. Passing economic screens is INCONCLUSIVE, requires forward evidence and native shared-wallet comparison before promotion. Report frequency, positive and negative filled standalone opportunities, net flat-ounce USD and R, PF, year consistency and all rejects. Incremental V1 baskets, wallet balance change and floating drawdown stay null.

## Implementation checks

Prefix causality, positive and negative direction event fixtures, gap reset, locked anchor, next-open entry, OHLC path ambiguity and doubled costs. Real data provenance hashed monthly. No synthetic prices in experiment output. Pilot checks mechanics only and does not gate historical profitability.

R11 and R11B together512 configurations plus R12's32 and prior searches: related trials must be disclosed; no unadjusted significance claims. Exact Frozen native data/tapes/reference ledger and broker specifications remain unresolved blockers to a portfolio profit claim.
