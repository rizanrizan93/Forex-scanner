# RIZAN R31 / R31B — High-Trade-Count Precision Audit (2012–2026)
**Date:** 2026-11-23. **Scope:** independent XAUUSD H1, H4, D1, W1 research. **Mode:** READ-ONLY.

## Source and verification
- R31 GitHub Actions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45196366454 — 34/34 success, 33,554,432 parameter evaluations verified across 32 shards. Aggregate artifact: `r31-verified-high-coverage-precision-2012-2026`.
- R31B GitHub Actions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45198209398 — 34/34 success, another **33,554,432 re-screenings of the SAME parameter space**, not new independent model families or holdout evidence. Aggregate artifact: `r31b-verified-high-frequency-precision-ranking`.
- Unique parameter universe: **256 direction variations × 4,096 zone filters × 8 exit policies × 4 source timeframes = 33,554,432 configurations**. Combined screening evaluations R31+R31B = 67,108,864, not 67M different strategies.
- H1/H4: verified session-filtered Dukascopy BID H1 and derived H4 (2012–2026). D1/W1: earlier HistData daily archive. Cross-provider broker parity is **not** proven.
- All entry setups: completed source-TF displacement, zone retest and later closed-candle rejection, same-TF direction vote, next-candle-open entry, pessimistic stop-first if target and stop touch one OHLC bar. Cannot prove M1/M5 intrabar execution sequence.
- Model selection: training screen 2012–2020; validation 2021–2023; retrospective evaluation 2024–2026 is **not pristine**, as prior experiments already studied it.
- Candidate eligibility gate: validation win rate >=55% (volume tier) or >=60% (precision tier), **PF >=1.12**, positive after-cost expectancy, no-overlap trades, >=2 positive validation calendar years, minimum trade count per timeframe. Cost $0.70/oz plus $0.80/oz stress is illustrative, not FP Markets realized fee.

## Findings
| TF | R31 strict selection | R31B denser validation selection | Conclusion |
|---|---|---|---|
| H1 | 0 pass | 0 pass | High volume still loses money after modeled stop/cost. |
| H4 | 0 pass | 28 stored passing configurations (not independent; multiple identical signal signatures) | Retrospective deterioration, **no robust promotion**. |
| D1 | 0 pass | 0 pass | Samples small; positive-looking test cases fail validation. |
| W1 | 0 pass | 0 pass | Too few valid weekly retest events for confident frequency conclusions. |

### H1 high-frequency trap
- Largest R31B validation volume: **913 trades**, 54.11% wins, PF **0.639**, net **−$929.98/oz**.
- A candidate reaching the 55% win floor: **760 validation trades**, 55.00% wins, PF **0.644**, net **−$733.99/oz**. Its retrospective test: 766 trades, 61.23% wins, PF **0.969**, net **−$146.20/oz**. High hit rate alone is not enough.
- R30 earlier selected benchmark: 87 retrospective H1 trades, 55.17% wins, PF 1.50, yet selection-period expectancy negative. Neither R30 nor R31B proves robust tradeable alpha.

### H4 candidate (model 26, zone config 140, 0.60R, hold 8 H4 candles)
| Measure | Validation 2021–2023 | Retrospective 2024–2026 |
|---|---:|---:|
| Nonoverlap trades | **82** | **86** |
| Win rate | **63.4146%** | **56.9767%** |
| PF | **1.13234** | **0.67280** |
| Net USD/oz after assumed costs | **+57.82717** | **−596.91500** |
| Extra $0.80/oz cost stress net | — | **−665.71500** |

Retrospective H4 annual net: 2024 **−$28.28633/oz**, 2025 **−$74.35611/oz**, 2026 **−$494.27256/oz**. H4 has 11 distinct stored winning-signal signatures in the archived shard toplists; all of these exhibit negative retrospective net. Thus the validated candidate is NOT stable OOS. Do not freeze this family.

### D1 and W1
- D1 sampled candidate: 12 validation trades, 58.33% wins, PF 0.855, net −$21.06/oz; 10 retrospective trades, 70% wins, PF 1.327, net +$57.20/oz. Selection-period failure and n=10 make retrospective success unreliable.
- W1: 77 zone-retest events across 2012–2026; no eligible candidate. Report `NO_VALIDATED_PASS`, never extrapolate a high-frequency win rate from sparse weekly samples.

## Decision and next research
**NO PROMOTION.** Do not modify `main` ForexScanner manual SMC panel's frozen candidate selectors, Frozen V1, live cBots, broker orders or portfolio execution as a result of this research.

The next materially different hypothesis should be verified on **historical signals from the actual frozen R25/R11/R29.2/R18/R27/R24 model heads** (with independent point-in-time parity), paired with **native M1/M5 zone touch and trigger sequences** from the original data source. Optimize **unique trades per year** subject to forward PF, expectancy, annual consistency, cost-stress and no overlapping positions, and require a new forward shadow period before promotion. Repeating 33M variants of the same OHLC zone hypothesis will not manufacture robust edge.
