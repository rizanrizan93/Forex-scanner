# RIZAN Fed R6 — Causal SMC Swing Room and Adverse-First XAU Continuation Risk

**Date/freeze:** 2026-11-20. Research branch `research/fed-smc-pivot-risk-r6-20261120`, based on R5 #893. **No production authority.**

## Hypothesis A — Structural swing instead of arbitrary M5 candle high/low

Original V4 opposing-room veto (`_opposing_room`) uses
nearest prior M5 candle extreme in last 36 bars, which may be a
micro-candle fluctuation instead of a tradeable liquidity swing.
R5 paired real-XAU study observed V4=0 entry-qualified candidates
in 69/69 post-FOMC windows.

R6 A/B holds ALL other V4 requirements fixed (H1/H4 alignment,
closed-bar M1 sweep/reclaim/MSS, anti-chase, quote/spread, frozen
invalidation, failed rejection cooldown). Only opposing-room changes:

- Scan last **96 completed M5** candles.
- A structural swing HIGH must exceed both the **2 left + 2 right**
  completed neighbors. A LOW must be below all 4. Ties disqualify.
- Swing at M5 bar i is not visible until two subsequent M5 bars
  finish; the `confirmed_at` is the rightmost M5 candle CLOSE time.
  No future or unfinished M5 candles and no nonconsecutive local
  windows across a trading-session gap.
- BUY: nearest **confirmed past swing HIGH above ask**; SELL:
  nearest **confirmed past swing LOW below bid**. Opposing distance
  must still be **>=0.8 M5 ATR**. Unknown swing = WAIT, not infinity.
- Test whether changed room rule recovers any V4 candidate when
  the old room veto was **the ONLY unrelated rejection**. A prior
  breaker, excessive chase/spread, absent HTF, stale quote or failed
  pattern can NEVER be bypassed. R6 result remains a **research
  hypothetical**, not an order, despite any number of recovered
  candidates.

Important limitation: a confirmed swing is only a past structure
reference, NOT proof that institutions have resting orders there,
and this R6 method is NOT a calibrated SMC/ICT probability.

## Hypothesis B — Continuation H1 accurate direction vs realistic risk

R5 reported first unique post-FOMC M1 EMA9 + 3-bar breakout
continuation observation per meeting/rule/side, with H1 terminal
sign after synthetic XAU cost. That says nothing about the *path*
needed to survive until an H1 exit.

R6 prespecified evaluation:

- Same candidate detection from only M1 bars already CLOSED.
  M1 `i` closes → hypothetical entry `i+1` OPEN; cost $0.50/oz
  total round trip (synthetic, no FP Markets real quotes).
- Within the subsequent 60 consecutive M1 bars:
  `TARGET_FIRST` if favorable excursion >= **$3.50/oz gross**
  before any **$3/oz gross adverse** excursion;
  `ADVERSE_FIRST` if adverse touches first, including **same
  minute ambiguous target + adverse**.
- Freeze a *separate static invalidation reference* from three
  **pre-signal** M1 highs for SELL / lows for BUY, extended by
  0.10×M5 ATR. Measure whether it is touched before target.
  Do NOT move stop based on future profitable bars.
- Report maximum favorable excursion (MFE net of cost), maximum
  adverse excursion (MAE), H1 terminal signed return and censor
  incomplete futures. A terminal right direction that first
  hits adverse barrier/structural stop MUST be called a risky
  trade path, not an independently successful TP trade.
- **Independent unit = first continuation signal per FOMC
  meeting/rule/side**. Repeated M1 patterns in the same meeting
  are correlated; never count them as additional wins. Compare
  with a first-observation unfiltered BUY/SELL baseline.

## Research validity

Historical 2019–2026 USMPD FOMC market-response fields are
retrospective **EX-POST event-study** results; they are NOT actual
time-stamped LIVE OIS/TIPS/DXY surprises. 2019–26 has already
been extensively inspected, not an untouched holdout. Pinned
historical M1 is secondary-market, $0.50 synthetic cost only,
no actual executable bid/ask, slippage, gap risk, commission or
financing. A good retrospective result is **not** a proven
predictive 80% accuracy.

Production release gate:
- Genuine point-in-time intraday Treasury/TIPS/OIS/DXY quote
  capture and independently timestamped Fed source ingestion.
- Robust BUY and SELL evidence at >=80% against both first-adverse
  barrier/stop AND terminal H1 outcomes; enough independent new
  meetings with Wilson 95% bounds and positive expectancy.
- Strict fixed code/thresholds BEFORE the new prospective events,
  forward testing; replay of prior researched years is diagnostic.
- Never change Frozen V1, Manual R3, LIVE cBots, ForexScanner
  production, broker bridges, leverage or order routing without
  separately validated and authorized release.
