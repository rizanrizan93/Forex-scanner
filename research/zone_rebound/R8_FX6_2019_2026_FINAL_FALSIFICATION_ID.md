# R8-FX6 final falsification — 2019–2026

**Research only, 20 Nov 2026 UTC; DO NOT PROMOTE OR MERGE TO LIVE.**

## Verified replay and source identity

- GitHub Actions 8-year annual source acquisition and fixed R6 causal events: [run 44756827925](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44756827925). All eight `fx6_annual` shards passed.
- 8-year normalized aggregate: [run 44758301348](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44758301348), artifact `r8-fx6-macro-8year-aggregate`. JSON SHA-256: `f44c33f8c7037bd22334da8551fbf7144b9cb75376f21e9b5c2f66a81be2ed76`.
- Fixed R6 baseline: PR #883, genuine HistData XAUUSD M1, expected signed move > $0.50/oz after 60m or 240m. All 32 R6 reference cells (8 years x H1/H4 x BUY/SELL) reproduced exactly in R8.
- USD macro is **independently reconstructed 6FX index** (EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF), using published ICE USDX weights on common HistData M1 UTC timestamps. Not licensed ICE DXY, not Dukascopy DOLLARIDXUSD. No forward-filled gaps.
- `first_seen_at` is **not** historically recorded. Lag 1/5/15m is scenario analysis only; 2025–2026 has been inspected repeatedly, **not pristine**. No actual broker spread, slippage, fills or cash-yield quotes.

## Results: 2025–2026 reused evaluation, lag = 1 minute

| H1/H4 | Cohort | BUY | SELL |
|---|---|---:|---:|
| H1 | frozen R6 | 55.38% (103/186) | 46.59% (116/249) |
| H1 | USD 15m and 60m XAU-aligned | **67.57% (25/37)** | **44.23% (23/52)** |
| H1 | USD 15m and 60m XAU-opposed | 58.16% (57/98) | 47.97% (59/123) |
| H4 | frozen R6 | 48.66% (91/187) | 45.61% (104/228) |
| H4 | USD 15m and 60m XAU-aligned | **45.95% (17/37)** | **51.16% (22/43)** |
| H4 | USD 15m and 60m XAU-opposed | 47.06% (32/68) | 46.48% (33/71) |

Full 2019–2026 USD-aligned cohort: H1 BUY 50.47% (54/107), SELL 40.24% (68/169); H4 BUY 47.02% (71/151), SELL 45.41% (84/185).

2019–2023 development USD-aligned cohort: H1 BUY 37.70% (23/61), SELL 40.86% (38/93); H4 BUY 43.75% (42/96), SELL 40.19% (43/107).

2024 validation USD-aligned cohort: H1 BUY 66.67% (6/9), SELL 29.17% (7/24); H4 BUY 66.67% (12/18), SELL 54.29% (19/35). Small n and lack of BUY/SELL symmetry preclude promotion.

For lag 15m with max quote-age 5m, macro eligibility is n=0, not 0% accuracy. H1 BUY 2025–26 aligned 67.57% has a Wilson 95% lower confidence bound of 51.46%, below 60%.

## Verdict

**R8-FX6 fails the >=60% BUY AND SELL acceptance gate on both H1 and H4.** The $10 reversal target is not investigated. No production or order system modifications. A genuinely prospective locked shadow ledger with timestamped first_seen_at, provider bid/ask, negative-control shuffled-lag experiment and regime-by-year robustness is required before future promotion.

The separate Dukascopy DOLLARIDXUSD native 2019–2026 replay remains blocked by HTTP503/timeout for old archive samples, though Nov-2025 and Nov-2026 M1 source samples were acquired. Do not treat the FX6 proxy as the native Dukascopy vendor dataset.
