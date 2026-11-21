# R7.4 — FINITE 9,374,976 factor+weight XAU/Fed/COT/VIX nested-grid empirical outcome
Date: 2026-11-21 WIB. Status **COMPLETE — REJECT FOR PRODUCTION**.

## What actually ran
**9,374,976 distinct predeclared parameter configurations** (390,624 nonzero 8-axis base-5 weight vectors x 4 thresholds x 2 GLOBAL/REGIME_GATED weighting policies x D1/W1/M1). The two historical 2023-price-source cohorts and eligible 2023/2024 outer folds resulted in **34,374,912 actual fold-configuration scoring evaluations** recorded across all six successful GitHub Actions jobs. This distinction prevents falsely claiming every unique configuration is a wholly independent experiment.

- Source code: `src/fx_scanner/fed_r74_finite_million_grid.py`, `src/fx_scanner/fed_r74_million_runner.py`.
- Formal design *before* search: `docs/research/R74_FINITE_9374976_GRID_PREREG_20261121.md`.
- Real-price replay source run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44846192772 (all 6/6 matrix jobs SUCCESS; each raw JSON separately archived).
- Regression: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44846263454 (6 synthetic anti-leakage and exact-count checks PASS).
- Only 2018–2024 gold and macro history imported, **2025–2026 quarantined** as already reviewed. 2023 and 2024 outer development folds were also previously explored in earlier R7/R7.3 research and are NOT an untouched future holdout.
- Source 2023: original HistData 164 daily bars vs independently recovered Dukascopy 259 daily bars. Cross-vendor switching is documented.
- Historical yield observation date, Fed effective target, CFTC reports, broker dollar CFD and VIX: **assumed availability lags and/or latest-vintage**, not original true archived historical publication+capture receipts. True CME FedWatch probabilities/FOMC surprise and licensed ICE DXY remain missing; they were **NOT** fabricated as model factors.
- Hypothetical $0.40/oz cost, **not** native FP Markets bid/ask or execution/slippage.

## Correct after assumed cost — matched same R7.4-selected decision dates
| Historical source cohort | Horizon | Selected accuracy | Correct/active | R7.2 price-only method refit on identical active dates | BUY/SELL | Wilson 95% CI | Exact paired p, UNADJUSTED |
|---|---|---:|---:|---:|---:|---:|---:|
| **Recovered Dukascopy 2023** | **D1** | **52.38%** | 55/105 | 57/105 (54.29%) | 69/36 | 42.91–61.68% | 0.7905 |
| Recovered Dukascopy 2023 | W1 | 43.94% | 29/66 | 26/66 (39.39%) | 41/25 | 32.63–55.92% | 0.6291 |
| Recovered Dukascopy 2023 | M1 | 45.45% | 5/11 | 7/11 (63.64%) | 8/3 | 21.27–71.99% | 0.5000 |
| Original **incomplete** HistData 2023 | D1 | 53.76% | 150/279 | 150/279 (53.76%) | 196/83 | 47.90–59.52% | 1.0000 |
| Original incomplete HistData 2023 | W1 | 52.38% | 22/42 | 19/42 (45.24%) | 14/28 | 37.72–66.64% | 0.6636 |
| Original incomplete HistData 2023 | M1 | 25.00% | 1/4 | 2/4 (50.00%) | 2/2 | 4.56–69.94% | 1.0000 |

P-values are NOT adjusted for repeated human research or many tested configurations; even unadjusted they do not substantiate R7.4 alpha. **One cannot compare accuracies across the two vendor cohorts as if dates were matched.** Model R7.2 is the same PRICE-ONLY METHOD **refit per past fold**, not frozen 2024 coefficients in earlier years.

### Why 80% in search is misleading
- W1 2024 repaired-source candidate chose an inner-period combination with **36/43 = 83.72%**, yet on the 2024 outer development year only **5/15 = 33.33%**, an assumed after-cost signed move of **−$11.91/oz** averaged over its 15 selected opportunities. The 2023 selected W1 combination was **24/51 = 47.06%**; weight vectors and GLOBAL/REGIME_GATED policies changed between outer folds.
- M1 selected candidates achieved **12/12 and 13/13 = 100%** during separate inner development selection, but outer outcomes were **4/9 and 1/2**, total **5/11 = 45.45%**. This is a small-sample, multiple-testing failure, not 100% predictive accuracy.
- The most promising-looking D1 2024 recovered-source candidate (weights eight axes `[0,-2,2,-2,1,1,-1,0]`, threshold 0.45, GLOBAL) generated **25/42 = 59.52%**, but the same-date price-only baseline was also **25/42 = 59.52%**, and there were **39 BUY vs only 3 SELL**. Thus it is not an independently confirmed bidirectional advantage.
- W1 results change materially depending on whether the incomplete original 2023 price source is retained or replaced, illustrating vendor/sample sensitivity rather than robust alpha.

## Candidate axes in order
1. XAU short-term momentum; 2. XAU 21-day trend; 3. XAU range+volatility; 4. Fed policy change + 2Y path *proxy*; 5. Treasury nominal/real yield changes; 6. Dukascopy Dollar Index CFD change (**not ICE DXY**); 7. CFTC managed-money gold positioning/Open Interest changes; 8. VIX risk level/change.
All raw components are normalized using earlier TRAIN years only. Missing or future time data fail closed. A regime-gated candidate uses fixed state multipliers, not validated automatic learning of actual liquidity liquidation.

## Research disposition
**Do not promote or deploy R7.4**, and DO NOT revise Frozen V1, R7.2 coefficients, ForexScanner production, or cBot accounts. Endless unbounded retesting would intensify selection bias. Required next evidence: true timestamped pre-FOMC futures/FedWatch expectations, original release and receipt timestamps, source-vendor consistency; pre-register ONE or a small number of hypotheses and shadow-validate only on genuinely NEW post-freeze market observations, followed by native broker spread/slippage/portfolio DD checks.

These are historical research calculations, not investment return or an executable order instruction.
