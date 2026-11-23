# RIZAN R33 — D1 Add-on During W1 EMA Idle Windows (2012–2026)

**Research-only, no live trading model promoted.**

Original primary W1 EMA BUY 4-week: **75 trades, +$2,825.99 per fixed troy ounce** at hypothetical $2/oz round-trip cost, 6/8 positive test years.

R33 D1 candidates are frozen prior-year R32 D1 signals; evaluation 2019–2026, 2026 incomplete. Extra D1 trades only when W1 primary is flat; at next W1 open, D1 is closed first. Combined exposure never exceeds 1 troy ounce.

| D1 source | Closed-candle filter | Total trades | Added | Net @ $2 | Net @ $5 | Increment vs baseline | Realized DD | Positive years |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| profit_frequency | d1_breakout | 85 | 10 | +3,144.80 | +2,889.80 | +318.82 | 570.13 | 7/8 |
| max_net | d1_adx | 93 | 18 | +3,011.95 | +2,732.95 | +185.96 | 570.13 | 6/8 |
| max_net | d1_ema | 101 | 26 | +3,005.51 | +2,702.51 | +179.52 | 570.13 | 6/8 |
| profit_frequency | d1_ema | 112 | 37 | +2,962.73 | +2,626.73 | +136.74 | 570.13 | 6/8 |
| profit_frequency | d1_adx | 105 | 30 | +2,960.89 | +2,645.89 | +134.90 | 570.13 | 6/8 |
| max_net | d1_breakout | 82 | 7 | +2,919.32 | +2,673.32 | +93.33 | 570.13 | 6/8 |
| max_signals | d1_adx | 125 | 50 | +2,896.44 | +2,521.44 | +70.45 | 581.01 | 6/8 |
| max_signals | d1_breakout | 90 | 15 | +2,893.57 | +2,623.57 | +67.58 | 581.01 | 6/8 |
| max_signals | d1_ema | 139 | 64 | +2,845.15 | +2,428.15 | +19.16 | 581.01 | 6/8 |
| max_net | prior_week_ema | 77 | 2 | +2,843.20 | +2,612.20 | +17.21 | 570.13 | 6/8 |
| max_signals | prior_week_ema | 78 | 3 | +2,833.43 | +2,599.43 | +7.44 | 570.13 | 6/8 |
| profit_frequency | prior_week_ema | 75 | 0 | +2,825.99 | +2,600.99 | +0.00 | 570.13 | 6/8 |
| max_net | any | 138 | 63 | +2,606.71 | +2,192.71 | -219.28 | 866.55 | 5/8 |
| profit_frequency | any | 166 | 91 | +2,494.91 | +1,996.91 | -331.08 | 1,021.26 | 6/8 |
| max_signals | any | 277 | 202 | +2,155.83 | +1,324.83 | -670.15 | 1,222.74 | 5/8 |

## Decision

- 11 configurations increased BOTH trade count and simulated net vs original 75-trade W1 strategy.
- 8 configurations also improved $5/oz net with >=6 positive years and DD <=1.25× baseline.
- Even a positive finding would remain exploratory rather than independent forward confirmation due to reuse of 2019–2026 research years.
- Do not deploy any R33 signal to live, do not modify Frozen V1 or ForexScanner forecast controls.

## Evidence

- [Actual GitHub Actions run: R33 W1 + D1 overlay](https://github.com/rizanrizan93/Forex-scanner/actions/workflows/r33_w1_d1_idle_alpha.yml)
- [Reproducible machine-readable result receipt](./RIZAN_R33_W1_D1_IDLE_ALPHA_FROZEN_20261124.json)
