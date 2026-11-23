# RIZAN R32 — Liquidity Sweep + Failed Breakout, XAUUSD 2012–2026

**Status:** COMPLETE FOR SOURCE-TIMEFRAME REPLAY; M5 FULL REPLAY BLOCKED BY SOURCE PROVIDER. **Mode:** Research-only / no broker orders or Frozen V1 modification. Evidence date: 2026-11-23 UTC (2026-11-24 WIB).

## GitHub receipts

- Actual source-TF full replay: [R32L GitHub Actions run 45257172812](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45257172812), **34/34 jobs success**, audited **33,554,432 distinct parameter combinations** (256 candidate direction rules × 4,096 zone filters × 8 exits × 4 timeframes).
- Post-selection stability: [run 45258099823](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45258099823), success, examined all 32 per-model shard result sets.
- Targeted W1 development-period audit: [run 45258479548](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45258479548), success.
- M5 historical data pilot: [run 45256100542](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45256100542), **FAILED** because Dukascopy minute endpoint returned HTTP 403 for 2012 and 2024. No TLS bypass, synthetic M5 bars, or claims of actual M5 execution.

## Study design

The new source-TF family tests liquidity grabs of *previous* rolling highs/lows (lookback 4, 8, 16), a close back inside the broken range, optional subsequent closed-candle confirmation, and entry at the **next fully opened SOURCE-TF candle**. Direction proxies are calculated from closed same-TF momentum, EMA and RSI (256 variants), never from unclosed candles. Risk is based on the swept source-candle distal extreme. Stop-first for intrabar OHLC ambiguity and worse opening prices after stop-breaching gaps. Only events with valid following candles are counted; no gap imputation or same-bar entry. No bid/ask spread or actual FP Markets slippage parity. Net dollar values are **USD/oz assuming a fixed $0.70/oz trading cost**, not portfolio P&L or actual broker net.

**Source:** H1/H4 session-filtered Dukascopy BID from R30 run 45190531878, 2012–2026; D1/W1 HistData-derived daily shards from R98 run 44886465487, 2012–2026. Providers are different; avoid cross-TF P&L comparisons as if matched execution feeds. The 2026 calendar year is incomplete.

**Model provenance:** These are new technical proxy candidates; **not a reconstruction** of live frozen R25/R11/R29.2/R18/R27/R24 forecast heads. The source-TF replay must not be represented as M5/M15 precision, cTrader live parity or a validated 80% strategy.

The candidate search uses development 2012–2020 and validation 2021–2023. Historical 2024–2026 is merely *retrospective*: it was repeatedly studied in previous R30/R31 work and is **not pristine OOS**. Heavy multiple comparisons create selection bias. Per-TF results apply a one-position-at-a-time non-overlap constraint.

## Summary

| TF | Source-TF sweep candidates | Validation-filter passes in 32 shard toplists | Best validation candidate | 2024–2026 retrospective outcome |
|---|---:|---:|---|---|
| H1 | 42,321 | Yes | 105 trades, 68.57% win, PF 1.405, net +$56.17/oz | 75 trades, 44.00% win, PF 0.557, **−$195.54/oz** |
| H4 | 1,036 | **0** | No qualifying case | Do not infer |
| D1 | 2,442 | Yes | 60 trades, 63.33% win, PF 1.160, net +$92.75/oz | 48 trades, 35.42% win, PF 0.521, **−$897.40/oz** |
| W1 | 434 | Yes | 25 trades, 72.00% win, PF 3.236, net +$319.03/oz | 15 trades, 60.00% win, PF 0.622, **−$351.64/oz** |

**Highest-frequency H1 diagnostic, irrespective of profit:** 2,209 validation trades, 50.52% wins, PF **0.459**, net **−$2,131.97/oz**. Higher signal count is not automatically useful alpha.

## Every preselected finalist: robustness audit

| TF | Unique source-TF validation finalist configs | Net-positive on 2024–26 | Meet retrospective PF, win rate, 2 profitable years, min trade count and stress simultaneously |
|---|---:|---:|---:|
| H1 | 34 | 1 | **0** |
| H4 | 0 | 0 | **0** |
| D1 | 32 | 3 | **0** |
| W1 | 25 | 8 | **2** |

The **two W1 survivors are closely related, not independent confirmations**. Exact fixed variants, both target 0.60R / hold 3 W1 bars / zone config 0:

| W1 proxy | Development 2012–2020 | Validation 2021–2023 | Retrospective 2024–2026 |
|---|---|---|---|
| Model 138 | 64 trades, WR 53.125%, PF **0.930**, net **−$51.93/oz** | 20 trades, WR 75%, PF 4.266, net +$318.36/oz | 12 trades, WR 75%, PF 1.677, net +$233.26/oz |
| Model 142 | 56 trades, WR 51.79%, PF **0.926**, net **−$50.21/oz** | 20 trades, WR 75%, PF 4.266, net +$318.36/oz | 10 trades, WR 80%, PF 2.581, net +$220.11/oz |

For model 138, retrospective annual trade counts were **7 in 2024, 2 in 2025, 3 in 2026**; for model 142, **7, 2, 1**. Both have small samples, 2024 net losses, and negative nine-year development profitability. Their positive retrospective results therefore do **not** establish robust long-run edge or high trading frequency.

## Outcome and next steps

**NO PROMOTION.** No candidate demonstrates compelling combination of high trade frequency, persistent profitability, acceptable drawdown and stable multi-regime performance. Source TF strategy research remains isolated from ForexScanner's frozen live candidate selector and RIZAN Frozen V1.

A materially different, testable next hypothesis must obtain a **verified minute/tick historical price source** (minute endpoint HTTP 403 is currently blocking our genuine M5 research) and reconstruct the **actual historical frozen direction signals point-in-time**, then compare liquidity sweep / order block / FVG / MSS under no-overlap, realistic costs and incremental forward shadow evidence. More configurations of a failing family are not a substitute for independent validation.
