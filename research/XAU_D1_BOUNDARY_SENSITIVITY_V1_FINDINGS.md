# XAU D1 Boundary Sensitivity V1 — Findings

Status: **PASS for boundary transferability at base cost; NOT a promotion by itself**.

Contract: `XAU_D1_BOUNDARY_SENSITIVITY_V1`  
Execution influence: `false`

## Why this test was required

The original `D1_TSMOM_60_200` research constructed D1 bars with UTC-midnight pandas buckets. The FP Markets cTrader DEMO history probe shows XAUUSD D1 timestamps at 17:00 America/New_York, represented as 21:00 or 22:00 UTC across DST. The strategy parameters were therefore frozen and replayed with only the D1 aggregation boundary changed.

## Frozen strategy

- close versus EMA200 trend
- 60-day return in the same direction
- next D1 open entry
- 2 ATR14 stop
- 4 ATR14 target (2R)
- 30 D1-bar maximum hold
- STOP_FIRST same-bar ambiguity policy
- XAU transaction-cost stress: $0.17 / $0.25 / $0.35 absolute roundtrip model

## Primary result

| Variant | Window | Trades | Net R | Expectancy R/trade | PF | Max DD R | Bootstrap 95% CI |
|---|---|---:|---:|---:|---:|---:|---:|
| UTC00 original | Full 2012–2026 | 249 | +44.0835 | +0.17704 | 1.3408 | 16.4294 | +0.02404 to +0.34497 |
| NY17 broker-aligned | Full 2012–2026 | 204 | +35.2310 | +0.17270 | 1.3419 | 14.7440 | +0.00099 to +0.34731 |
| UTC00 original | OOS 2025–2026 | 32 | +20.9286 | +0.65402 | 2.8601 | 2.3561 | +0.18313 to +1.12074 |
| NY17 broker-aligned | OOS 2025–2026 | 28 | +20.9917 | +0.74970 | 3.5148 | 3.1437 | +0.26696 to +1.19318 |

The broker-aligned result retains essentially the same full-history expectancy and PF and improves the recent OOS expectancy/PF. This means the previously identified XAU edge is not an artifact of using UTC-midnight D1 bars.

## Cost stress

NY17 full-history:
- $0.17: +0.17270 R/trade, PF 1.3419, CI +0.00099 to +0.34731
- $0.25: +0.17077 R/trade, PF 1.3373, CI -0.00096 to +0.34538
- $0.35: +0.16836 R/trade, PF 1.3316, CI -0.00324 to +0.34298

NY17 OOS 2025–2026 remains strong under all tested costs:
- $0.17: +0.74970 R/trade, PF 3.5148
- $0.25: +0.74913 R/trade, PF 3.5118
- $0.35: +0.74840 R/trade, PF 3.5080

The full-history bootstrap lower bound crosses slightly below zero under the higher cost stresses. Therefore the result supports continued DEMO validation but does **not** justify increasing execution authority.

## Direction diagnostic — not a strategy change

Broker-aligned full history:
- LONG: 124 trades, +42.3047R, +0.34117 R/trade, PF 1.7530, CI +0.10360 to +0.59319
- SHORT: 80 trades, -7.0737R, -0.08842 R/trade, PF 0.8491, CI -0.35825 to +0.19396

This is diagnostic only. Turning off shorts now would be a post-hoc strategy modification and is prohibited without an independently preregistered validation.

## Decision

1. Keep XAUUSD `D1_TSMOM_60_200` in DEMO-only validation.
2. Do not promote to LIVE or increase risk/lot authority.
3. Continue durable forward evidence collection on actual cTrader D1 bars.
4. Run confirmatory cTrader broker-feed replay / cross-feed validation.
5. Treat long-vs-short asymmetry as a future hypothesis, not as an immediate rule change.

Evidence workflow run: `34665250496`  
Evidence artifact ID: `10289015760`  
Artifact SHA-256: `b729e85f7bd2973781b5d5f649b1b57c2e846a43bffcf684874a31f42a8539ff`
