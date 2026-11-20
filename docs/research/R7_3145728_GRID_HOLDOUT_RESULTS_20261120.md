# R7 empirical calibration — 3,145,728 grid evaluations (20 Nov 2026)

**STATUS: REJECTED FOR PRODUCTION / NO EVIDENCE OF PREDICTIVE ALPHA.**

Verified Actions result: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44761408020
Exact artifact: r7-resumed-million-factor-results, internally containing r7-million-grid-results.json.
Action regression gate: **17 passed**. 8 factors x four signed grid weights
(-2,-1,+1,+2) = 4^8 = 65,536 vectors; 16 absolute-score thresholds
0 to 0.75 by 0.05 = **1,048,576 combinations per tested horizon**.
3 horizons tested (D1, W1, M1): **3,145,728 evaluated configurations**.
Y1 cancelled on evidence sufficiency: only one independently spaced
validation and one heldout yearly outcome.

## Data and causal caveats
Actual secondary-market HistData XAU M1 2018–20 Nov 2026, rolled
into 2,148 accepted UTC-session daily OHLC observations.
**2023 only 164 admitted days**; March–July severely undercovered.
A session required at least 1,000 real M1 quotes, tolerated the
ordinary spot-gold daily maintenance break up to two hours, did not
forward-fill missing price and excluded horizon-crossing major gaps.

Four actual *archived* FRED series from
research/zone_rebound/fixed10_evidence/fred_macro_snapshot.csv.gz:
DFII10 real 10Y, DGS2 nominal 2Y, DGS10 nominal 10Y, DTWEXBGS
broad trade-weighted USD (**not ICE DXY**). Verified source SHA256:
7b60c4e998acac0b061497162696155df34f8049179045343acb85e5a717cf2f.
Rates assumed delayed 3 US business days; broad USD delayed 10
US business days. Actual source publication timestamps / historical
FRED vintages are unavailable. **This does not qualify as causal
point-in-time macro forecasting evidence.** The DTWEXBGS snapshot
ends 2026-03-31, so valid 2026 macro-factor holdout does NOT run
through Nov 2026.

Four remaining features are strictly price-derived: XAU daily range
5-session mean, momentum 5-session, momentum 21-session,
realized volatility 21-session. Missing Fed policy surprise, intraday
COMEX flow, COT, ETF, physical gold purchases, geopolitics and
observed futures OI; no causal claim about any missing factor.

Training normalisation: 2019-2022 only; selection 2023-2024 only.
Holdout: 2025 to latest available macro date (part of 2026),
evaluated exactly once after the model choice; no selection using
holdout outcomes. Horizon outcomes use next valid session open to
future h-th close and subtract *assumed* $0.40/oz roundtrip spread.
This is NOT FP Markets broker spread, execution, slippage, margin
or risk-of-ruin simulation.

## Final holdout vs development selection

| Horizon | Grid tried | Dev correct/n | Holdout correct/n | Holdout BUY | Holdout SELL | Selected coverage |
|---|---:|---:|---:|---:|---:|---:|
| D1 (1 session) | 1,048,576 | 73/122 = 59.84% | 39/88 = **44.32%** | 13/18 = 72.22% | 26/70 = 37.14% | 26.04% |
| W1 (5 sessions) | 1,048,576 | 19/25 = 76.00% | 10/23 = **43.48%** | 5/9 = 55.56% | 5/14 = 35.71% | 34.33% |
| M1 (21 sessions) | 1,048,576 | 11/11 = 100% | 4/7 = **57.14%** | 1/1 | 3/6 | 43.75% |
| Y1 (252 sessions) | 0 | insufficient | insufficient | — | — | — |

Unadjusted Wilson 95% intervals for *holdout* correct direction:
D1 approx 34.4-54.7%; W1 approx 25.6-63.2%;
M1 approx 25.0-84.2%. Because 1M selection trials
were evaluated for each horizon, development accuracies are
strongly subject to multiple-comparison selection bias.
M1 fails two-sided holdout evidence sufficiency; Y1 never ran.

## Learned-on-development relative signed weights (NOT stable causal betas)

D1 selected weights:
- real10: -0.20; nominal2: +0.20; nominal10: -0.10;
  broad USD: +0.10; gold range5 +0.10; gold mom5 +0.10;
  gold mom21 -0.10; gold vol21 -0.10.
- Absolute grouping: Treasury 50%, broad USD 10%, gold
  momentum/volatility 40%.

W1 selected absolute grouping: Treasury 50%, broad USD 8.33%,
price-derived 41.67%.

M1 selected absolute grouping: Treasury 41.67%, broad USD 16.67%,
price-derived 41.67%.

These weights did NOT generalize well. Signs of supposedly
fundamental drivers differ by horizon and are likely unstable
under multicollinearity, 2023 missing data and regime shifts.
**Do not install them as R7 production coefficients or present
them as a calibrated probability.**

## Control baselines (different coverage; NOT matched-signal comparison)

Always-BUY on all evaluable holdout dates:
D1 58.28% (338 total), W1 65.67% (67 total),
M1 81.25% (16 total). These are NOT same
selected subset as the new model, so no strict causal
head-to-head superiority can be inferred; nevertheless,
the model has not shown a compelling edge over simple trends.
Momentum-5 baseline on all dates: D1 51.18%,
W1 49.25%, M1 56.25%.

## Research decision
**Do not merge/promote R7 to live trading.**
Keep original Frozen V1/cBots unchanged.
Next: a) repair full-year 2023 history / cross-check independent
vendor; b) obtain true publication/vintage-tagged yield and DXY,
event surprise, COMEX futures flow and ETF sources; c) fit
regularized macro weights with purged nested walk-forward,
block bootstrap, regime stability and held-out *new* years,
d) require BOTH BUY and SELL genuine sample coverage,
out-of-sample improvement over same-date baseline, and
economically positive after-cost expectancy before any forecast
confidence/promotion. The 2025-2026 holdout was already examined;
it must NEVER be reused as a new untouched holdout for another
reoptimised R7 release.
