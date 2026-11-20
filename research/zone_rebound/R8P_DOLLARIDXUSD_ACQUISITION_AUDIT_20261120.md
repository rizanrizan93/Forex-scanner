# R8-P — DOLLARIDXUSD acquisition feasibility and falsification protocol (2026-11-20)

Status: **CATALOG CONFIRMED; RAW BYTES NOT ACQUIRED; NO REAL MACRO REPLAY**. Research only.

## Source audit (secondary catalogs, not vendor byte verification)

- cpcerrato/dukascopy-downloader `docs/instruments.md` (catalog updated 2025-12-21) advertises `DOLLARIDXUSD` M1–M30 from **2017-12-01** (UTC). https://github.com/cpcerrato/dukascopy-downloader/blob/main/docs/instruments.md
- knusul/dukascopy-tools README advertises DOLLAR.IDX/USD earliest minute **2017-12-01 00:45 UTC**, earliest tick **00:45:45 UTC**. https://github.com/knusul/dukascopy-tools/blob/master/README.md
- These are third-party catalogs. They establish *advertised coverage*, **not** that a 2019–2026 minute archive was downloaded, nor that it is official ICE DXY. The earliest minute need not have a full hour of lookback.

## Acquisition acceptance gate (fail closed)

1. Download a small **2019** UTC sample through a documented endpoint/CLI. Record exact request URL, tool name/version, UTC retrieval time, HTTP status, response content-type, bytes, SHA-256, and source licensing terms. Do not assume a catalog URL is a vendor data URL.
2. Retain original compressed bytes and immutable acquisition log. Record a manifest for each partition; R8-L checks manifest-byte consistency but **cannot authenticate vendor independently**.
3. Decode independently into UTC M1 with explicit **bar-open** timestamps. Reject duplicates, out-of-order records, impossible OHLC, nonpositive quotes, and undocumented timezone conversion. Record transformation code SHA-256.
4. Compare a small sample against independent Dukascopy UI/vendor export where possible. Reconcile spread and price scale. Mark any unverified provenance **INELIGIBLE_FOR_REPLAY**.
5. For each XAU R6 event at UTC t, choose USD M1 bars with close_time + publication_lag <= t; report quote_age=t-(last_bar_close+lag), source SHA, and 5/15/60-minute lookback continuity. Reject missing lookback and future bars. Pre-register lag and age; do not silently choose a more favorable threshold.
6. Produce event ledger with event_id, event_utc, side, H1/H4 outcome, xau_source_sha256, usd_raw_sha256, usd_last_available_utc, quote_age_seconds, lag_seconds, USD momentum 5/15/60, and abstain reason. R8-I must pass; keep cross-horizon event identity consistent.
7. Ablate R6-only, USD 5m, 15m, 60m, all three, and quote-age strata. Report per year/side/horizon n, accuracy, Wilson95, coverage, costs, and overlapping-event cluster uncertainty. Development 2019–2023; 2024 validation; 2025–2026 previously exposed descriptive stress only.

## New falsifiable hypothesis: post-breakdown exhaustion vs continuation

Following a strong M5 displacement beyond a prior low/high, define **exhaustion** using *only completed M5 bars at decision time*: displacement size / trailing pre-event M5 median true range, wick-to-body ratio, and first retrace depth. Pre-register thresholds on 2019–2023. Compare (a) R6 baseline, (b) R6 + USD lag, (c) R6 + exhaustion, (d) combined. A large sell candle alone is not proof of reversal; if no confirmation, abstain. Use distinct BUY and SELL thresholds only if trained inside development folds, never on 2025–2026.

## Current blockers

No raw DOLLARIDXUSD partition, original SHA-256, XAU R6 event ledger, independently validated timestamp semantics, or real R8 BUY/SELL sample count was obtained in this cycle. Therefore **no claim of >=60% accuracy** and no LIVE changes.
