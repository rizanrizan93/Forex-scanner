# Architecture v0.1

```text
TMGM MT5 terminal (Windows collector host)
          |
          | read-only ticks/rates
          v
MarketDataCollector
          |
          +--> Data Contract / Quality Gate --X--> BLOCK
          |
          v
Partitioned Parquet data lake
          |
          +--> DuckDB research/query layer
          |
          +--> bar aggregation M1/M5/M15/H1/H4/D1
          |
          v
Future Phase 2+ engines
Macro -> Currency Strength -> Pair Ranking -> SMC/ICT -> Execution Guards
          |
          v
Paper/Demo only until acceptance gate passes
```

Operational states and research evidence can be persisted to a separate Supabase/Postgres project.

## Security boundaries

- raw broker/MT5 credentials: collector host environment only
- Supabase service-role key: trusted backend only
- GitHub: no secrets
- browser/dashboard: no privileged key
- stock-scanner Supabase projects: not reused

## Latency tiers

- tick/seconds: Bid, Ask, spread, active setup later
- M1: microstructure features
- M5: entry trigger later
- M15: setup formation later
- H1/H4: market structure later
- macro: event-driven later
- COT: weekly later
