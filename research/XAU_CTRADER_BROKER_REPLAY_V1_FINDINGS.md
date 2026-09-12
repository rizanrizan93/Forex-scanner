# XAU cTrader Broker Replay V1 — Findings

Status: **PASS as confirmatory broker-feed evidence; DEMO-only remains unchanged.**

Contract: `XAU_CTRADER_BROKER_REPLAY_V1`  
Execution influence: `false`

## Scope

This replay uses **FP Markets cTrader Open API historical XAUUSD D1 trendbars**, i.e. the same broker/feed family used by the DEMO scanner. It does not use Dukascopy bars for the replay and does not expose an order-submission path.

Frozen `D1_TSMOM_60_200` parameters:

- trend: D1 close versus EMA200
- momentum: 60-day return with the same sign
- entry: next broker D1 open
- stop: 2 ATR14
- target: 4 ATR14 = 2R
- maximum hold: 30 D1 bars
- same-bar ambiguity: STOP_FIRST
- cost stress: $0.17 / $0.25 / $0.35 absolute roundtrip model

## Broker coverage and boundary

- Requested historical bars: 1,500
- Closed broker D1 bars returned: **1,500**
- First bar: `2020-11-01T22:00:00+00:00`
- Last closed bar: `2026-09-10T21:00:00+00:00`
- D1 open seconds UTC: **[75600, 79200]** = 21:00/22:00 UTC

This independently confirms the observed cTrader D1 boundary as 17:00 America/New_York with DST.

## Base-cost result — actual cTrader bars

| Window | Trades | Net R | Expectancy R/trade | PF | Win rate | Max DD R | Bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full available 2020–2026 | 79 | +26.2196 | +0.33189 | 1.7228 | 50.63% | 7.0308 | +0.04998 to +0.62494 |
| OOS 2025+ | 29 | +18.6920 | +0.64455 | 2.8307 | 62.07% | 3.3778 | +0.16634 to +1.14748 |

The broker-feed replay is positive with a bootstrap interval above zero over the full available broker history and the 2025+ OOS slice.

## Cost stress — actual cTrader bars

Full available:

- $0.17: +0.33189 R/trade, PF 1.7228, CI +0.04107 to +0.62317
- $0.25: +0.33069 R/trade, PF 1.7192, CI +0.04793 to +0.62321
- $0.35: +0.32918 R/trade, PF 1.7147, CI +0.03997 to +0.61842

OOS 2025+:

- $0.17: +0.64455 R/trade, PF 2.8307, CI +0.15747 to +1.11840
- $0.25: +0.64397 R/trade, PF 2.8283, CI +0.15281 to +1.12453
- $0.35: +0.64325 R/trade, PF 2.8253, CI +0.15575 to +1.12335

All tested broker-feed cost stresses retain positive bootstrap lower bounds.

## Direction diagnostic — no rule change

Full available broker replay:

- LONG: 59 trades, +32.9281R, +0.55810 R/trade, PF 2.4445, CI +0.21866 to +0.90153
- SHORT: 20 trades, -6.7085R, -0.33542 R/trade, PF 0.5023, CI -0.75219 to +0.15154

This repeats the long/short asymmetry seen in the broker-aligned Dukascopy analysis. It is still diagnostic only. Disabling shorts now would be a post-hoc strategy modification and requires its own preregistered validation.

## Annual variability

The full strategy is not uniformly profitable by calendar year:

- 2021: -3.4686R
- 2022: +1.8684R
- 2023: -1.6262R
- 2024: +10.7540R
- 2025: +18.0716R
- 2026 partial: +0.6203R

This is why rolling-window stability and future unseen DEMO evidence remain necessary despite the strong aggregate result.

## Decision

1. Broker-boundary transferability: **PASS**.
2. Actual cTrader cross-feed replay: **PASS**.
3. Cost stress on actual broker bars: **PASS**.
4. LIVE promotion: **NO**.
5. Risk/lot ceiling increase: **NO**.
6. Existing limited DEMO authorization for XAUUSD may remain; continue durable forward evidence collection.
7. Next confirmatory gate: frozen rolling 3-year / 5-year stability plus continued unseen forward DEMO evidence.

Workflow run: `34665457251`  
Artifact ID: `10289475568`  
Artifact SHA-256: `5876337aa7b0b87c8a9a37fc8d1bddc216271b743534a2102facdbdc45ecddca`
