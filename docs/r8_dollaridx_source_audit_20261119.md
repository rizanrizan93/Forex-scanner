# R8 19 November 2026 — DOLLARIDXUSD source audit and falsification plan

## What was verified
Independent instrument catalogs list Dukascopy `DOLLARIDXUSD` M1 starting 2017-12-01 UTC (catalog metadata, NOT a downloaded 2019–2026 dataset):
- https://github.com/cpcerrato/dukascopy-downloader/blob/main/docs/instruments.md
- https://github.com/knusul/dukascopy-tools/blob/master/packages/dukascopy-cli/README.md

This is the Dukascopy DOLLAR.IDX/USD index CFD proxy, **not** licensed ICE US Dollar Index futures. Provider availability metadata does not verify any specific day's candle, spread, archive integrity, or complete 2019–2026 coverage.

## New R8 hypothesis
After a CLOSED M5 liquidity sweep + market-structure shift (R6 event), XAU continuation or failure may depend on whether the USD-index proxy was already rising/falling in each of 5, 15, and 60 minutes **before** the event. This is an *as-of conditional* test, not a same-bar hindsight classification.

Predictions (falsifiable):
- SELL XAU + USD-index rising on 15/60m may have better downside follow-through than SELL XAU + USD-index falling.
- BUY XAU + USD-index falling may have better upside follow-through than BUY XAU + USD-index rising.
- Compare both against R6 without macro, against unconditional H1/H4 direction, and against a lag-shuffled placebo.
- A conflicting USD proxy is an **abstention candidate**, not automatic reversal.

## Evidence and blockers
No verified source-native `DOLLARIDXUSD` CSV, matching XAU event ledger, bid/ask costs, or actual R8 replay are available in this run. **n BUY = unavailable; n SELL = unavailable; 60% target not met or established.** Do not substitute the earlier R6/R7 numbers as R8 outcomes.

## Protocol for next data-backed run
1. Acquire native Dukascopy dollaridxusd historical M1 for independent years; record original URL, request time, original payload SHA256, parser version, UTC OPEN semantics, publication/quote age, and archive failures. Build CSV with `available_at` sourced from a defensible publication-lag model, not invented from bar time.
2. Run `scripts/research_r8_dollaridx_asof_audit.py` against CSV+manifest. Audit source time, close time, as-of, SHA256, geometry, duplicates and gaps. A valid schema alone does NOT prove historical live availability.
3. Match only R6 M5 event timestamps to DXY candles already closed AND observable as-of event; exclude missing data. Add 5/15/60-minute DXY direction without peeking into the event's future.
4. Per year 2019–2026 and separately BUY/SELL: report eligible events, coverage, n, hit-rate, Wilson 95% interval, gross/net after spread and slippage, MFE/MAE and 60m/240m outcomes; use same event and cost definitions as baseline.
5. Lock rules before testing a fresh prospective period; 2025–26 are contaminated by prior hypothesis searches, not pristine holdout. No >=60% conclusion without adequate n and both sides' confidence intervals.
6. Negative controls: timestamp +60m leakage placebo (must not be used for signals), shuffled DXY alignment, stale quote gate, volatility-regime and session splits. Correct for multiple comparisons.

## Research scope
Research branch and draft PR only. No merge to main, no live strategy or broker action.
