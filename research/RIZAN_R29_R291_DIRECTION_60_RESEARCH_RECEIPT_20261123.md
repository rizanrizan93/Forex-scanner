# RIZAN R29 → R29.1 — Independent BUY/SELL Close-to-Close Direction Research

Research receipt date: 2026-11-23 WIB. **Research only. No live model replacement, orders, Frozen V1/cBot changes.**

## Reproducible GitHub Actions evidence

- R29 baseline: [run 45165027692](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45165027692) — contract and H1/H4/D1/W1 historical jobs all **success**.
- R29.1 liquidity/structure-event challenger: [run 45165585427](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45165585427) — causal prefix tests and H1/H4/D1/W1 jobs all **success**.
- Historical input: R10 run 44901264975 (H1/H4 2019–2026), R9.8 run 44886465487 (D1/W1 2012–2026).
- Code: `scripts/r29_direction60_walkforward.py`, `scripts/r291_event_structure_direction.py`.
- Complete yearly, side-specific receipts (accuracy, support, coverage, Wilson, gross/net cost): GitHub Actions artifacts `r29-direction-*` and `r291-event-*`.

All figures are **historical reused evaluation**, not untouched forward results. Evaluation 2024–2026 H1/H4; 2023–2026 D1/W1. Independent BUY and SELL heads are trained on earlier data; model and filter selected on preceding-year validation only; next-candle labels mature before period boundaries. Sides conflict ⇒ WAIT. M1/M5 execution and intraday spread/slippage **were not** backtested.

## Actual findings

| TF | R29 BUY | R29 SELL | R29.1 BUY | R29.1 SELL | R29.1 combined coverage | R29.1 passes all gates |
|---|---:|---:|---:|---:|---:|---|
| H1 | 657/1236 = 53.16% | 419/794 = 52.77% | 1153/2155 = 53.50% | 1039/2117 = 49.08% | 26.34% | **NO** |
| H4 | 199/365 = 54.52% | 193/410 = 47.07% | 199/332 = **59.94%** | 224/415 = 53.98% | 18.23% | **NO** |
| D1 | 155/312 = 49.68% | 81/181 = 44.75% | 108/207 = 52.17% | 72/151 = 47.68% | 41.20% | **NO** |
| W1 | 31/67 = 46.27% | 18/38 = 47.37% | 18/31 = 58.06% | 23/50 = 46.00% | 45.51% | **NO** |

R29.1 H4 BUY assumed $0.70/oz cost: mean close-to-close net **+$1.4751/oz** on n332; Wilson lower95 ~54.58%, **not statistically established above 60%**.

R29.1 H4 BUY annual:
- 2024: **83/143 = 58.04%**, net assumed +$0.7186/oz.
- 2025: **108/176 = 61.36%**, net assumed +$2.4516/oz.
- 2026: **8/13 = 61.54%**, net assumed **−$3.4232/oz** (insufficient support).
- R29.1 H4 SELL 2026: 75/123 = 60.98%, yet mean assumed net **−$4.5492/oz**. Direction correctness ≠ realized trading edge.

No side-complete timeframe passes the predeclared gates: each side >60% pooled, minimum total n, ≥2 years with adequate support, positive mean close-to-close net after assumed $0.70/oz, and combined coverage ≥4%.

## Interpretation — what NOT to do

1. **Do not** lift H4 BUY 59.94% into a "60% strategy"; it is below the target and not forward validated.
2. **Do not** lower thresholds until 2026 looks profitable or repeatedly pick the top yearly accuracy; 2024–2026 were examined in R1–R29 and R29.1 is adaptive.
3. Do not combine different historical R25/R11/R27/R28.1 selected winners into a combined claimed accuracy unless replayed on the same candles with conflict resolution.
4. No trading authority: existing ForexScanner H1/H4 R25/R11 and R28.1 SHADOW remain untouched.

## Next predeclared research stage

Priority H4 → H1 → D1:

- **H4:** Test liquidity-event continuation and reversal as separate *predefined* strata, with later blind forward evidence; investigate why 2026 BUY event coverage collapses to n13 and why 2026 SELL direction ~61% has negative average close-to-close magnitude. Do not optimize threshold to the examined year.
- **H1:** Explore session-specific conditional hypotheses (Asia/London/NY), asymmetric movement size targets, and labeled no-trade windows; retain identical close-to-next-close target for headline comparability. Decompose directional correctness from profit after spread.
- **D1:** Expand only using verified point-in-time DXY, U.S. 2Y/10Y, real yields, scheduled FOMC/CPI/NFP surprises and release timestamps. Never use revised macro releases or pre-publication data as predictors. Audit publication lags first; don't silently backfill.
- Evaluate same-candle matched samples, precision vs coverage curves, calibration/Brier, lower Wilson bound, annual stability, mean gross and cost-adjusted USD/oz, tail loss, MFE and MAE. Preserve positive cost scenario as hypothetical until true FP Markets spread/slippage is obtained.
- Reserve fresh, subsequently arriving candles as **prospective forward test**. No threshold re-selection on that set. The historical target is not yet met.

## Version contracts

- R29: `R29_V1_PREDECLARED_20261123`
- R29.1: `R29_1_EVENT_STRUCTURE_PREDECLARED_20261123`
- Immutable research branches: `research/r29-direction60-walkforward-20261123`, `research/r291-event-structure-direction-20261123`.
