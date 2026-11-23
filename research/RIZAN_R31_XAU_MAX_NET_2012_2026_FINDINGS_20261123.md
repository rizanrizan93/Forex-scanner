# RIZAN R31 — XAUUSD Net Profit First 2012–2026

Research frozen, **no live promotion or cBot edits**.

All amounts are *hypothetical* USD for a constant **one troy ounce per position** with a **$2/oz cost scenario**. They are NOT account balances or executable profits. 2019–2026 walk-forward (partial 2026).

## Scanned 30 independently replayed TF × holding period × selection-mode variants

| TF | Hold bars | Mode | Trades | Net $/1oz | Max realized DD $/1oz | Net/DD | Net at $5 cost | Positive years |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| 1W | 2 | net_dd | 72 | +1,339.83 | 303.90 | 4.41 | +1,123.83 | 2/8 |
| 1W | 2 | profit_frequency | 116 | +1,032.25 | 932.22 | 1.11 | +684.25 | 3/8 |
| 1W | 2 | max_net | 103 | +848.92 | 1,053.60 | 0.81 | +539.92 | 3/8 |
| 1W | 1 | profit_frequency | 225 | +676.08 | 1,046.55 | 0.65 | +1.08 | 3/8 |
| 1h | 1 | max_net | 111 | +194.73 | 234.80 | 0.83 | -138.27 | 1/8 |
| 1h | 1 | profit_frequency | 111 | +194.73 | 234.80 | 0.83 | -138.27 | 1/8 |
| 4h | 1 | net_dd | 171 | +38.85 | 277.01 | 0.14 | -474.15 | 2/8 |
| 1h | 1 | net_dd | 0 | +0.00 | 0.00 | — | +0.00 | 0/8 |
| 1D | 1 | net_dd | 237 | -46.87 | 506.97 | -0.09 | -757.87 | 3/8 |
| 1W | 1 | net_dd | 106 | -182.76 | 888.47 | -0.21 | -500.76 | 2/8 |
| 4h | 2 | max_net | 374 | -229.38 | 625.59 | -0.37 | -1,351.38 | 3/8 |
| 1W | 1 | max_net | 161 | -337.26 | 1,178.14 | -0.29 | -820.26 | 3/8 |
| 4h | 3 | max_net | 544 | -340.43 | 887.77 | -0.38 | -1,972.43 | 1/8 |
| 1D | 2 | profit_frequency | 425 | -340.76 | 1,307.03 | -0.26 | -1,615.76 | 1/8 |
| 4h | 1 | max_net | 295 | -430.12 | 693.36 | -0.62 | -1,315.12 | 2/8 |
| 4h | 3 | net_dd | 307 | -432.04 | 619.17 | -0.70 | -1,353.04 | 1/8 |
| 4h | 1 | profit_frequency | 331 | -457.97 | 793.76 | -0.58 | -1,450.97 | 2/8 |
| 1D | 2 | net_dd | 140 | -585.38 | 738.22 | -0.79 | -1,005.38 | 2/8 |
| 1h | 4 | net_dd | 262 | -602.72 | 736.54 | -0.82 | -1,388.72 | 0/8 |
| 4h | 2 | net_dd | 347 | -654.24 | 966.00 | -0.68 | -1,695.24 | 0/8 |
| 1h | 4 | profit_frequency | 580 | -726.62 | 875.66 | -0.83 | -2,466.62 | 0/8 |
| 1D | 1 | max_net | 449 | -732.29 | 1,365.27 | -0.54 | -2,079.29 | 1/8 |
| 1D | 1 | profit_frequency | 498 | -800.55 | 1,365.27 | -0.59 | -2,294.55 | 1/8 |
| 1h | 2 | net_dd | 186 | -851.82 | 905.76 | -0.94 | -1,409.82 | 0/8 |
| 1h | 4 | max_net | 543 | -936.68 | 988.95 | -0.95 | -2,565.68 | 0/8 |
| 1D | 2 | max_net | 450 | -1,074.26 | 1,307.03 | -0.82 | -2,424.26 | 0/8 |
| 1h | 2 | profit_frequency | 394 | -1,079.29 | 1,164.24 | -0.93 | -2,261.29 | 0/8 |
| 1h | 2 | max_net | 342 | -1,111.07 | 1,196.01 | -0.93 | -2,137.07 | 0/8 |
| 4h | 2 | profit_frequency | 720 | -1,290.70 | 1,516.38 | -0.85 | -3,450.70 | 2/8 |
| 4h | 3 | profit_frequency | 757 | -2,216.90 | 2,310.45 | -0.96 | -4,487.90 | 1/8 |

## Robustness verdict

- None of the 30 tested policies passed the predeclared five-year and conservative-cost robustness gates. No winner suitable for promotion.

## Audit caveats

- 2012–2018 H1/H4 are independent historical rehosted candles with 2019 byte-identical overlap to original R10; source boundary logged.
- Exit is H-th future completed close; next open is an optimistic fill proxy, not executable FP Markets bid/ask.
- No compounded account value, lot size, leverage, spread measurement or margin model.
- Training and selection use previous 2 fully matured calendar years; entire search had earlier exploratory research on 2019–26. Overfit possible.
- Drawdown is realized-close based and understates potential floating drawdown.
- Preserve the original 30 JSON receipts; never choose a live model based on this historical rank alone.

## Next actions

- Research only: additional time splits, multiple vendor source checks, FP Markets spread/slippage measurements, prospective never-retuned shadow receipts and MFE/MAE.
- No changes to Frozen V1, R28, R29, R30 or ForexScanner signal permissions.
