# RIZAN R31.1 — XAUUSD Extended Holding Net Profit, 2012–2026

**Exploratory research: no forward verification or live promotion.**

All outcomes are hypothetical USD for fixed one troy ounce, at $2/oz assumed cost, without leverage or compounding. Later 2026 is partial.

## 24 additional holding-period and mode combinations

| TF | Hold bars | Mode | Trades | Net $/1oz | Max realized DD $/1oz | Net at $5 cost | Positive years |
|---|---:|---|---:|---:|---:|---:|---:|
| 1W | 8 | net_dd | 31 | +2,171.25 | 562.93 | +2,078.25 | 5/8 |
| 1W | 8 | max_net | 36 | +1,528.80 | 1,159.95 | +1,420.80 | 3/8 |
| 1W | 8 | profit_frequency | 36 | +1,528.80 | 1,159.95 | +1,420.80 | 3/8 |
| 1W | 4 | profit_frequency | 61 | +711.59 | 1,176.80 | +528.59 | 1/8 |
| 1W | 6 | net_dd | 26 | +709.60 | 405.68 | +631.60 | 3/8 |
| 1W | 4 | max_net | 63 | +540.44 | 1,176.80 | +351.44 | 2/8 |
| 1W | 3 | profit_frequency | 86 | +498.89 | 1,436.72 | +240.89 | 1/8 |
| 1W | 3 | max_net | 83 | +468.97 | 1,466.64 | +219.97 | 1/8 |
| 4h | 6 | max_net | 668 | +304.54 | 1,089.59 | -1,699.46 | 4/8 |
| 1D | 5 | max_net | 229 | +236.84 | 1,295.80 | -450.16 | 3/8 |
| 4h | 6 | profit_frequency | 705 | +232.54 | 1,089.59 | -1,882.46 | 3/8 |
| 4h | 4 | max_net | 539 | +211.60 | 705.04 | -1,405.40 | 3/8 |
| 4h | 4 | net_dd | 348 | +162.00 | 573.66 | -882.00 | 4/8 |
| 1D | 3 | max_net | 284 | +51.92 | 1,167.33 | -800.08 | 4/8 |
| 1D | 5 | profit_frequency | 254 | +46.15 | 1,295.80 | -715.85 | 2/8 |
| 1W | 6 | max_net | 45 | +15.71 | 885.13 | -119.29 | 1/8 |
| 1W | 6 | profit_frequency | 45 | +15.71 | 885.13 | -119.29 | 1/8 |
| 1W | 3 | net_dd | 50 | -204.61 | 1,012.51 | -354.61 | 1/8 |
| 1D | 3 | profit_frequency | 350 | -276.96 | 1,167.33 | -1,326.96 | 2/8 |
| 1D | 5 | net_dd | 106 | -466.71 | 658.37 | -784.71 | 3/8 |
| 1W | 4 | net_dd | 50 | -471.10 | 1,064.09 | -621.10 | 4/8 |
| 4h | 4 | profit_frequency | 675 | -563.53 | 1,188.95 | -2,588.53 | 3/8 |
| 4h | 6 | net_dd | 408 | -673.28 | 827.99 | -1,897.28 | 1/8 |
| 1D | 3 | net_dd | 110 | -1,193.09 | 1,348.97 | -1,523.09 | 1/8 |

## Fixed, no-refitting baseline controls

A higher raw net is not enough. In particular, W1 long-hold profits can be dominated by market-wide gold appreciation and the 2025 trend.

| TF | Hold | Best constant control | Net $/1oz |
|---|---:|---|---:|
| 1W | 3 | ema_buy | +2,621.76 |
| 1W | 4 | ema_buy | +2,825.99 |
| 1W | 6 | ema_buy | +2,703.28 |
| 1W | 8 | ema_buy | +2,436.81 |
| 1D | 3 | ema_adx_buy | +1,677.11 |
| 1D | 5 | ema_adx_buy | +2,294.64 |
| 4h | 4 | ema_adx_buy | -1,106.42 |
| 4h | 6 | ema_adx_buy | +53.66 |

## Research decision

- 1 configurations passed minimum 5 positive years, >=30 trades and net-positive at $5 cost.
- Any result selected after viewing 2025 W1 behavior is exploratory. Independent prospective testing and measured executable broker transaction costs are mandatory before considering adoption.
- Frozen V1, R28, R29, R30, ForexScanner and cTrader orders unchanged.
