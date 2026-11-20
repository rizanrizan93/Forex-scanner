# R8-E: Failed-auction x volatility compression (preregistered, no accuracy claim)

Date: 2026-11-19. Research-only extension. No market data processed in this note.

## Distinct falsifiable hypothesis
R6 M5 sweep/MSS reversals may work only after a local volatility contraction followed by a failed auction, while continuation dominates when the sweep closes outside the prior range with expanding realized range. This is **not** a DXY sign filter; test it independently before any combination with R8-D.

## Causal features at event confirmation
For each R6 event, calculate prior 12 completed M5 bars' median true range, and prior 48 completed M5 bars' median true range, using only closes <= event confirmation UTC. Compression = median(TR12)/median(TR48) <= 0.75 (candidate, frozen before replay). Failed auction = wick crosses prior 12-bar extreme and M5 confirmation closes back inside prior 12-bar range; continuation candidate = close outside prior 12-bar extreme with event bar TR >= 1.5 * prior-48 median TR. Compute both separately for upside/downside, symmetric BUY/SELL; otherwise WAIT. Prevent overlapping labels from leaking into splits.

## Test design
First run 2019-2023 development, 2024 fixed validation, 2025-26 descriptive stress only (reused, NOT pristine holdout). Compare with exact R6 event ledger, matched year/session/side cohorts and baseline, H1/H4 separately, fixed $0.50/oz cost assumption. Report each year and side: eligible n, retained n, win n, Wilson 95% CI, coverage, drawdown and net excursion if available; no claims for missing data. Apply block bootstrap by week to address clustered signals. Freeze one future prospective event timestamp for truly untouched evaluation. Do not select a threshold by 2025-26 outcomes.

## Required provenance and stop conditions
Requires individual real XAU R6 M5 events, raw M1/M5 source hashes, UTC normalization, event close and executable entry timestamps, forward labels and cost. No synthetic OHLC or backfilled event timestamps. Any missing ledger or unverifiable source -> NO RESULT. DXY native data accessibility remains a separate R8 blocker; DOLLARIDXUSD is not official ICE DXY.

## Promotion gate
Require >=60% BUY AND >=60% SELL on both H1/H4, adequate independent signal count, lower confidence bounds and positive net cost-adjusted expectancy on prospective sample. No automatic production push, cBot changes, bridge, routing, or risk edits.
