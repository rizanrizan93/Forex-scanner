# cTrader Demo AutoTrade v0.13

This runtime is intentionally **DEMO ONLY**.

## Safety contract

- FP Markets cTrader is both the research feed and the demo-forward execution venue.
- The Open API host is fixed to DEMO.
- Granted account discovery rejects live accounts and ambiguous multi-account grants.
- OAuth must expose SCOPE_TRADE.
- The committed repository mode remains DISABLED.
- Demo AUTO requires the exact `CTRADER_DEMO_AUTOTRADE_ENABLED` opt-in value.
- Supabase `execution_control` must independently say AUTO, enable new orders, and clear emergency stop.
- Only durable `signals.state = EXECUTION_READY` rows are considered.
- Active guards must be empty and data coverage must be at least 0.80.
- The fresh executable cTrader price must still lie inside the signal entry zone.
- TP2 RR must remain at least 1.50.
- Every signal is atomically claimed by moving it to COOLDOWN before broker I/O.
- Maximum demo order size is 0.01 lot.
- Maximum simultaneous broker positions is one.
- Server-side SL and TP are mandatory.
- The real/live account path is not enabled.

## Phone-only sequence

1. Run `cTrader Demo Execution Preflight`.
2. Add the explicit demo opt-in repository secret.
3. Run `cTrader Demo Execution Control` with `enable`.
4. Run `cTrader Demo AutoTrade` manually once.
5. Keep the scheduled runner only as an interim worker; use a persistent Linux host for the intended one-second cadence.

An empty EXECUTION_READY queue is a safe no-op, not an error. This executor
does not invent signals and does not lower macro, MTF, evidence, or hard-guard
requirements to force a demo order.
