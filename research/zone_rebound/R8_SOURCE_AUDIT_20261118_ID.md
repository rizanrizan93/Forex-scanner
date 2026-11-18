# R8 18 Nov 2026 — DOLLAR.IDX/USD availability correction and source probe

## Verified change from R7 source assumptions
The Dukascopy-node instrument catalog **explicitly says M1/M5/M15/M30: NOT PUBLISHED**, while tick/S1 and H1/H4/D1 are listed starting 2017-12-01. R7's claim that M1 was directly published was incorrect. This is a meaningful data-availability blocker, not an accuracy result. Reference: https://www.dukascopy-node.app/instrument/dollaridxusd

## Actions in this cycle
- Reviewed PR #880, #881, #882, #883, #884 and their baseline claims. R6 BUY/SELL H1/H4 still failed >=60% dual-sided criterion.
- Created isolated source-probe workflow to fetch real H1 DOLLAR.IDX/USD 2025-06-02 through 2025-06-06 (bid CSV) and audit UTC timestamps, H1 gaps, price integrity, SHA256 and first available timestamp. H1 bar opens must never be used until **bar close + 2 min**.
- **No minute-level DXY claim** from this workflow; no XAU model fit or real-data 2019–2026 DXY macro ablation yet.
- To test 5/15/60-minute macro returns at M5 entry timestamps, obtain raw ticks or S1 and reconstruct M1 with explicit price-side, sparse-bar and timestamp rules. Do not fill missing minutes or assume an H1 quote is known mid-hour. H1-based macro may be evaluated as a separately registered slow-moving regime filter.
- Treasury ZT/ZN historical futures data still absent; daily DGS2/DGS10 cannot be used as intraday surprises.

## Required future independent experiment
For each R6 M5 event, join latest completed H1 dollar-index bar at XAU decision timestamp (H1 open+62 minutes), reject source age >120 min and missing H1 observations, compare R6 unfiltered and DXY trend-concordant vs trend-discordant paired events. **Freeze filter before** testing next untouched forward observations; 2025–26 was already inspected repeatedly. Report by year, H1/H4 horizon, BUY and SELL counts, costs, confidence intervals, coverage and false-discovery sensitivity. Avoid selecting winners on repeatedly inspected 2025–26.

## Safety
Research branch only; no production ForexScanner, Frozen V1, Manual R3, cBot LIVE, bridge, routing, sizing or risk changes.
