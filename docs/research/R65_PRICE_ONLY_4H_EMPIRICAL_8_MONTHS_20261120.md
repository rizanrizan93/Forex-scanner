# R6.5 — Empirical XAU 4-hour price-only pilot, 20 Nov 2026

**Result: DOES NOT VALIDATE R6.5 or 80% BUY/SELL accuracy.**
Research PR #900, no LIVE order authority, no Frozen V1 changes.

GitHub Actions run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44747561855
State: **success** for baseline unit tests and eight publicly downloaded
HistData XAUUSD M1 sampled months. All eight JSON artifacts retain
source timestamps, SHA256 of normalized inputs and per-side outcomes.

Period: **one selected month per year 2019-2026**, not full eight-year
continuous coverage. Total 349,594 historical M1 candles examined.
Closed M1 to M5/M15/H1/H4; existing R6 EMA20 bias (H1/M15 agreement,
H4 cannot oppose), one candidate at most every 48 M5 bars. Compare
next M5 open with 48th completed M5 close. Missing bars/candle gaps
are skipped. Cost scenarios: roundtrip spreads $0, $0.40 and $1.00
per ounce. **No real FP Markets fills or costs**.

## Findings at assumed $0.40/oz spread

| Month | Baseline n | Baseline correct | Guarded n | Guarded correct |
|---|---:|---:|---:|---:|
| 2019-06 | 57 | 50.88% | 35 | 51.43% |
| 2020-03 | 52 | 48.08% | 31 | 45.16% |
| 2021-06 | 60 | 48.33% | 37 | 51.35% |
| 2022-09 | 67 | 52.24% | 36 | 55.56% |
| 2023-03 | 14 | 57.14% | 7 | 85.71% |
| 2024-11 | 60 | 55.00% | 42 | 50.00% |
| 2025-01 | 70 | 55.71% | 43 | 55.81% |
| 2026-03 | 69 | 47.83% | 42 | 45.24% |
| **All** | **449** | **231/449 = 51.45%** | **273** | **141/273 = 51.65%** |

- 176/449 = 39.20% candidates vetoed, including **90 actually correct**
  and **86 incorrect** according to the 4h horizon label.
- 120/176 vetoes due to three-closed-M5 POST_STRESS_COOLDOWN.
- BUY baseline 120/230 (52.17%), guarded 81/149 (54.36%).
- SELL baseline 111/219 (50.68%), guarded 60/124 (48.39%).
- Wilson 95% interval: baseline 46.83-56.04%; guarded
  45.74-57.51%. Sample variation is large.
- After assumed $0.40 spread, average price-point return:
  baseline +$1.081/oz, guarded +$0.243/oz. This is **not**
  broker-executable PnL.
- At assumed $1/oz spread: baseline 46.33% direction wins,
  guarded 45.42%; mean guarded net move **-$0.357/oz**.

**Conclusion:** Current unconditional M5 liquidity veto has no
convincing 4-hour directional accuracy uplift; it removes almost
as many correct calls as incorrect calls and reduces conditional
price-point expectancy in this sample. The 85.71% for March 2023
is only six wins out of seven; not a validated 80% model.

Critical scope limitations: **technical price-only proxy**. No matched
point-in-time 2019-2026 US2Y/US10Y, DXY, OIS, Fed release,
news calendar or full R6.5 decision snapshots; no liquidation
order-flow attribution, no real FP Markets bid/ask fills,
slippage, commission or position/risk simulation. Eight months
were selected prior to inspecting their results, but are not a
representative or untouched multi-year validation.

Next research should pre-register competing liquidity admission
rules (e.g. zero- to three-bar cooldown, distinguish displacement
continuation from sweep reversal), obtain historical source
capture times, and test full months/years with untouched holdout
and forward shadow. **Do not merge this as validated alpha or
enable automated trading.**
