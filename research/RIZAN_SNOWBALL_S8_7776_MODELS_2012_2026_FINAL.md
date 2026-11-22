# RIZAN Snowball S8 — 7,776 XAU structural model screening 2012–2026

**Date:** 2026-11-22 WIB  
**Status:** all research jobs completed successfully; no policy qualified for native Frozen V1 promotion. Research only.

## Objective and historical control

User's long-term objective: single-account hypothetical compounding from $100 → $125 → $250 → $1,000 → $10 billion with controlled floating equity DD. Historical Frozen Bootstrap125 V1 continuous backtest comparison remains a **simulation** of $1,662,133,293.08 / max equity DD ~56.67%, 2019–13 November 2026; never assert broker-capacity feasibility, expectancy or future performance.

This S8 is an independent **signal-level screening**, not a full matched Frozen V1 cTrader native ledger replay.

## Actual GitHub execution and verification

- S8 source: `scripts/snowball_s8_structural_xau.py`, workflow `.github/workflows/snowball_s8_structural_full.yml`, branch `research/bootstrap125-snowball-r2-20261122`.
- Pilot 2014 + 2024 **SUCCESS**: [GitHub 45027381750](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45027381750).
- **Full 14-year 2012–2025 SUCCESS**: [GitHub 45027476506](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45027476506). 12 structurally different intraday pattern families × 2 sides × 3 lookbacks × 3 H4 trend regimes × 3 sessions × 3 horizons × 2 ATR stops × 2 TP R targets = **7,776 configs/year**, or **108,864 model-year evaluations**. Each config evaluated for separate nominal cash $100, $125, $250 and $1,000. Data and sha256 provenance archived as GitHub Actions artifacts.
- Additional **2026 Jan–Aug partial retrospective SUCCESS**: [GitHub 45027528050](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45027528050), **7,776 additional model configurations**. Raw third-party archive stops in August; do not claim testing September–November 2026 or pristine future holdout. 2026 was *not* used in S8 train or validation.

### New structural hypotheses tested

Asian liquidity failure and range expansion, previous-day high/low failure and retest, daily-opening-price reversion, ADR extreme fade, London opening-range breakout, New York opening trap, M15 prior-fractal reclaim, z-score extreme reentry, z-score trend expansion, volatility compression-to-expansion. BUY and SELL independently. Not the same S5–S7 parameter grid, although some ideas share structure.

## Frozen predeclared selection and results

Train: 2012–2018. A candidate must have ≥120 trades, mean normalized stress net >0.03R, stress profit factor ≥1.12, and ≥5 profitable stress years. Only a training-qualified candidate would then qualify for validation (2019–2022; ≥70, mean stress >0.01R, PF ≥1.08, ≥3 profitable stress years); 2023–2025 is retrospective. **Never pick a strategy because it wins in one year.**

| Nominal available cash | Training-qualified | Validation-qualified | Retrospective-qualified |
|---|---:|---:|---:|
| $100 | 0 / 7,776 | 0 | 0 |
| $125 | 0 / 7,776 | 0 | 0 |
| $250 | 0 / 7,776 | 0 | 0 |
| $1,000 | 0 / 7,776 | 0 | 0 |

Annual in-sample best signals are **diagnostic, not selected policies**:
- 2014 ZSCORE_EXTREME_REENTRY SELL, hold 120m, ATR stop1.5, TP1.5R, n=38, simulated avg stress +0.21168R.
- 2024 ZSCORE_EXTREME_REENTRY BUY, H4_WITH, hold 120m, TP2.5R, n=36, simulated avg stress +0.43127R.
- 2026 Jan–Aug ASIA_RANGE_BREAK SELL, H4_WITH, US_WIB, hold120m, ATR stop1.5, TP2.5R, n=32, simulated avg stress +0.58514R. **Partial year, selected post hoc, NOT an OOS-verified leader.**

Different winners across years do not prove exploitable edge or greater Frozen V1 terminal balance.

## Strict limitations

- XAU M1 prices are from pinned third-party Dukascopy-derived bid/ask repository `3650326613-png/dukascopy_xauusd_1m_data` commit `1d8e4c008fe177be455f6de05f5057ebdde901ae`, **not FP Markets/cTrader and not checksum-identical frozen input**.
- 1oz assumed minimum XAU traded volume, leverage 1:200, per-entry planned risk ≤8%, margin ≤50% are hypothetical; actual FP Markets cTrader account symbol metadata and margin tier must be checked.
- Fixed estimated fee and slippage used to model stress, with stop-first within ambiguous M1 OHLC; **2x-cost stress was not rerun with full broker fill paths**, funding and live market impact unknown.
- The 4 cash levels are **independent admission filters at fixed balances**, not real sequential $100→$125→$250→$1000 account progression, nor concurrent XAU/EUR wallet or compounding to $10 billion.
- The historical data has been researched repeatedly, so even 2023–25 is not a pristine untampered holdout.
- **No native C# Frozen V1 matched ledger parity**, therefore no verified portfolio equity DD, increased filled baskets, time-to-tier, terminal balance or true uplift for S8.

## Decision

**Do not add an S8 strategy to Frozen V1 or live cBots.** The high-volume screen failed the conservative economic robustness gates. Preserve existing Frozen EUR seed and growth core.

Next research should prioritize exact checksum-matched original EUR/XAU/BTC M1 *and* native original C# strategy execution/ledger parity on GitHub with verified broker lot/margin/fee accounting. After parity, prioritize stage-specific portfolio add-ons and shared-risk batch/pyramiding, plus point-in-time verifiable macro regime factors. Do NOT repeat unsuccessful grids or retune to single-year 2026 maxima.

An **existing hourly RIZAN Trading & Growth Research automation** was updated to inspect these specific run IDs, report meaningful verified progress, and keep LIVE unmodified.
