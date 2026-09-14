# EURAUD / GBPAUD forward-shadow activation — 2026-09-14

## Status

The two selected D1 strategies are now installed on `main` as a broker-native cTrader DEMO/read-only forward-evidence lane. This activation does **not** grant broker-order authority: `execution_eligible=false`, `execution_influence=false`, and `promotion_authority=false` remain mandatory.

## Frozen strategy identities

- EURAUD: `D1_DONCHIAN55_VOLFILTER_CHANDELIER35` — D1 EMA50/EMA200 trend alignment, Donchian-55 breakout, ATR%-vs-126-session-median volatility filter, 2 ATR initial stop reference, 3.5 ATR Chandelier trail, 120 D1 max hold.
- GBPAUD: `D1_COMPONENT_RET63_OPPOSITE_CHANDELIER3` — GBPAUD EMA200 direction plus opposite 63-session GBPUSD/AUDUSD momentum, 2 ATR initial stop reference, 3 ATR Chandelier trail, 120 D1 max hold.

## First broker-native forward evaluation

GitHub Actions run `34796601194` completed successfully on cTrader DEMO history and persisted both evaluations to durable Supabase evidence.

- EURAUD: 699 completed D1 bars evaluated. Current direction: none. Reason: `D1_VOLATILITY_FILTER_NOT_MET`. The evaluation was persisted.
- GBPAUD: 697 aligned completed D1 component bars evaluated. Current direction: none. Reason: `GBPAUD_DOWNTREND_COMPONENTS_NOT_OPPOSITE`. The evaluation was persisted.

Therefore no new trade is justified by either frozen strategy at activation time. The correct strategy behavior is `NO_TRADE` until its exact setup appears; no rule is relaxed to force an entry.

## Runtime

The scheduled workflow runs after the broker D1 close on weekdays (`17 23 * * 1-5` UTC), deduplicates by completed signal bar and strategy identity, stores forward evidence in `broker_order_events`, and writes a runtime heartbeat. It never calls the broker order-submission path.

## Validation

The activation workflow passed configuration validation, the forward-shadow authority contract, cTrader broker-history retrieval, and evidence persistence. After activation on `main`, repository CI run `34796656752` passed installation, Streamlit syntax smoke, unit tests, config contract, macro source smoke, and demo ingest.
