# RIZAN XAU MicroAlpha R4 — Liquidity/Macro Research Report

**Research status (16 Nov 2026 WIB): NO-GO FOR LIVE.**
**Instruments:** XAUUSD, $100 initial equity with compounding, leverage reference 1:200.
**Execution authority:** NONE. Frozen V1, existing cBot LIVE, bridge, workers and production ForexScanner unchanged.

## 1. Research design

R4 tests an objective, algorithmic proxy of an ICT/SMC liquidity sweep:
- M5 sweeps prior 12 or 24 completed M5 high/low, **or** the fully established 06:00–08:00 WIB Asia opening range high/low.
- Swept level is reclaimed by completed M5 candle; directional body confirms.
- Within 1–3 subsequent consecutive M5 candles, close displaces beyond the sweep candle high/low (mechanical MSS confirmation proxy).
- Enter at the **next** M5 opening price, not on the pre-confirmation sweep.
- Stop loss is beyond actual sweep wick with +0.1 ATR M5 buffer, **not arbitrarily narrowed** to fit the smallest tradable lot.
- Take profit 2R or close at 13:00 WIB, whichever happens sooner; no overlapping trades.
- Compare optional M15 EMA20/EMA50 or H1 EMA50 directional alignment.

$100 risk gate assumes **0.01 lot minimum = 1 ounce** and lot step 0.01, 100oz/lot, risk <= 5% current equity, initial margin <= 50% equity, max 0.50 lot, cost $0.80/oz roundtrip, leverage 1:200. Risk and margin inputs are **hypothetical** pending direct FP Markets cTrader symbol verification.

## 2. Data

497,345 historical M5 public **mid OHLC** bars, **2019-01-01 23:00 UTC through 2026-01-09 21:55 UTC**.
- Dataset: Hugging Face vichetkao/xauusd_dataset_2026, pinned reference M5 Parquet.
- SHA256: 43c0bf9e15bc3c6b94b707112ebb7623571a7653cacfcbf4abb8cbd51247b3a5
- No duplicate timestamps, no impossible OHLC bars according to basic integrity checks, max 5-minute close-to-close move 1.964%.
- Missing spread, bid/ask, FP-specific execution, actual margin/stopout levels, commissions, swap and fill delays. Floating drawdown is **an OHLC excursion estimate**.
- Chronological diagnostic windows: 2019–2022, 2023–2024 and 2025–09 Jan 2026. These are diagnostics, **not genuine untouched out-of-sample after selecting research designs**.
- Publisher-lagged FRED/H.10 macro changes are not independently validated point-in-time intraday quotes, and broad US dollar is **NOT ICE DXY**. No calibrated macro forecast accuracy claimed.

## 3. Full continuous-compounding results

| Model | $100 ending | Profit factor | Closed DD | Executed trades |
|--|--:|--:|--:|--:|
| Sweep Asia 06–08 opening range | $19.66 | 0.148 | 81.67% | 72 |
| Sweep Asia + M15 trend | $22.36 | 0.141 | 78.23% | 71 |
| Rolling 12 M5 sweep + MSS | $19.76 | 0.030 | 80.24% | 54 |
| Rolling 12 + M15 | $19.61 | 0.071 | 80.39% | 62 |
| Rolling 24 + H1 | $21.90 | 0.128 | 78.10% | 68 |
| Opening-range + real yield + broad USD | $23.83 | 0.127 | 76.17% | 67 |
| Opening-range + real/nominal yield + broad USD | $23.29 | 0.112 | 76.75% | 64 |

All full-period models are materially unprofitable.

## 4. Large-sample drawdown and discrete-lot constraint

R4 opening-range model produced 4,724 raw technical signals but only 72 executed trades in the compounded whole-period replay; **4,495 signal opportunities were blocked by the 5% risk gate**. As equity fell after early losses, the account ceased to be able to trade at the assumed 0.01-lot minimum. This *trade affordability shutdown* is a substantial feature of any $100 XAU research, not a backtester defect to override.

Using 0.01 lot at a 100oz/lot contract, the nominal exposure is 1 oz and $1 XAU movement is about $1 P/L before costs. With $100 equity, 5% risk ceiling and an assumed roundtrip cost $0.80 per oz, the maximum stop width is roughly $4.20 per oz. At 2% risk, only $1.20 remains. Margin used does not equal total stop-loss risk; nominal leverage increases purchasing power, **not risk-adjusted alpha**.

## 5. Regime result and overfitting caution

Only the **independently restarted** 2025–09 Jan 2026 window showed modest positive results for the publisher-lagged macro proxies:
- Opening range + real yield + USD broad: **$100 to $119.35**, PF 1.203, DD 19.79% (45 trades).
- Opening range + real/nominal yield + USD broad: **$100 to $122.56**, PF 1.278, DD 18.52% (40 trades).

But 2019–2022 and 2023–2024 windows had severe losses for these same variants (for example real-yield+USD ending $26.27 and $34.04 when restarting each diagnostic window at $100). The recent positive slice is not proof of a forecastable regime; multiple hypothesis testing and hindsight selection apply. Full compounded portfolios never recovered from early losses.

## 6. Transaction friction stress requires careful interpretation

Opening-range ending equity under roundtrip friction assumptions: $0.40/oz -> $14.05; $0.80 -> $19.66; $1.50 -> $32.86; $3.00 -> $60.91. **This reversed cost/return relation is NOT evidence higher friction improves profits**; higher friction causes the risk/lot constraint to reject more trades, preventing more of this loss-making system from trading. The proper comparison must hold trade eligibility, risk and fills constant before interpreting trading-cost sensitivity.

## 7. Software deliverables

- Pure R4 strategy module: src/fx_scanner/xau_microalpha_r4.py
- Closed-M5, leak-free tests: tests/test_xau_microalpha_r4.py
- Reproducible SHA-pinned multi-year runner: scripts/research_xau_microalpha_r4_multiyear.py
- CI workflow: .github/workflows/xau-microalpha-r4-research.yml
- Read-only dashboard research tab (draft PR only): pages/6_XAU_MicroAlpha_R4.py
- Comprehensive JSON evidence produced as GitHub Actions workflow artifact.

Macro screen in the new page reads ForexScanner's existing **V400 validated context** and shows **WAIT** unless quote timestamps, independent FX/rates sources, published macro quality state and intraday alignment all pass. **Current macro is never injected into historical 2019–2026 prices.** No automatic execution.

## 8. Decision

**NO-GO for LIVE**. Neither R3 nor R4 reached positive whole-period risk-adjusted expectancy, even before realistic FP Markets tick bid/ask costs and execution uncertainty. Do not merge into signal-to-order production or modify Frozen V1.

## 9. Proposed next research decision point

The responsible next step is to audit native FP Markets cTrader XAU symbol (VolumeInUnitsMin/Step, LotSize, PipValue, GetEstimatedMargin), then use 2019–2026 tick bid/ask to validate a genuinely different source of alpha rather than retune a losing system until it looks good. If broker minimum volume prevents a structural stop fitting a $100 risk budget, correctly output BLOCKED_BY_RISK rather than sending a risky live order. Consider 1,000-unit FX instruments or a compatible genuine micro-contract for risk sizing only if brokerage permissions and strategy-specific evidence support it.

**No untested daily macro number is a direct entry trigger.**
