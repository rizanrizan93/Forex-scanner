# R8-D (19 Nov 2026 15:40 WIB): abstention/coverage hypothesis, not a backtest

## New question
Does point-in-time DOLLARIDXUSD inverse momentum **remove low-quality R6 M5 sweep/MSS events** without destroying usable BUY/SELL opportunity counts? The objective is not to maximize conditional accuracy on a tiny cherry-picked sample.

## Preregistered comparison
For each R6 event at its true M5 confirmation close, obtain the latest eligible DXY M1 data as-of the event, requiring completed bar plus conservative publication lag and quote-age <=120s. Evaluate fixed 5, 15, 60-minute windows independently, not choose the best on test outcomes. BUY is accepted if DXY direction is DOWN; SELL if UP. FLAT, stale, missing, ambiguous -> abstain. Report raw R6 baseline vs accepted group, per year, H1/H4, BUY/SELL, including denominator, n, wins, 95% Wilson, percentage coverage, and stale fraction. A high conditional percentage with 1/100 events is not useful.

## Dataset blocker and source access
The earlier R8-C infrastructure is an integrity-only contract; it is NOT evidence of completed historical DXY ingestion or matched real R6 event replay. Dukascopy DOLLARIDXUSD catalog coverage is only a candidate, not proof of a native M1 archive. Need a source-native sample (tick/S1/H1 as actually available), source URL, provider time convention, UTC normalization, original-byte SHA-256, normalized-file SHA-256, no synthetic gap filling, and precise as-of/publication timestamps. R6 needs a **per-event** ledger, not yearly aggregates; event IDs, event close UTC, side, entry price, horizon, forward label, costs, source hash and overlapping-event clusters. Neither source is fabricated.

## Controls
- Compare inverse DXY against same-side baseline and unconditional matched cohorts, including source-coverage selection bias.
- Label H1 and H4 separately and preserve $0.50/oz cost assumption from R6 until true spread/slippage exists.
- Freeze 2019–23 development and 2024 validation rules; **2025–26 are contaminated/reused**, not pristine holdout. Start an immutable prospective event log from a future timestamp, with no threshold revisions midstream.
- Use Wilson lower 95% >=60% as an exploratory gate only; prospective cluster-robust evaluation and adequate annual regime coverage are still required before promotion.
- R8-D audit module is intentionally NOT an ingestion or as-of validator; upstream real source and label verification remain mandatory.

## Work done this cycle
Created `research/zone_rebound/r8d_selective_coverage_audit.py`, `tests/test_r8d_selective_coverage_audit.py`, and a standalone CI workflow. These validate fail-closed outcome types, SHA format, duplicate event/horizon rejection, stale-data abstention, BUY/SELL symmetry, and sample-size gates. **No historical market observations were analyzed in this cycle. No real BUY/SELL n or accuracy is available.**

No change to production ForexScanner, Frozen V1, Manual R3, LIVE cBot, bridge, risk or order routing.
