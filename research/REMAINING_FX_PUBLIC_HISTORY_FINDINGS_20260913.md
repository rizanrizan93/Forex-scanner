# Remaining FX Public-History Findings — 2026-09-13

Research only. `execution_influence=false`. No result in this report grants DEMO or LIVE order authority.

Source: Dukascopy Bank public BID H1, 2012-01-01 through 2026-09-01. Same-bar ambiguity is STOP_FIRST. Each pair uses a small frozen six-family tournament rather than exhaustive parameter optimization. Stress friction is pair-specific; moving-block bootstrap and four multi-year eras are evaluated.

| Pair | Champion | Status | Stress pips | Trades | Exp R | PF | Net R | Max DD R | + eras | 95% CI low | Recent Exp | Recent PF |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GBPAUD | `H4_MEAN_REVERT_Z2_TO_SMA20` | WATCH | 4.0 | 92 | +0.0888 | 1.164 | +8.17 | 10.67 | 3/4 | -0.1302 | +0.1678 | 1.315 |
| AUDJPY | `H4_DONCHIAN40_ADX20` | WATCH | 3.0 | 435 | +0.0668 | 1.106 | +29.06 | 16.37 | 3/4 | -0.0759 | +0.0215 | 1.033 |
| GBPJPY | `D1_TSMOM_60_200` | WATCH | 3.5 | 261 | +0.0255 | 1.044 | +6.67 | 25.24 | 2/4 | -0.1387 | +0.0616 | 1.115 |
| USDCAD | `H4_DONCHIAN40_ADX20` | WATCH | 2.0 | 431 | +0.0179 | 1.028 | +7.70 | 24.88 | 3/4 | -0.1172 | +0.0765 | 1.121 |
| CADJPY | `D1_TSMOM_120_200` | WATCH | 3.0 | 256 | +0.0002 | 1.000 | +0.05 | 22.33 | 2/4 | -0.1508 | +0.0420 | 1.083 |
| EURAUD | `D1_DONCHIAN55_200` | REJECT | 3.5 | 98 | +0.1164 | 1.218 | +11.40 | 9.33 | 2/4 | -0.1217 | -0.1105 | 0.825 |
| NZDUSD | `H4_MEAN_REVERT_Z175_TO_SMA20` | REJECT | 2.0 | 54 | +0.0082 | 1.016 | +0.44 | 6.22 | 1/4 | -0.2452 | -0.0686 | 0.859 |
| USDCHF | `D1_DONCHIAN55_200` | REJECT | 2.0 | 98 | -0.0052 | 0.991 | -0.51 | 8.06 | 1/4 | -0.2098 | -0.2059 | 0.680 |
| EURJPY | `D1_TSMOM_60_200` | REJECT | 2.5 | 263 | -0.0116 | 0.980 | -3.06 | 23.26 | 3/4 | -0.1913 | +0.0889 | 1.169 |
| EURCHF | `H4_MEAN_REVERT_Z175_TO_SMA20` | REJECT | 2.5 | 71 | -0.0715 | 0.867 | -5.08 | 19.50 | 2/4 | -0.3474 | -0.3451 | 0.480 |
| EURGBP | `H4_MEAN_REVERT_Z175_TO_SMA20` | REJECT | 2.0 | 54 | -0.0902 | 0.858 | -4.87 | 10.27 | 1/4 | -0.4161 | -0.6314 | 0.203 |

## Decision

Strong research pass: none.
WATCH: GBPAUD `H4_MEAN_REVERT_Z2_TO_SMA20`, AUDJPY `H4_DONCHIAN40_ADX20`, GBPJPY `D1_TSMOM_60_200`, USDCAD `H4_DONCHIAN40_ADX20`, CADJPY `D1_TSMOM_120_200`
REJECT in this frozen family search: EURAUD, NZDUSD, USDCHF, EURJPY, EURCHF, EURGBP.

A WATCH result is not automatically promotion-eligible. Broker-feed cross-check and forward DEMO evidence remain required before any execution authority change.
