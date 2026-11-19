# R8 — Dukascopy DOLLAR.IDX/USD provenance & causal M5 R6 conditional macro research

Date: 2026-11-19 (WIB). Research-only, no production, cBot, Frozen V1, bridge, or order changes.

## New hypothesis and falsification

**Hypothesis R8:** an R6 M5 sweep + MSS event conditional on point-in-time 5/15/60-minute changes in Dukascopy DOLLAR.IDX/USD (a proxy, not ICE DXY) increases directional precision separately for BUY and SELL without collapsing trade count. Compare to the unchanged R6 baseline; do not select threshold using the 2025–2026 period again. Report n, successes, Wilson 95% intervals, trade frequency, year-by-year results and net-cost sensitivity for each side.

**Falsify** if either BUY or SELL fails the 60% lower-confidence target out-of-sample, if improvement disappears after realistic timestamp delay, if sample size is insufficient, or if macro observations are stale/unavailable. No $10 bounce objective until direction clears both sides.

## Provenance and availability audit

R8 adds `r8_dxy_proxy_asof_audit.py` which reads *supplied* real M1 CSV bytes with UTC-open timestamps, checks SHA256, explicit HTTPS source, OHLC, duplicates, gaps, source-age and full completed M5/M15/H1 bars. At each event timestamp, only the last closed DXY proxy bars can be used; missing or stale features are marked UNAVAILABLE. This does **not** download or establish that actual Dukascopy files have been retrieved.

Source candidate: Dukascopy historical DOLLAR.IDX/USD, advertised M1 from 2017-12-01; must verify reachable source endpoint, download provenance, timezone, licensing, coverage and SHA before treating as a real replay. ZT/ZN futures are inverse-yield price proxies requiring roll/cost/license; FRED DGS2/DGS10 are daily, not intraday.

## Planned event replay (not yet run)

1. Obtain real XAU M1 2019–2026 with provenance and real Dukascopy dollaridxusd M1. Save immutable SHA256 manifests, UTC time semantics, publication/quote age.
2. Freeze R6 event definitions and baseline before conditioning on macro.
3. At each event t, attach DXY proxy changes for last completed 5/15/60m intervals, with configurable causal delays 0, 1, 5, 15 minutes; drop stale/missing observations, not forward-fill through gaps.
4. Compare R6 only, R6 + DXY sign agreement, R6 + DXY sign disagreement, and abstention threshold. Evaluate BUY and SELL separately by calendar year; avoid optimizing repeatedly on 2025–2026. Prefer rolling-origin evaluation and an untouched prospective period.
5. Calculate counts, hit rate, Wilson 95% CI, spread/slippage 1×/1.5×/2×, event-to-entry latency, median excursion and annual trade frequency. Do not report performance without real replay.

## Evidence status

PR #880 macro handoff, #881 baseline, #882 negative R2/R3, #883 negative R6, #884 R7 as-of gate CI (per research brief). These are not evidence that R8 achieves 60%. GitHub files of these PRs are not necessarily on main; default-branch fetch returned 404 during this run. The research module and tests are on branch `research/rejection-engine-v1-20261119` for inspection, not production. The tests use synthetic fixtures, not market replay.

**Current empirical BUY n: unavailable; SELL n: unavailable; BUY accuracy: unverified; SELL accuracy: unverified.**
