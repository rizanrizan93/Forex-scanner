# Five Core Tournament V1 — Findings

Date: 2026-09-12 (Asia/Jakarta)

Research only. `execution_influence=false`.

Universe is intentionally fixed to five instruments: XAUUSD, EURUSD, GBPUSD, USDJPY, AUDUSD.

## Primary result

The strongest strategy/instrument combination is **XAUUSD D1_TSMOM_60_200**.

Long-history unchanged-rule validation, Dukascopy BID H1 resampled to D1, 2012-01 through 2026-09-01:

| Era | Trades | Expectancy | PF | Net R | 95% bootstrap mean CI |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2012–2016 | 78 | +0.07255R | 1.1272 | +5.6591R | -0.21369 .. +0.34508 |
| 2017–2020 | 64 | +0.05326R | 1.0998 | +3.4084R | -0.24332 .. +0.35863 |
| 2021–2024 | 75 | +0.18783R | 1.3568 | +14.0874R | -0.10323 .. +0.50551 |
| 2025–Aug 2026 | 32 | +0.65402R | 2.8601 | +20.9286R | +0.18313 .. +1.12074 |
| Full 2012–Aug 2026 | 249 | **+0.17704R** | **1.3408** | **+44.0835R** | **+0.02404 .. +0.34497** |

Full-history max drawdown: 16.4294R. Annual net R is positive in 10 of 15 calendar-year buckets (2026 partial). The strategy has losing years and is not a guaranteed-return system, but all four multi-year eras are positive and the full-history bootstrap mean CI is above zero.

XAUUSD OOS cost stress remains effectively unchanged because D1 ATR risk is large relative to transaction cost:
- $0.17 round trip: +0.65402R/trade, PF 2.8601.
- $0.25: +0.65336R/trade, PF 2.8572.
- $0.35: +0.65253R/trade, PF 2.8536.

This is a **strong research candidate**, not yet execution-promoted. Broker-specific cTrader replay, alternate-feed confirmation, daily-bar boundary sensitivity, and forward DEMO evidence remain mandatory.

## Secondary observations

### XAUUSD H4 compression breakout
Full 2012–2026: 329 trades, +0.12504R/trade, PF 1.2089, +41.137R, but CI crosses zero (-0.02127 .. +0.27644). It was negative in 2021–2024 (-0.16724R/trade) before becoming very strong again in 2025–2026 (+0.56040R/trade). Treat as **regime-dependent research candidate**, not a stable standalone edge.

### USDJPY H4 compression breakout
Full 2012–2026: 378 trades, +0.09162R/trade, PF 1.1487, +34.6338R, but CI crosses zero (-0.05211 .. +0.23705). Era behavior is unstable: negative in 2012–2016 and 2017–2020, strong in 2021–2024, mildly positive in 2025–2026. Treat as **regime-dependent watch**, not promotion-ready.

### AUDUSD
H4 trend-pullback full 2012–2026: 907 trades, +0.03525R/trade, PF 1.0566, but CI -0.05325 .. +0.12649 and recent 2-pip stress turns expectancy negative. **Weak / no promotion.**

### GBPUSD
No tested slow strategy is robust over 2012–2026. H4 trend-pullback is mildly positive only in 2025–2026 but full-history expectancy is -0.07639R/trade. **No candidate.**

### EURUSD
No tested strategy is robust. Full-history H4 trend-pullback and compression breakout are negative; D1 momentum is near flat and OOS 2025–2026 is negative. **NO_TRADE remains the correct state until another independent alpha family passes.**

## M15 Asia sweep reversal
Rejected across all five instruments in 2025–Aug 2026:
- XAUUSD: -0.10221R/trade, PF 0.8330.
- EURUSD: -0.17535R/trade, PF 0.7432.
- GBPUSD: -0.13790R/trade, PF 0.7923.
- USDJPY: -0.09684R/trade, PF 0.8444.
- AUDUSD: -0.14679R/trade, PF 0.7776.

This strategy family should not receive execution influence.

## Current pair profiles

| Instrument | Current research interpretation |
| --- | --- |
| XAUUSD | Best fit: D1 trend/momentum. H4 compression is a secondary regime-dependent hypothesis. |
| USDJPY | Compression/trend-breakout deserves further regime work; recent D1 momentum is weak. |
| AUDUSD | No convincing edge yet; H4 pullback is too weak/cost-sensitive. |
| GBPUSD | No robust tested edge; keep NO_TRADE while testing other families. |
| EURUSD | No robust tested edge; keep NO_TRADE while testing other families. |

## Promotion status

No strategy is promoted by this research branch. The next confirmation target is XAUUSD D1_TSMOM_60_200 using broker-specific/cross-feed historical data and forward DEMO. Risk ceilings and current DEMO execution logic remain unchanged.
