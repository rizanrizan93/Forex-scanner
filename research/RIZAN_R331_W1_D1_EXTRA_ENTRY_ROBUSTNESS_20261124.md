# RIZAN R33.1 — W1 + D1 Additional-Entry Risk Stress

**Historical exploratory evidence only; NOT prospectively validated.**

Existing W1 trend base: 75 signals, +$2,825.99/1oz under assumed $2/oz cost. R33 D1 overlays execute only when W1 is not active, and never exceed 1oz combined exposure.

| D1 source | Filter | Extra trades | Extra net @ $2/oz | Extra net @ $5/oz | Extra net @ $10/oz | Excluding 2025 |
|---|---|---:|---:|---:|---:|---:|
| profit_frequency | d1_breakout | 10 | +318.82 | +288.82 | +238.82 | +318.82 |
| max_net | d1_adx | 18 | +185.96 | +131.96 | +41.96 | +185.96 |
| max_net | d1_ema | 26 | +179.52 | +101.52 | -28.48 | +179.52 |
| profit_frequency | d1_ema | 37 | +136.74 | +25.74 | -159.26 | +136.74 |
| profit_frequency | d1_adx | 30 | +134.90 | +44.90 | -105.10 | +134.90 |
| max_net | d1_breakout | 7 | +93.33 | +72.33 | +37.33 | +93.33 |
| max_signals | d1_adx | 50 | +70.45 | -79.55 | -329.55 | +70.45 |
| max_signals | d1_breakout | 15 | +67.58 | +22.58 | -52.42 | +67.58 |
| max_signals | d1_ema | 64 | +19.16 | -172.84 | -492.84 | +19.16 |
| max_net | prior_week_ema | 2 | +17.21 | +11.21 | +1.21 | +17.21 |
| max_signals | prior_week_ema | 3 | +7.44 | -1.56 | -16.56 | +7.44 |
| profit_frequency | prior_week_ema | 0 | +0.00 | +0.00 | +0.00 | +0.00 |
| max_net | any | 63 | -219.28 | -408.28 | -723.28 | -219.28 |
| profit_frequency | any | 91 | -331.08 | -604.08 | -1,059.08 | -331.08 |
| max_signals | any | 202 | -670.15 | -1,276.15 | -2,286.15 | -670.15 |

## Most profitable additional-entry rule, by annual contribution

| Year | Extra net $/1oz (cost $2) |
|---|---:|
| 2019 | +0.00 |
| 2020 | +0.00 |
| 2021 | +30.66 |
| 2022 | +25.71 |
| 2023 | +0.00 |
| 2024 | +0.00 |
| 2025 | +0.00 |
| 2026 | +262.45 |

## Cautions

- Selected after 15 tested combinations: profit_frequency with d1_breakout.
- Incremental 2019–2022 total +56.37; 2023–2026 total +262.45.
- Remove 2025 incremental PnL: +318.82. Largest individual profit +89.32, loss -41.59.
- Bootstrap resampling 8 calendar-year outcomes, 20k draws: 95% diagnostic interval [+25.71, +843.72]. THIS IS NOT a forward confidence interval after multiple historical searches.
- Execution spread/overnight swap and floating drawdown not yet measured, so cannot promote to LIVE.

## Evidence

- [Original 15 R33 XAU backtests](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45255941738)
- [Machine-readable risk evidence](./RIZAN_R331_W1_D1_EXTRA_ENTRY_ROBUSTNESS_20261124.json)
