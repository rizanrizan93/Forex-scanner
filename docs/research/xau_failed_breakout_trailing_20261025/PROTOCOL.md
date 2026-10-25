# Failed breakout with trailing exits — protocol

Declared before computing results, 25 October 2026. Research only; no live changes.

Data: existing BID M1 archive January 2019–March 2026; averaged spread ask proxy.
All historical data have previously been observed. This is not a new independent holdout.
No verified point-in-time macro or COMEX orderflow is available in this run.

Levels are the preceding UTC calendar day's or preceding completed UTC week's
high/low. Signals use closed M5/M15 bars only. A sweep must reclaim within one
or three signal bars. Either enter after reclaim, or require a subsequent close
through the three bars' high/low preceding the sweep, within three bars.
Entry variants: next M1 open, or first retest of the reclaimed level within 60min.
BUY and SELL are generated symmetrically. Stop beyond the observed sweep extreme
with 0.1 signal ATR buffer. Reject initial price risk below $1 or above $10/15/20.
No fixed take profit. Trailing distance $5/10/15 or 1/2 closed H1 ATR; activation
after favorable excursion $10/25. Initial stop stays until then; stop only tightens.
Update from a completed M1 bar for the NEXT bar, with current-close validity cap.
No favorable excursion/trailing update on a limit fill bar; original SL can hit.
Max hold 24/72h; one position overall, FIFO; no compounding or layers.
Daily regime uses last completed daily close, EMA20 and EMA20 slope across 5
completed daily bars. Up: close>EMA and positive slope; down: reverse; else flat.
Compare no directional filter versus trade only aligned with daily regime.

Costs: spread at entry/SELL exit, $0.17/oz fee and slippage proxy, adverse
$0.10/oz/calendar-day carry proxy (not broker swap). Cost2 reruns fills with double
spread and fee/slippage. Stops first; adverse gap fills; known data gaps >72h
excluded with warmup; disclose retrospective coverage exclusion. Require 40 daily
observations before signals, daily reference at least500 M1 bars, weekly2000.
Training entry 2019–2022, with max72h boundary embargo; review2023–2025 same
embargo; Q1 2026 diagnostic. Max-hold trades reaching the tape end are excluded.

Ranking uses TRAIN ONLY: first require >=60 total trades, >=20 each side,
PF>=1.5 and net win>=50% overall, and PF>=1.2 separately for BUY and SELL.
Rank by smaller side PF, then total PF, then sample size. Freeze first-ranked
candidate before evaluating review/Q1. Review acceptance: >=30 overall, >=10
each side; overall PF>=1.5, win>=50%, each-side PF>=1.2; bearish-regime >=10
trades and PF>=1.2. Cost2 review PF>=1.2. Q1 >=10 and PF>=1; otherwise inconclusive
or reject. Also report all train-ranked top10 without promoting a review winner.
If no train qualifier, show descriptive best minimum-side PF with n>=60/20 each,
explicitly unqualified. Report annual and regime results, consecutive losses,
R-equity drawdown (not account DD), net >=$25, MFE >=$25 and giveback.

Operational publication/consumer delay and broker tick parity are not validated
by this baseline. Test 60/300-second signal publication delays for frozen model.
No guarantee of catching every first touch; limit retests before publication
are permanently missed, not eligible on a later touch.

## Phase 2 extension (declared after phase 1, before phase 2 computation)

Phase1 has zero train qualifiers and its frozen descriptive candidate fails
review. To cover earlier/adaptive protection, expand only the exit grid: trail
distances additionally0.75/1.5/2.5 initialR; activation additionally immediate,
$5,0.5/1/2 initialR. Keep original distances/activations as controls. Total21,504
phase2 configurations, with the same entry rules, ranking and acceptance gates.
No review-based re-ranking; this extension is exploratory and uses already-seen
data. Root outputs remain phase1; phase2/ holds separate freezes and results.
PF in ranking is normalized by each trade's initial risk (PF_R); additionally
report ordinary PF for equal ounce exposure. Neither is an account replay.
