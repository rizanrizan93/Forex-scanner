# R8-W — Causal event clustering and overlap embargo (2026-11-20 12:36 WIB)

Status: RESEARCH DESIGN ONLY; no real macro replay, no measured accuracy, no production changes.

## New falsifiable hypothesis
R6 M5 sweep+MSS events may cluster during a single directional displacement. Treating all overlapping H1/H4 forward outcomes as independent exaggerates effective n and makes uncertainty intervals too narrow. Test whether a fixed, causally determined event embargo improves *out-of-sample* directional accuracy and confidence calibration without hiding losing signals.

## Pre-registered comparison (not optimized on 2025-26)
A. R6 raw all eligible events; B. R6 with a fixed 60-minute per-side embargo; C. R6 with 240-minute embargo; D. A/B/C crossed with DOLLARIDXUSD 5/15/60-minute as-of momentum, after vendor data passes provenance gate. Embargo starts at decision timestamp and cannot inspect future outcome. Predefine tie-break by earliest timestamp then stable event ID; report excluded event counts and BUY/SELL counts per year. Do not call A/B/C independent strategies if outcomes overlap.

## Causal audit
- Vendor M1 candle must have UTC aligned open time; close_time = open_time+60s; available_at = close_time + measured/assumed nonnegative publication delay; event decision_time >= available_at.
- Compute quote_age_market = decision_time-close_time and quote_age_available = decision_time-available_at separately; enforce a pre-registered staleness threshold and log both.
- A 60-minute return needs 61 consecutive M1 closes with no gaps; never forward-fill missing market data.
- SHA-256 must be computed from retrieved original bytes, with URL, HTTP status, acquisition UTC, vendor instrument ID, and byte length recorded. A catalog listing alone is not a source-byte validation.
- 2019–23 development, 2024 validation; 2025–26 previously inspected, so descriptive stress-test only, not pristine holdout.

## Outcome and uncertainty
Report H1 and H4 separately: BUY wins/n, SELL wins/n, Wilson 95% intervals, per-year wins/n, gross and spread/slippage-adjusted net directional result, median favorable/adverse excursion, coverage and skipped-event reasons. Also report cluster-robust uncertainty by day/week or non-overlapping block bootstrap; no target >=60% claim unless each side meets threshold with defensible uncertainty and usable signal frequency. No $10 bounce optimization before dual-side validation.

## Acquisition attempt
At 2026-11-20 around 12:36 WIB, direct GET to https://datafeed.dukascopy.com/datafeed/DOLLARIDXUSD/2019/00/02/00h_ticks.bi5 failed before HTTP due to DNS NameResolutionError in execution environment. No source bytes, HTTP status, SHA, UTC vendor timestamps, or macro replay were obtained. This is an environment connectivity failure, NOT evidence that Dukascopy lacks history.

## Falsification criteria
Reject any claimed improvement that disappears with clustered uncertainty, falls below 60% on either side, has trivial sample size, worsens after execution costs, or depends on 2025–26 tuning. Do not silently drop conflicting USD observations; count and report them.

## Safety
Research branch only. No ForexScanner production, Frozen V1, Manual R3, LIVE cBot, bridge, order routing, or risk changes.
