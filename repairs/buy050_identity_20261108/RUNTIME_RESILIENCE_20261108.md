# BUY050 runtime resilience research patch (2026-11-08)
Incident: cTrader journal showed heartbeat count 20, then supervisor message "Killed" at 05:55:50 UTC and automatic restart within 10 seconds. A SIGKILL is external to managed C# catch handlers. The root cause (host OOM vs platform recycle vs other supervisor decision) is **not verified**.

## Changes
- Incremental completed-M1 cache on XAU and EUR: preserves the same full chronological candle series as the previous rebuild on append-only bars; forces rebuild on history rotation/backfill.
- Throttle human-readable full checkpoint JSON in cTrader journal from every minute to every five minutes (durable checkpoint saves / remote CAS unchanged).
- Managed heap/GC collection and uptime telemetry every minute, plus number of broker positions without protective stop. The pre-existing OpenRisk=Infinity protective block for positions without SL stays unchanged.
- Catch unexpected managed exceptions in BTC tick handler and block **new** BTC entries while allowing timer position management to continue; no broker orders in the patch.
- cTrader OnException diagnostics for subsequent managed exceptions. Cannot catch kernel SIGKILL or guarantee continuous cTrader Cloud runtime.

## Constraints and status
No change to BUY050 frozen entry/exit/SL/TP, sizing, bridge endpoint, protocol, state identity, current local/remote checkpoints or manual trades.
This is a **code candidate**, not proof of killed root cause and not a live deployment. Native build and regression must pass before merging; cTrader deployment is separately controlled by owner. No VPS systemd or nginx change.
