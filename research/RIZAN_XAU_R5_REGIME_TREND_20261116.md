# RIZAN XAU R5 — Regime-Adaptive Trend, November 16, 2026 (WIB)

**Status: RESEARCH_ONLY; NO-GO for LIVE.** No change to Frozen V1, cTrader LIVE, bridge or production ForexScanner.

## Conditions and evidence

- $100 starting equity, compounding, reference leverage 1:200, maximum single-position risk 5%, initial margin cap 50% equity, no simultaneous positions, 08:00–13:00 WIB Asian entries and exit by 13:00.
- ASSUMED gold symbol contract 100 oz/lot, minimum volume .01 lots = 1 oz, .01-lot step, maximum .50 lots; **actual FP Markets cTrader specifications have NOT been checked**.
- Public mid-price OHLC M5 (NOT FP Markets bid/ask ticks): 497,345 bars from **2019-01-01 23:00 UTC to 2026-01-09 21:55 UTC**; SHA256 43c0bf9e15bc3c6b94b707112ebb7623571a7653cacfcbf4abb8cbd51247b3a5.
- Fixed roundtrip friction reference $0.80 per oz, conservative stop-first OHLC intrabar replay, SL beyond recent M5 structural swing, target 2R or time stop. Historical true tick floating drawdown, swaps, actual spreads and changing margin unknown.
- R5 macro uses publisher-lagged historical real yield DGS10/H10 broad US dollar proxy; broad-dollar index is **not ICE DXY** and original release timestamps were not independently verified.
- Simulated last-year profit is NOT proof the regime will recur or is ex-ante predictable.

## Full sample: six fixed technical hypotheses

| Strategy (M5 signals, H1/M15 regime) | Ending $100 equity | PF | Closed DD | Trades |
|---|---:|---:|---:|---:|
| Donchian-12 breakout | 24.13 | .088 | 75.87% | 72 |
| Donchian-24 breakout | 25.14 | .169 | 74.86% | 76 |
| Trend pullback EMA20 M5 | 22.83 | .191 | 77.17% | 70 |
| Compression to volatility expansion | 35.24 | .335 | 64.76% | 91 |
| Asian opening-range breakout | 24.78 | .439 | 75.22% | 117 |
| H1 trend microbreak | 22.42 | .097 | 77.58% | 74 |

**None is profitable.** A prospective $100 account would not survive the early years of this historical replay.

Macro proxy ablation on Donchian-12/H1/M15:
- Technical-only: $24.13 ending, PF .088.
- Lagged real yield + USD broad change direction: $35.66 ending, PF .390.
- Lagged real & nominal yields + broad USD: $34.94 ending, PF .346.
- Macro slows losses but does not create positive risk-adjusted expectancy.

## Recent 2025 diagnostic vs earlier years

On independent $100 restarts, Asian opening-range breakout:
- 2019–2022: $29.94, PF .456, 113 trades.
- 2023–2024: $45.98, PF .593, 98 trades.
- 2025–Jan 9, 2026: $120.17, PF 1.268, 36 trades.

**This is a regime hypothesis**, NOT a backtested classifier that reliably forecast those conditions.

## Additional daily-regime filter (exploratory, not blind OOS)

Use only the prior completed UTC daily bar (as-of the NEXT UTC midnight). Compare:
| Filter on Asian opening-range | Final $ | PF | Max closed DD | Trades |
|---|---:|---:|---:|---:|
| None | 24.78 | .439 | 75.22% | 117 |
| BUY only | 25.86 | .349 | 74.14% | 89 |
| D1 EMA20/100 direction alignment | 32.15 | .573 | 76.73% | 115 |
| BUY only with D1 closing above previous 60-day high | **92.51** | **.896** | **20.79%** | 40 |

The restrictive daily high-breakout gate preserves far more capital but is STILL NEGATIVE over the full sample. Independent $100 restarts for this gate: 2019–22 $94.91 (15 trades), 2023–24 $92.82 (23 trades), 2025–Jan2026 $101.18 (4 trades). Post-hoc screening carries strong selection bias. Low sample sizes prohibit confident return forecasts.

## Code and integration

- Read-only research engine: src/fx_scanner/xau_microalpha_r5.py
- Static/causality and risk tests: tests/test_xau_microalpha_r5.py
- Reproducible price and macro tests: scripts/research_xau_microalpha_r5_multiyear.py
- Daily-regime falsification: scripts/research_xau_r5_daily_regime.py
- Read-only Streamlit page: pages/7_XAU_MicroAlpha_R5.py
- Draft PR: https://github.com/rizanrizan93/Forex-scanner/pull/854 (stacked; not deployed)
- Research CI passed for R5 engine, data replay, and UI syntax. Current macro V400 quality screen is independently timestamp-checked at display time and never backfilled into historical candles.

## Decision

**NO-GO for all tested R5 entry strategies on the full sample.** The best discovery is a possible **regime eligibility / no-trade gate** using completed D1 60-day highs, not a robust profitable trading system.

Next: Verify actual FP Markets cTrader minimum XAU volume, contract size and broker-estimated margin in a safe read-only diagnostic. Revalidate selective regime model against data not used for selection, true bid/ask spreads and macro as-of history. NEVER bypass account risk limits or change Frozen V1 LIVE.
