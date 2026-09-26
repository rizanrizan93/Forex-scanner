# EURUSD Depth V235 — Historical Transfer Benchmark 2012–2026

## Scope

V235 applies the existing XAU V225.2 causal Supply/Demand first-touch depth methodology to EURUSD without changing the geometry.

- Pair: EURUSD
- History: 2012–2026
- Source: HistData M1, normalized to UTC with the existing historical data contract
- Timeframes: H4 / H1 / M15
- Reaction definition: favorable move >= 0.50 ATR before a close beyond the distal edge
- First-touch only, causal zone availability and causal supersession
- Policy: SHADOW_ONLY
- Execution influence: false
- Execution authority: false
- LIVE execution: false
- This benchmark does **not** simulate the complete V229 4-child execution lane.

## Overall EURUSD results

| TF | Touches | Reaction >=0.50 ATR | Wilson LB 95% | Median depth | P25 | P75 | IQR | Highest hazard band | Conditional hazard |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| H4 | 4,795 | 71.95% | 70.66% | 17.07% | 5.50% | 39.05% | 33.55 pp | 00–10% | 26.28% |
| H1 | 15,079 | 72.25% | 71.53% | 19.51% | 6.78% | 43.33% | 36.55 pp | 00–10% | 22.88% |
| M15 | 52,227 | 75.15% | 74.77% | 19.51% | 6.78% | 43.24% | 36.46 pp | 00–10% | 23.41% |

Total first-touch episodes: **72,101**.

The hazard column is conditional on an episode reaching the lower boundary of the stated depth band. It is not a standalone trade win probability.

## Directional symmetry

| TF | LONG reaction | SHORT reaction | LONG median depth | SHORT median depth |
| --- | ---: | ---: | ---: | ---: |
| H4 | 71.23% | 72.65% | 16.38% | 18.11% |
| H1 | 72.57% | 71.93% | 19.19% | 19.91% |
| M15 | 75.02% | 75.27% | 19.44% | 19.64% |

LONG/SHORT behavior is notably symmetric, especially on M15.

## Era stability

| Era | Episodes | H4 reaction | H4 median / IQR | H1 reaction | H1 median / IQR | M15 reaction | M15 median / IQR |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- |
| 2012–2018 | 34,030 | 71.83% | 17.55% / 34.75 pp | 72.69% | 19.49% / 37.69 pp | 75.02% | 20.29% / 36.93 pp |
| 2019–2024 | 29,117 | 71.82% | 16.81% / 33.27 pp | 71.33% | 19.71% / 35.43 pp | 75.28% | 18.87% / 36.01 pp |
| 2025–2026 | 8,954 | 72.80% | 16.79% / 31.67 pp | 73.58% | 18.73% / 35.67 pp | 75.15% | 18.92% / 36.47 pp |

The outer-zone first-touch reaction distribution is unusually stable across the three eras. No era shows a collapse in the >=0.50 ATR reaction metric.

## EURUSD vs XAU V225.2

The comparison uses the same first-touch depth methodology.

| TF | EURUSD reaction | XAU reaction | Difference | EURUSD median depth | XAU median depth | EURUSD IQR | XAU IQR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 | 71.95% | 71.37% | +0.58 pp | 17.07% | 20.03% | 33.55 pp | 37.72 pp |
| H1 | 72.25% | 70.96% | +1.29 pp | 19.51% | 20.88% | 36.55 pp | 37.75 pp |
| M15 | 75.15% | 74.29% | +0.86 pp | 19.51% | 20.37% | 36.46 pp | 36.97 pp |

The strongest measurable stability improvement is H4: EURUSD's depth IQR is about 4.17 percentage points narrower than XAU, roughly an 11% reduction in dispersion.

The 00–10% conditional hazard is also higher for EURUSD:
- H4: 26.28% vs XAU 23.23%
- H1: 22.88% vs XAU 21.30%
- M15: 23.41% vs XAU 22.00%

## Nested hierarchy

EURUSD:
- H4 successful reactions: 3,450
- Pre-existing H1 child coverage: 44.20%
- M15 child coverage given H1 child: 41.18%
- H1 child median depth: 36.25% (P25 14.62%, P75 61.48%)
- M15 child median depth: 48.89% (P25 23.72%, P75 73.36%)

XAU is very similar:
- H1 child coverage: 45.91%
- M15 child coverage given H1: 40.87%
- H1 child median: 37.41%
- M15 child median: 46.21%

Therefore, EURUSD's advantage is mainly in the **outer first-touch depth geometry**, especially H4. Nested H1/M15 refinement is not dramatically narrower or simpler than XAU.

## Interpretation

V235 supports three conclusions:

1. The XAU Depth foundation transfers cleanly to EURUSD across 2012–2026.
2. EURUSD is modestly more statistically stable than XAU in outer first-touch depth, with the largest improvement at H4.
3. This is not yet evidence that the full EURUSD trading system is more profitable. V235 does not model V229 child entries, structural SL/TP, M5 confirmation slots, broker costs, fill behavior, or position-level PnL.

## Next research gate

The next valid test is a **full EURUSD V229-style historical execution simulation**:

- H4/H1/M15 Depth candidate generation
- L1/L2 pre-touch entries
- L3 reclaim + MSS retest
- L4 displacement + refined-pocket retest
- structural SL
- M15/H1/H4 opposing-zone targets
- transaction-cost model
- conservative intrabar ordering
- per-era PnL, expectancy R, profit factor, drawdown, hit rate, MAE/MFE
- walk-forward and perturbation checks

Until that test is complete, EURUSD remains research/shadow-only.
