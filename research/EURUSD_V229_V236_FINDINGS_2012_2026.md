# EURUSD V229-Style Historical Execution V236 — 2012–2026 YTD

## Scope

V236 reconstructs the current V229 2+2 child architecture on EURUSD using causal historical data.

- Pair: EURUSD
- History: 2012–2025 full years + 2026 YTD through 2026-09-27
- Initial account balance: **$100**
- Leverage: **1:100**
- Child size: **0.01 lot**
- Maximum children per parent: **4**
- L1/L2: pre-touch LIMIT
- L3: M5 reclaim + local MSS retest
- L4: M5 displacement + refined-pocket retest
- H4 structural stop: distal + 0.15 ATR buffer
- TP: opposing M15/H1/H4 supply-demand using the V229 structural-target planner
- Terminal structural RR gate: >= 1.5R
- Parent TTL: 16 hours
- Parent supersession cancels unfilled older children
- Intrabar ambiguity: **STOP_FIRST**
- Base costs: spread 0.8 pip, slippage 0.2 pip, commission 0.2 pip round trip
- Stress: spread x1.25, slippage x1.50
- Research/shadow only; no execution authority and no LIVE changes

The depth ladder is deliberately frozen from **XAU V225.2** rather than fitted on the EURUSD 2012–2026 sample. This avoids using future EURUSD depth information to manufacture historical entries.

## Overall result

### Base costs

| Metric | Result |
| --- | ---: |
| Parent plans | 3,221 |
| Completed child trades | 6,099 |
| Wins | 2,109 |
| Losses | 3,990 |
| Win rate | **34.58%** |
| Profit factor | **0.873** |
| Expectancy | **-0.0847R/trade** |
| Median trade | **-1.012R** |
| Fixed-0.01 total PnL without account-margin admission | **-$510.92** |
| Median MAE | **1.006R** |
| Median MFE | **0.790R** |
| STOP_FIRST ambiguous losses | 26 |

The current transferred V229-style geometry therefore has **negative expectancy** on EURUSD.

### Stress costs

| Metric | Result |
| --- | ---: |
| Completed child trades | 6,101 |
| Win rate | **34.39%** |
| Profit factor | **0.851** |
| Expectancy | **-0.0998R/trade** |
| Fixed-0.01 total PnL | **-$664.59** |

The weakness is not created by transaction costs alone; stress costs make an already-negative edge worse.

## $100 account, leverage 1:100

### Base costs

| Margin policy | Accepted trades | Margin rejected | Peak balance | Ending balance | Return | Realized max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Margin-only | 2,108 | 3,991 | **$355.39** | **$9.08** | **-90.92%** | **97.45%** |
| 50% margin cap | 2,019 | 4,080 | **$313.13** | **$16.84** | **-83.16%** | **94.62%** |

The account does not technically hit zero in this balance-based ledger, but the drawdown is catastrophic. The early balance peak does not represent a robust compounding edge; subsequent losses erase almost all of it.

### Stress costs

| Margin policy | Accepted trades | Margin rejected | Peak balance | Ending balance | Return | Realized max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Margin-only | 2,052 | 4,049 | **$347.73** | **$7.49** | **-92.51%** | **97.84%** |
| 50% margin cap | 1,981 | 4,120 | **$303.55** | **$18.85** | **-81.15%** | **93.79%** |

The stressed 50%-cap balance finishes slightly higher than the base-cost 50%-cap case only because worse costs alter margin feasibility and reject a different subset of later trades. It is **not** evidence that higher costs improve performance.

## By child slot — base costs

| Slot | Role | Completed | Win rate | PF | Expectancy |
| --- | --- | ---: | ---: | ---: | ---: |
| L1 | pre-touch | 2,272 | 43.27% | 0.833 | -0.0955R |
| L2 | pre-touch | 2,288 | 33.04% | **0.916** | **-0.0574R** |
| L3 | M5 reclaim + MSS | 864 | 23.15% | 0.868 | -0.1040R |
| L4 | M5 displacement | 675 | 25.19% | 0.848 | -0.1160R |

L2 is the closest slot to break-even, but still fails the positive-expectancy requirement. The current L3/L4 confirmation logic does not rescue expectancy; confirmation appears too late and/or the resulting target-stop geometry remains unfavorable.

## By candidate source — base costs

| Source layer | Completed | Win rate | PF | Expectancy |
| --- | ---: | ---: | ---: | ---: |
| H4 | 819 | 39.56% | 0.797 | -0.1241R |
| H1 | 2,245 | 32.74% | 0.848 | -0.1038R |
| M15 | 3,035 | 34.60% | **0.910** | **-0.0599R** |

M15 is the strongest source layer, but still negative.

## Era stability

| Era | Completed | Win rate | PF | Expectancy | Fixed-0.01 PnL |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2012–2018 | 2,876 | 34.32% | 0.834 | -0.1104R | -$314.40 |
| 2019–2024 | 2,489 | **35.15%** | **0.927** | **-0.0481R** | -$112.80 |
| 2025–2026 YTD | 734 | 33.65% | 0.840 | -0.1081R | -$83.72 |

No era produces positive expectancy. 2019–2024 is materially closer to break-even, but still does not pass.

2026 is partial through **2026-09-27**. The 2026 shard contains 242 H4 first-touch parents, 167 valid plans, and 288 base-cost completed children.

## Why V235 looked strong but V236 loses money

V235 measured a different question:

> After a fresh zone is touched, does EURUSD produce at least a 0.50 ATR favorable reaction before distal invalidation?

That occurred around 72–75% of the time.

V236 asks the trading question:

> Can the current V229 entry ladder, structural H4 stop, structural M15/H1/H4 targets, M5 confirmation and costs turn those reactions into profitable executed trades?

The answer for the current transfer is **no**.

The median completed trade reaches only about **0.79R MFE**, while median MAE is approximately **1.01R**. Many zones react enough to satisfy the V235 0.50 ATR criterion, but not enough—soon enough—to overcome the V229 stop/target geometry.

This distinction is critical: a high zone-reaction rate is not the same as a profitable execution strategy.

## Research conclusion

Do **not** grant EURUSD execution authority from V236 and do not copy XAU V229 thresholds unchanged into EURUSD.

The next research target should not be a more aggressive leverage setting. Leverage does not repair negative expectancy.

The most useful V237 candidates are:

1. Keep the strong EURUSD causal depth map but recalibrate **exit geometry** around observed MFE/reaction distribution instead of forcing the XAU structural terminal behavior.
2. Test L2 independently because it is the closest child to break-even.
3. Rework L3/L4 activation timing; current M5 confirmation does not improve expectancy.
4. Separate M15-source entries from H4/H1-source entries; M15 is materially stronger.
5. Run walk-forward target/stop perturbations using training-only EURUSD history, then evaluate untouched forward eras.
6. Preserve the $100 / 1:100 account test only after a strategy variant has positive R expectancy and PF > 1 after costs.

## Limitations

- V236 is a causal reconstruction of the current V229 child mechanics, not a byte-for-byte replay of historical live AFIC path-focus decisions.
- XAU V225.2 depth priors are frozen to avoid EURUSD full-sample leakage.
- The account ledger admits new positions from **realized balance** and does not simulate intratrade mark-to-market broker stop-out. True broker survival can therefore be worse than reported.
- A 30-day research exit is used only when neither structural TP nor SL occurs.
- Historical data and transaction-cost models cannot guarantee future performance.
