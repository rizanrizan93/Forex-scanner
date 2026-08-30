# FX Institutional Scanner v0.5 pre-deploy audit

## Architecture

- FP Markets cTrader: research feed only
- HFM Cent MT5: single execution venue
- automatic cross-broker failover: forbidden
- live execution default: DISABLED
- Supabase: cached control plane + asynchronous audit, outside critical path

## Findings remediated before merge

### P0 / execution-integrity

1. **Unknown broker outcome could previously permit blind retry.**
   - Fixed with persisted `uncertain_signal_ids`.
   - Once submit starts, an exception with unknown outcome quarantines the signal.
   - Explicit broker reconciliation is required before retry.

### P1

1. MT5 `SYMBOL_FILLING_*` flags were not safe to pass directly as
   `ORDER_FILLING_*` request enum values.
   - Fixed with execution-mode-aware mapping.
2. cTrader research path still exposed an execution-capable gateway.
   - Fixed with read-only `CTraderResearchFeed`; configured factory rejects
     cTrader execution.
3. Price could move between HFM reconciliation and MT5 preflight.
   - Fixed with final fresh-quote geometry and drift guard.
4. Wrong HFM account/symbol contract could silently distort Cent sizing.
   - Fixed with USC account check, 1,000-unit contract check and startup symbol
     resolution.
5. cTrader reconnect could lose spot subscriptions.
   - Fixed with automatic research-universe reload/resubscription.
6. cTrader access token expiry could stop the research feed after rotation.
   - Fixed with refresh-token flow plus atomic VPS-only rotated-token state.
7. Failed dual-stack startup could leave broker resources connected.
   - Fixed with cleanup of both execution and research connections.

### P2

1. EXECUTION_READY config advertised 50 ms while the scheduler floor was 250 ms.
   - Fixed: effective target is now consistently 250 ms.
2. Async Supabase audit could drop queued events during graceful shutdown.
   - Fixed: worker drains its bounded queue before stopping.
3. Sub-second cadence comparison had a floating-point boundary edge.
   - Fixed with a small numerical tolerance.

## Safety properties

- HFM execution is revalidated against fresh FP/HFM quotes.
- divergence/spread/chase/RR/geometry guards fail closed.
- HFM broker tick economics determine volume.
- MT5 `order_check` precedes submit.
- kill switch and cached control state are rechecked immediately before submit.
- server-side SL/TP are mandatory.
- persistent idempotency is mandatory for configured live execution.
- unknown submit outcome is not automatically retried.
- secrets are excluded from source control.
- execution remains DISABLED.

## Residual / requires real broker infrastructure

These are not represented as passed tests because credentials are not present:

- FP Markets real cTrader Open API authentication and quote smoke test
- HFM Cent real MT5 login / symbol suffix / contract-spec verification
- Windows VPS end-to-end latency benchmark
- actual FP-vs-HFM divergence distribution and threshold calibration
- spread/slippage/commission stress with broker observations
- full HFM M5 SMC/ICT pattern parity; v0.5 revalidation is intentionally
  execution-geometry reconciliation
- demo forward validation before any real-money consideration

No real-money readiness is claimed.
