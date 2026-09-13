# Rejected FX Alternative Strategy Findings — 2026-09-13

Research only. `execution_influence=false` and `promotion_authority=false`. No result in this document grants DEMO or LIVE order authority.

This second-stage tournament was frozen before execution and intentionally changed strategy/exit architecture rather than exhaustively tuning parameters. Public data are Dukascopy Bank BID H1 from 2012-01-01 through 2026-09-01. The candidate family included D1 TSMOM 252/120 with ATR Chandelier exits, D1 Donchian100 with Chandelier exits, H4 Donchian40 with Chandelier exits, H4 Z2 mean reversion, and a pair-agnostic adaptive H4 regime switch. Costs are pair-specific; same-bar ambiguity is `STOP_FIRST`; four multi-year eras and moving-block bootstrap are evaluated.

| Pair | Second-stage champion | Status | Stress pips | Trades | Stress Exp R | PF | Net R | Max DD R | + eras | 95% CI low | Recent Exp | Recent PF | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| EURJPY | `D1_TSMOM_252_CHANDELIER3` | WATCH | 2.5 | 206 | +0.1274 | 1.294 | +26.25 | 12.72 | 4/4 | -0.0434 | +0.1727 | 1.478 | cross-feed candidate |
| EURAUD | `D1_DONCHIAN100_CHANDELIER3` | WATCH | 3.5 | 62 | +0.0229 | 1.051 | +1.42 | 10.16 | 2/4 | -0.2455 | +0.7533 | 2.903 | cross-feed candidate; recent sample only 8 trades |
| GBPAUD | `H4_MEAN_REVERT_Z2_TO_SMA20` | WATCH | 4.0 | 92 | +0.0888 | 1.164 | +8.17 | 10.67 | 3/4 | -0.1302 | +0.1678 | 1.315 | original winner already contradicted by cTrader |
| EURCHF | `D1_TSMOM_252_CHANDELIER3` | REJECT | 2.5 | 185 | +0.2880 | 1.557 | +53.29 | 14.85 | 3/4 | -0.1893 | -0.2205 | 0.577 | historical edge decayed in current regime |
| NZDUSD | `H4_MEAN_REVERT_Z2_TO_SMA20` | REJECT | 2.0 | 77 | -0.0770 | 0.861 | -5.93 | 9.86 | 1/4 | -0.2801 | -0.2076 | 0.651 | reject |
| USDCHF | `H4_MEAN_REVERT_Z2_TO_SMA20` | REJECT | 2.0 | 82 | -0.0407 | 0.923 | -3.34 | 13.36 | 2/4 | -0.3006 | +0.4147 | 2.353 | recent rebound does not overcome negative full-history edge |
| EURGBP | `D1_TSMOM_252_CHANDELIER3` | REJECT | 2.0 | 214 | -0.0029 | 0.993 | -0.63 | 21.57 | 1/4 | -0.1422 | -0.1235 | 0.726 | reject |

## Key findings

`EURJPY D1_TSMOM_252_CHANDELIER3` is the strongest genuinely new second-stage candidate: positive stress expectancy, PF 1.294, +26.25R, and all four eras positive. It is still only WATCH because the moving-block bootstrap lower bound remains slightly negative at -0.0434R.

`EURAUD D1_DONCHIAN100_CHANDELIER3` improved from first-stage REJECT to WATCH, but its full-history edge is small and its very strong 2024-2026 result is based on only eight recent trades. It therefore requires broker-feed confirmation before any forward shadow collection.

For `GBPAUD`, the original H4 mean-reversion champion remains attractive on Dukascopy but already failed the independent cTrader replay. The appropriate next candidate is therefore the alternative `D1_DONCHIAN100_CHANDELIER3`, which also achieved WATCH in this second stage with 64 trades, +0.0506R stress expectancy, PF 1.104, +3.24R net, and recent expectancy +0.3012R / PF 1.658. It must be tested independently on cTrader before any forward collection.

`EURCHF` is a useful example of regime decay: its long-history TSMOM252 result is strong, but 2024-2026 is negative. It remains REJECT. `NZDUSD`, `USDCHF`, and `EURGBP` remain rejected after the alternative/adaptive tournament.

## Next gate

Only three new candidates advance to broker-native read-only cTrader cross-feed testing: `EURJPY D1_TSMOM_252_CHANDELIER3`, `EURAUD D1_DONCHIAN100_CHANDELIER3`, and the alternative `GBPAUD D1_DONCHIAN100_CHANDELIER3`. Cross-feed support still does not grant execution authority; a supported pair must first collect prospective DEMO shadow evidence with `execution_eligible=false`, `execution_influence=false`, and `promotion_authority=false`.
