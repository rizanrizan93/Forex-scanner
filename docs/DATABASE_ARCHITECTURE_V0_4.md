# Database architecture v0.4

The scanner still needs durable storage, but the database is deliberately kept
out of the latency-critical order path.

## In-memory / realtime

- latest cTrader Bid/Ask
- ARMED signal state
- spread/freshness guard
- execution queue
- duplicate in-flight claim
- connection/session health

A Supabase round trip is not required to process each quote or send each order.

## Parquet + DuckDB

- raw/history ticks when retained
- M1/M5/M15/H1/H4/D1 bars
- research feature history
- backtests and walk-forward datasets

## Supabase/Postgres

- macro and currency-strength snapshots
- scanner runs and signal audit
- broker/order event audit
- paper/demo/live trade history
- model performance and drift
- runtime heartbeats
- mobile control state (AUTO/PAUSE/emergency stop)
- non-secret broker account metadata

## Failure rule

Database outage must not create a stale or duplicated trade. New live orders
should fail closed if critical durable control state cannot be verified. Existing
broker-side SL/TP remains independent of database availability.
