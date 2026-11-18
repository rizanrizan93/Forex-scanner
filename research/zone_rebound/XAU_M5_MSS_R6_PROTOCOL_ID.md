# RIZAN XAU R6 — M5 sweep + confirmed market structure shift (MSS) to predict H1/H4

**Research-only, 18 Nov 2026 WIB.** This is NOT an approved live strategy and contains no broker or bridge calls. Extend R1/R2 direction audits without modifying Frozen V1, Manual R3 or cBots.

## Why test R6
R1 H1/H4 technical signals, R2 logistic/HGB, R3 rolling logistic, R4 22 OHLC event families x 10 filters, and R5 cost-aware CatBoost have NOT robustly achieved >=60% net direction accuracy for BUY and SELL. R4 strong displacement H4 SELL showed 63.46% on 52 **post-hoc selected** events but was only 33.33% on 27 validation events. Do not treat that as a discovered >=60% strategy.

This R6 uses new **M1-to-M5 event clocking**, which is distinct from R4's H1/H4 end-of-bar features.

## Causal contract
1. Download public HistData XAUUSD M1, verify source SHA, year and failed periods. Dates published by supplier; data unavailable after its latest date are NOT guessed. Public spot data ≠ FP Markets executable bid/ask.
2. Aggregate **only complete** five-minute candles with timestamps at their right edges.
3. Generate past-information-only liquidity levels: previous 12 complete contiguous M5 high/low, previous 36 complete contiguous M5 high/low, or completed previous observed UTC trading day's high/low (minimum 100 M5 bars).
4. Mark a sweep when the M5 extreme pierces level by >=0.04 M5 ATR, closes back inside by >=0.04 ATR and its rejection wick is >=25% of total candle range.
5. Two event timestamps are predeclared: immediate M5 reclaim close, or an MSS close **within the following 3 complete M5 candles** breaking the pre-sweep three-M5 highs/lows in reversal direction. The MSS signal timestamp is the actual later confirmation bar, never backdated to the sweep.
6. Context variants: NONE, last-completed H4 trend aligned, last-completed H4 trend counter. Three sessions: Asia 08–14 WIB, London 14–19 WIB, New York 19–01 WIB plus ALL. A global cooldown of 60 minutes for H1 and 240 minutes for H4 avoids overlapping observations within each policy.
7. M1 open at M5 completion is the hypothetical entry. The forecast is correct if signed price change at the last M1 close 60 or 240 minutes later is **greater than $0.50/oz**. The full M1 path must exist with no gap; invalid outcomes get GAP status, never winners.
8. Search space exactly 3 levels × 2 confirmations × 3 HTF gates × 4 sessions = **72 policies per horizon**, evaluated independently for BUY/SELL. Choose **one fixed joint policy per horizon on 2024**, maximizing the worse-side Wilson 95% lower bound with >=25 signals/side H1 or >=12/side H4 on 2024; freeze it and then report its 2025–2026 result. Require >=100 test events/side H1 or >=40/side H4 for an observed 60% claim. Training years 2019–2023 are diagnostics only. No target $10 search yet.

## Caveats
- Cost is hypothetical, no slippage, financing or real fills; direction accuracy alone does not prove profitability.
- PR #880 has not delivered genuine historical intraday DXY, US2Y or US10Y quotes; R6 uses **price geometry only** and makes no false macro confirmation claims.
- R4/R5 and earlier work have already examined 2025/26; this evaluation is **not a pristine program-level holdout**.
- Both sides must pass with adequate n and durability, not one 60% result from small sample.
- If R6 does not meet the gate, label as FAILED / WAIT / RESEARCH ONLY, do not push to ForexScanner or cTrader.

## Reproduce
Workflow `.github/workflows/xau-m5-mss-r6.yml`: 8 annual public M1 downloads and automated provenance; controlled causal tests; single aggregate artifact with validation ranking and every calendar year's BUY/SELL accuracy.

Note: this test is explicitly **H1/H4 directional endpoint forecasting** from an M5 entry event, NOT a claim of an actual smart-money order book or an ICT indicator's intrinsic probability.
