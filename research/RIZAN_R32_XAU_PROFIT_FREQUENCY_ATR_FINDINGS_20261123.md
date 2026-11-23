# RIZAN R32 — Profit + Profitable Signal Count (2012–2026)

**Research-only. No Frozen V1 or ForexScanner changes.**

All results are **hypothetical USD per 1 fixed ounce** (not compounded account balance). Entry from next OPEN, OHLC-based ATR trailing/stop/target. Main cost assumption $2/oz, tested $5/oz.

| TF | Objective | Signals | Net @ $2/oz | Net @ $5/oz | PF | Max realized DD | Positive years |
|---|---|---:|---:|---:|---:|---:|---:|
| 1W | profit_frequency | 50 | +2,538.89 | +2,388.89 | 2.13 | 650.78 | 5/8 |
| 1W | max_signals | 157 | +2,122.17 | +1,651.17 | 1.47 | 960.16 | 5/8 |
| 1W | max_net | 63 | +1,646.73 | +1,457.73 | 1.49 | 1,295.74 | 4/8 |
| 1D | max_net | 223 | +1,340.32 | +671.32 | 1.20 | 1,483.84 | 5/8 |
| 1D | profit_frequency | 311 | +535.52 | -397.48 | 1.06 | 1,439.00 | 3/8 |
| 4h | max_net | 383 | +351.57 | -797.43 | 1.07 | 1,068.53 | 4/8 |
| 4h | profit_frequency | 338 | +278.70 | -735.30 | 1.06 | 1,068.53 | 3/8 |
| 1D | max_signals | 533 | +33.02 | -1,565.98 | 1.00 | 2,142.72 | 3/8 |
| 1h | max_net | 0 | +0.00 | +0.00 | — | 0.00 | 0/8 |
| 1h | max_signals | 0 | +0.00 | +0.00 | — | 0.00 | 0/8 |
| 1h | profit_frequency | 0 | +0.00 | +0.00 | — | 0.00 | 0/8 |
| 4h | max_signals | 544 | -273.36 | -1,905.36 | 0.97 | 1,442.04 | 2/8 |

## Read-only selection and baseline

- Previous simple W1 EMA BUY 4-week baseline: 75 trades, +$2,825.99/oz (PF 2.70), 6/8 positive years.
- Previous simple D1 EMA+ADX BUY 5-day baseline: 193 trades, +$2,294.64/oz, 6/8 positive years.
- A new R32 candidate is not an improvement merely because of more trades or higher gross profit; compare same 1oz exposure, $5 cost, and positive years.
- No 2019–26 clean pristine OOS remains because many strategy versions have already inspected those years.
- ATR stop loss is not a hard loss limit when price gaps or broker liquidity breaks.
- Do not deploy based on backtests. Forward never-retuned historical-to-live handoff is required.

## Evidence

- [R32 original complete multi-timeframe GitHub Actions evidence](https://github.com/rizanrizan93/Forex-scanner/actions/workflows/r32_profit_frequency_atr.yml)
- [Machine-readable research checkpoint](./RIZAN_R32_XAU_PROFIT_FREQUENCY_ATR_LOCK_20261123.json)
