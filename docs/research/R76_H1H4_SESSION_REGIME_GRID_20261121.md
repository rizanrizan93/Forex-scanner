# R7.6 H4/H1 session and regime conditional rule replay — 21 Nov 2026

Research-only development; no production change. R7.3 M1 remains selected research family, not a prospective parameter freeze. R7.2 and Frozen V1 unchanged.

Local empirical replay completed using source-hash-checked R2 HistData M1-derived XAU feature/label archives from run 44240141371 and Dukascopy DOLLAR.IDX/USD H1 BID CFD archives from run 44831876236, 2019–2024 only. 2023 gold source remains incomplete, not independently repaired for intraday. USD bar available only after H1 close plus assumed 1h or 2h delay. Matching timestamps across both assumptions, not authenticated historic receipts or ICE DXY. Outcome = next 1h/4h move after completed gold candle, less assumed USD0.50/oz. No actual FP Markets execution or P&L. 2025–26 excluded; 2023–24 outer development years already repeatedly examined, not independent holdout.

Grid: 10 symmetric price/USD rules × 5 session filters × 4 volatility filters × 4 strength thresholds = 800 configurations per horizon, 1,600 horizon-specific configurations. Each scored in earlier years at both delay assumptions, selected for 2023 and 2024 separately. Minimum earlier BUY/SELL sample counts, yearly side-count floors, positive aggregate hypothetical net movement, and worst-side Wilson criterion. Total 6,400 config-fold-delay scores. No tuning on outer year outcomes. 

| Horizon/outer year | Selected rule | Correct/active | BUY | SELL | Mean signed move after hypothetical cost |
|---|---|---|---|---|---|
| H4 2023 | XAU trend, NY local 08–16, vol ratio <0.85 | 18/38 | 6/17 | 12/21 | -0.894 |
| H4 2024 | XAU trend, London local 08–16, vol ratio <0.85 | 37/72 | 23/47 | 14/25 | +0.4732 |
| H1 2023 | XAU trend, London 08–16, vol ratio >1.2, strength >=0.5 | 27/74 | 11/29 | 16/45 | -1.6724 |
| H1 2024 | WAIT, no candidate eligible | — | — | — | — |

The selected rules were all price-only despite adding USD candidate families. Same-date price trend comparator is identical by construction. No evidence of robust incremental USD/regime alpha. H4 aggregate 55/110 =50%, BUY 29/64=45.3125%, SELL 26/46=56.5217%; low coverage (110/1581 matched observations). 60% bidirectional gate not passed. Do not deploy or select a single outer winner post hoc. Source provenance and incomplete 2023 price source limit generalization.

Next: actual timestamped intraday Treasury yields or Treasury futures and verified scheduled policy/news event receipts, compare before and after releases with independent forward evidence. Measure MFE/MAE and first-touch +/-$10 only after direction hypothesis established and full M1 paths acquired. No claim of completed MFE/MAE or $10 test in R7.6.
