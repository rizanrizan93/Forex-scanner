# RLFE L2 Win-Rate Audit — 2026-10-20

## Status: NOT PROMOTED
Independent verification used archived `RIZAN_BOOKMAP_ZONE_L2_PILOT_20261020.zip` from the user's research library. The source is **Bybit BTCUSDT linear perpetual order-book snapshots and deltas** covering 2024-01-01 through 2024-01-08, **not** licensed Bookmap software, **not** FP Markets BTCUSD execution, and **not** exchange trades. Quote grids (1 s) and event ledger replayed; 12 original tests and 10 RLFE shadow-contract tests pass locally. No new exchange feed was connected.

Data audit recorded 6,911,831 messages, 691,200 1-second sample slots, 16 invalid quote seconds. Event ledger: 189 candidates, 181 complete, 7 invalid risk, 1 gap censored. Four development days Jan 2-5; three short diagnostic holdout days Jan 6-8.

### Ex-ante zone touch, net R after modeled cost

| Split | Filter | N | Net win % | Mean gross R | Mean cost R | Mean net R | PF net |
|---|---|---:|---:|---:|---:|---:|---:|
| 2024-01-02..05 | Baseline | 56 | 46.43 | -0.037 | 0.457 | -0.495 | 0.326 |
| 2024-01-02..05 | Imbalance L2 | 8 | 37.50 | -0.395 | 0.425 | -0.820 | 0.179 |
| 2024-01-06..08 | Baseline | 57 | 50.88 | +0.057 | 0.673 | -0.617 | 0.219 |
| 2024-01-06..08 | Imbalance L2 | 11 | 63.64 | +0.320 | 0.610 | -0.289 | 0.461 |

Holdout coverage after L2 = 11/57 (19.3%). Holdout daily L2 signal results: Jan 6 3/3 positive, +0.329R mean; Jan 7 2/4, -0.611R; Jan 8 2/4, -0.432R. Pooled signal 95% Wilson interval 38.68%..81.53% before dependence correction. In 20,000 random size-11 unstratified draws from the 57 baseline holdout events, 12.6% had an equal or higher mean net R; diagnostic only, **not** a formal significance p-value.

At fee factor 0.5x (same assumed fills) filtered PF ≈1.035, mean ≈+0.015R; factor below 0.5254x is needed for positive mean. This is *not* evidence that these costs are achievable. One-active-position chronological downselection yields baseline 44 trades, PF ≈0.191, filtered 11, PF ≈0.461. No profitable net edge certified.

Holdout repo-derived H1/M5 zones: baseline 2/10 net wins vs L2 0/2. M15 sweep reclaim: baseline 11/25 vs L2 0/2. Persistence filters passed zero/one holdout samples: no usable win-rate conclusion.

### XAUUSD / EURUSD L2 availability
Read-only database audit found 22 broker Level-II XAU pressure rows only from 2026-09-27 22:03:58 UTC to 22:38:54 UTC in the legacy Forex scanner Supabase project; ForexRizan had zero same-table rows. This is insufficient for multi-year validation. Turso not audited. No COMEX GC/CME 6E historical MBO archive available to this run. CME DataMine sells historical Market Depth/MBO; Bookmap's public CME data backfill product is not a substitute for historical long-horizon depth. Tardis publishes first-of-month historical crypto L2/trade samples without API key, but binary download access is blocked in current research runtime.

### Release decision
**NO LIVE PROMOTION**, no exchange-trade-derived CVD/absorption inference, do not add signal to frozen cBot/bridge, do not assert RLFE improves Candidate A XAU win rate. This BTC pilot uses different zone families and market/fee execution assumptions from Candidate A XAU. `NO_DATA` until licensed, point-in-time native depth and prints plus instrument basis mapping and multi-month/multi-year validation are available.

Artifacts for reproducibility reside in user research library: `RIZAN_BOOKMAP_ZONE_L2_PILOT_20261020.zip`; audit deliverable `RIZAN_RLFE_BOOKMAP_L2_WINRATE_AUDIT_20261020.zip` includes its exact ledger, independent audit code, logs and group summaries.

Public documentation:
- https://docs.tardis.dev/downloadable-csv-files
- https://github.com/binance/binance-public-data
- https://bookmap.com/en/bmdata
- https://www.cmegroup.com/market-data/real-time-and-historical-data.html
