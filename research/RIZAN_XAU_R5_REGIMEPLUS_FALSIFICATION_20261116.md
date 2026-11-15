# RIZAN XAU R5 RegimePlus — Post-Selection Falsification

**16 November 2026 WIB. Status: EXPERIMENTAL / NO LIVE EXECUTION.**
This document describes a positive but statistically fragile exploratory backtest, NOT a deployable strategy.

## Mechanically defined selected hypothesis

- XAUUSD, long-only trades entering 08:00–13:00 WIB after an objective 06:00–08:00 Asian opening-range breakout, with already-closed H1 EMA50/EMA200 and M15 EMA20/50 aligned upward.
- Last completed UTC daily close greater than the highest high of the PREVIOUS 60 completed UTC trading days.
- Historical publisher-lagged FRED 10Y real yield 7-day change < 0 (do NOT substitute a current revised number in the past).
- Next M5 candle open entry; structural stop beyond last six M5 lows plus ATR buffer, 2R target, maximum two-hour hold or close by 13:00 WIB.
- Starting $100, equity compounding, 1:200 reference leverage, assumed minimum 0.01 lot = 1 oz, position size discrete by lot steps, maximum 5% equity risk and 50% margin consumption.
- Simulated friction reference USD0.80/oz roundtrip, mid-price M5 OHLC, NOT broker bid/ask ticks.

## Reproduced full historical numbers

497,345 public M5 OHLC bars, 2019-01-01 23:00 UTC through **2026-01-09 21:55 UTC**, source SHA256 43c0bf9e15bc3c6b94b707112ebb7623571a7653cacfcbf4abb8cbd51247b3a5.

- $100 to **$106.50** = +6.50% total over ~7 years (NOT per year).
- Profit factor: **1.129**.
- **27** executed trades across seven years, 48.15% winning.
- Closed-trade DD **18.69%**; M5 OHLC intrabar floating drawdown approximation **21.09%**; actual tick floating DD is UNKNOWN.
- Mean profit per risk unit +0.1036R, sensitive to sample and selection.

Independent $100 restarts:
- 2019–2022: $99.38, 12 trades, PF 0.972.
- 2023–2024: $106.11, 13 trades, PF 1.280.
- 2025–Jan 9 2026: $103.92, only 2 trades, PF 2.117. This two-trade segment is not statistically informative.

## Risk of data mining and numerical uncertainty

Exploratory IID resampling of the 27 observed trade R values, 5,000 fixed-seed bootstrap draws:
- Mean R 95% percentile interval: **-0.3063R to +0.5254R**, includes zero.
- Fraction of IID bootstrap samples with positive mean R: **68.14%**. This is NOT a calibrated probability of future profit. It fails to correct for serial dependence, regime changes, selection over many previous candidates, or source revisions.

No untouched valid out-of-sample price/macro aligned dataset was used for this post-hoc filter. Classify result as **suggestive only**, not validated statistical alpha.

## Transaction cost sensitivity

| Hypothetical roundtrip cost USD/oz | Ending equity | PF | Trades |
|---|---:|---:|---:|
| 0.40 | $114.64 | 1.284 | 28 |
| 0.80 | $106.50 | 1.129 | 27 |
| 1.20 | $101.14 | 1.025 | 26 |
| 1.60 | $93.93 | 0.842 | 21 |
| 2.40 | $89.98 | 0.634 | 13 |

Changing assumed fees also changes *trade eligibility* under the risk cap, which means these are scenario outcomes, not a pure fixed-trade marginal fee estimate. The finding is economically fragile: a plausible higher spread/commission scenario can turn gains into losses.

## Adding more macro filters does NOT automatically help

With **both** negative publisher-lagged 10Y real yield and negative seven-day H.10 broad US-dollar change required, the same 60D breakout model ends at **$92.32**, PF 0.774 (18 trades). H.10 broad USD is **not ICE DXY**.

All macro inputs are sourced from a third-party dataset that claims they were publication-lagged. True original release timestamps were NOT independently verified. No claim about nowcasting future Treasury official releases, real-time DXY or gold next-15-minute probabilities is made.

## Decision and next essential validation

**NO-GO LIVE.** The first positive full-period R5 variant is low-return, highly selected, cost-sensitive, and thinly traded. It should NOT replace Frozen V1 or generate order signals.

Research code is in draft PR https://github.com/rizanrizan93/Forex-scanner/pull/854 (stacked; no production deployment).
- Price/technical module: src/fx_scanner/xau_microalpha_r5.py
- Verified R5 read-only dashboard prototype: pages/7_XAU_MicroAlpha_R5.py
- Reproducible historical macro/daily gate: scripts/research_xau_r5_daily_regime.py
- Isolated unit tests and GitHub Actions workflow passed.

Mandatory next constraints:
1. Verify FP Markets cTrader Gold symbol volume minimum/step, lot size, estimated BUY/SELL margin, commission/spread/swap before broker-executable sizing claims; 1:200 account leverage does not prove 1:200 effective symbol margin.
2. Use native bid/ask ticks (or realistically spread-simulated data) 2019–2026 and out-of-sample after source cutoff; verify quote/official macro publication timestamps.
3. Do an untouched, pre-registered holdout test and account for the multiple hypotheses already researched. No additional optimization against these same years can serve as proof.
4. Maintain hard WAIT / BLOCKED_BY_RISK / BLOCKED_BY_MARGIN controls for any potential dashboard indicator and do NOT change LIVE.
