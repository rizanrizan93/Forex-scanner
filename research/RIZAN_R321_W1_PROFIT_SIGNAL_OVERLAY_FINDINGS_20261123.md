# RIZAN R32.1 — W1 Profit and Extra Trade Study (2012–2026)

All **6** conservative one-oz combined strategies validated from individual event trade receipts. The baseline W1 EMA BUY 4-week model is preserved at **75 trades, +$2,825.99 per fixed oz**.

| W1 main + R32 overlay | Conditional entry | Trades | Added trades | Net @ $2/oz | Net @ $5/oz | Incremental net | Years positive |
|---|---|---:|---:|---:|---:|---:|---:|
| max_signals | ema_direction | 75 | 0 | +2,825.99 | +2,600.99 | +0.00 | 6/8 |
| profit_frequency | ema_direction | 75 | 0 | +2,825.99 | +2,600.99 | +0.00 | 6/8 |
| max_net | ema_direction | 75 | 0 | +2,825.99 | +2,600.99 | +0.00 | 6/8 |
| profit_frequency | any_flat | 78 | 3 | +2,804.73 | +2,570.73 | -21.26 | 6/8 |
| max_net | any_flat | 80 | 5 | +2,748.00 | +2,508.00 | -77.99 | 6/8 |
| max_signals | any_flat | 101 | 26 | +2,674.46 | +2,371.46 | -151.53 | 5/8 |

## Conclusion

- **No configuration increased BOTH historical profit and signal frequency under the same 1oz exposure cap.**
- The 26 additional trades from max_signals any_flat reduced total profit. Trading more was not the best action on these periods.
- The reference W1 EMA trend filter remains the higher-profit control, but has no independently verified future alpha.
- Research next: seek genuinely positive expectancy in *baseline-flat* regimes using independent forward period and broker executable spreads; do not overfit 2025.
- Frozen V1, R28, R29, R30 and ForexScanner/cTrader LIVE unmodified.
