# cTrader WATCH Cross-Feed Findings — 2026-09-13

Research / DEMO evidence only. `execution_influence=false`; no row in this document grants order authority or LIVE permission.

The public-history WATCH champions were replayed against broker-native cTrader DEMO trendbars using their frozen signal rules, conservative `STOP_FIRST` same-bar handling, and the same pair-specific stress-friction assumptions used in the Dukascopy research tournament.

| Pair | Frozen strategy | Broker bars | Trades | Stress cost | Exp R | PF | Net R | Max DD R | Cross-feed decision | Next state |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| AUDJPY | `H4_DONCHIAN40_ADX20` | 5000 H4 | 66 | 3.0 pips | +0.1868 | 1.318 | +12.33 | 6.39 | BROKER_FEED_SUPPORT | forward shadow evidence |
| GBPJPY | `D1_TSMOM_60_200` | 1400 D1 | 67 | 3.5 pips | +0.0602 | 1.106 | +4.03 | 9.32 | BROKER_FEED_SUPPORT | forward shadow evidence |
| CADJPY | `D1_TSMOM_120_200` | 1400 D1 | 68 | 3.0 pips | +0.0319 | 1.058 | +2.17 | 7.46 | BROKER_FEED_SUPPORT | forward shadow evidence |
| USDCAD | `H4_DONCHIAN40_ADX20` | 5000 H4 | 94 | 2.0 pips | +0.0101 | 1.016 | +0.95 | 6.72 | BROKER_FEED_SUPPORT (marginal) | forward shadow evidence, higher scrutiny |
| GBPAUD | `H4_MEAN_REVERT_Z2_TO_SMA20` | 5000 H4 | 16 | 4.0 pips | -0.1974 | 0.702 | -3.16 | 5.78 | BROKER_FEED_CONTRADICTS | reject / no forward promotion |

## Interpretation

AUDJPY is the strongest broker-feed confirmation in this batch and is materially stronger on cTrader than its public-history WATCH score. GBPJPY also reproduces a positive edge close to its recent public-history reference. CADJPY is positive but modest. USDCAD is technically positive on the broker feed but its margin is thin enough that forward evidence should be treated as a falsification test rather than a promotion presumption. GBPAUD failed the independent broker-feed check despite its favorable Dukascopy history and therefore remains rejected.

## Forward evidence policy

AUDJPY, GBPJPY, CADJPY, and USDCAD may collect non-authoritative forward shadow evaluations. The collectors must preserve exact strategy identity, closed-bar causality, deduplication, DEMO-only authentication, durable Supabase evidence, `execution_eligible=false`, `execution_influence=false`, and `promotion_authority=false`. No strategy is automatically promoted from these cross-feed results. A later promotion decision requires sufficient prospective samples and explicit evaluation of expectancy, profit factor, drawdown, data integrity, and stability.
