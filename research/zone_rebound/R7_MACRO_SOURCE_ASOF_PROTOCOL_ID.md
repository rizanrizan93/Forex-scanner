# RIZAN XAUUSD R7 — Macro cross-market provenance & no-lookahead handoff
Date: 18 November 2026, Asia/Jakarta. Status: **source catalog + causal validation module only; no 2019–2026 macro backtest yet.**

## Research objective
Find a high-selectivity H1 or H4 XAU BUY/SELL signal with >=60% out-of-sample directional accuracy for **both sides** with meaningful n, transparent transaction costs, and new genuinely future validation. Do not investigate the USD10 rebound until this direction gate is met.

## New public-data discovery
1. **Dukascopy DOLLAR.IDX/USD** with historical **1-minute** samples reported from 2017-12-01; symbol `dollaridxusd`. Candidate coverage for 2019–2026. This is a Dukascopy broker quote of the dollar-index-linked instrument, **NOT official ICE DXY**. Instrument and date-window catalog: https://www.dukascopy-node.app/instrument/dollaridxusd and https://www.dukascopy-node.app/quick-start .
2. **ICE official DXY** cash index published intraday; the ICE data source is separate from the Dukascopy quote. The data service lists historical access; it has not been licensed or downloaded by this project. https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-currency-indices .
3. **CME 2Y and 10Y Treasury note futures**, symbols **ZT** and **ZN**, have 2019–2026 minute data reported by commercial archives (e.g. https://firstratedata.com/i/futures/ZT and https://finzdata.com/futures/zn ). **These are futures prices, not official 2Y/10Y cash yields**. Futures/actual yield have broadly inverse directional relationship but not a one-to-one mapping; expiry, cheapest-to-deliver, CTD/duration, carry, and contract rolls require explicit handling.
4. **DGS2 / DGS10 (FRED)**: official daily constant maturity rates, **not intraday**. Never use the same day's DGS close before its actual publication time or as a fictitious per-minute yield. Sources: https://fred.stlouisfed.org/series/DGS2 and https://fred.stlouisfed.org/series/DGS10 .
5. Optional free bond ETF **IEF** and **TLT** Dukascopy source exists but US equity-session-only instruments; they are market-price proxies and not equivalent to yields. The restricted session makes them poor proxies for XAU's Asia hours. No 2019–2026 minute coverage has been downloaded/tested.

## Implementation now available
- `research/zone_rebound/xau_r7_macro_asof.py`: conservative UTC-only M1 quote validation; rejects timezone-naive, bad OHLC, duplicates, unsupported sources. Computes independent 5/15/60-minute quote returns using **contiguous** historical minutes only.
- Each M1 quote is stamped at candle **OPEN**. Earliest estimated availability = `open + 1 minute bar duration + 1 minute conservative delivery delay`. Join is backward from the XAU decision timestamp; future quote bars and newly opened candles cannot enter the feature set.
- If source is stale (>5 min since available) or there is an M1 gap in the 60m feature window, mark `macro_ready=False` and set unavailable returns null. An unavailable source yields **WAIT**, never optimistic synthetic data or interpolated future data.
- Strict flags `is_official_ice_dxy=False`, `is_cash_treasury_yield=False` and `EXECUTION_AUTHORITY=False` protect against false labels or LIVE execution.
- Unit tests `tests/test_xau_r7_macro_asof.py` verify a future quote changed only after its publication timestamp, gaps, bad sources and stale rejections. GitHub Actions performs tests. Tests use **synthetic M1 quotes** to test code correctness; they are **not proof of market predictive accuracy**.

## Still outstanding
**Not yet downloaded:** real historical `dollaridxusd` 2019–2026 joined with XAU event timestamps. Before running real replay, retrieve Dukascopy M1 data with precise UTC as-of and provenance SHA per calendar year, investigate quote-side (bid/ask/mid), missing minute profile and index tracking error against ICE DXY spot during overlapping periods. Quantify session-specific DXY-freshness coverage. Treat any comparison with official DXY benchmark as a separate license/access question.
**Not yet sourced:** ZT/ZN intraday 2019–26 with proper roll rules and legally accessible data. No data purchase has been made or authorized. Daily FRED releases may be used only as macro *known at timestamp* controls, not as intraday innovations.
**Not yet tested:** R7 macro-confirmed H1/H4 BUY/SELL direction or accuracy. **Do not quote R7 as 60%, or promote to ForexScanner, until independent replay.**

## Fair forward-evaluation design
R1–R6 have already examined 2025–2026 repeatedly: that period is a **research-touched test**, not an independent project-pristine holdout. Pre-register directional hypotheses and decision threshold before the next genuinely unseen forward period. Compare same M5 events with/without DXY return sign and volatility, analyze H1/H4 outcomes after illustrative $0.50/oz costs, no within-bar future labels. Report annual BUY/SELL n, coverage, 95% confidence lower bound, session breakdown, false positive rate, positive and negative regimes, paired-event uplift. Require both sides >=60% on sufficiently independent n, and spread/cost robustness. Do not use as-if 2025–2026 remained pristine after screening six generations of models.

## LIVE SAFETY
Frozen V1, Manual R3, cBot LIVE, bridge and risk controls untouched. This branch is research and data QA only.
