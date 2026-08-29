# FX Institutional Scanner v0.1

Production-oriented forex scanner foundation for intraday trading research.

## Scope

This bootstrap implements **Phase 0 (contracts & safety)** and **Phase 1 (market-data foundation)** only.
It does **not** place live orders. There is intentionally no `order_send` path in the codebase.

Core design:

`Macro Regime -> Currency Strength -> Pair Ranking -> HTF Structure -> Liquidity/SMC -> Entry -> Guards -> Paper/Demo -> Real-Money Gate`

The later phases are specified in configuration and schema contracts, but trading logic is not enabled until data integrity is validated.

## Phase 0 implemented

- 15-pair G10 liquid universe
- canonical UTC time contract
- signal state contract
- risk limits and real-money acceptance criteria
- session definitions using real time zones (DST-aware)
- fail-closed data-source rules
- no placeholder/default-neutral values for missing evidence
- no live-order execution path

## Phase 1 implemented

- broker-native MT5 collector adapter (read-only market data)
- deterministic mock collector for tests
- UTC tick contract with Bid/Ask validation
- tick-to-bar aggregation for M1/M5/M15/H1/H4/D1
- spread statistics on every bar
- data-quality/freshness checks
- Parquet partition store adapter
- DuckDB catalog adapter
- JSONL audit fallback for environments without Arrow/DuckDB
- Supabase declarative schema (not applied to any remote project)
- test suite for contracts, aggregation, quality, sessions, and guards

## Important MT5 host constraint

The official `MetaTrader5` Python wheel is currently distributed for **Windows x86-64**. Therefore the broker-native collector should run on a Windows machine/VPS with the TMGM MT5 terminal logged in. The scanner/dashboard can run elsewhere and consume persisted data.

The MT5 adapter is **fail-closed**. If the package/terminal is unavailable it raises an explicit error; it never silently substitutes another price feed.

## Data contract

All timestamps are timezone-aware UTC.

A tick is valid only when:

- `bid > 0`
- `ask > 0`
- `ask >= bid`
- timestamp is timezone-aware
- symbol belongs to configured universe

Bar prices use the tick midpoint for research features, while raw Bid/Ask ticks remain the source of truth for execution-cost/backtest work.

## Storage design

Large raw market data:

- `data/ticks/symbol=<PAIR>/date=<YYYY-MM-DD>/*.parquet`
- `data/bars/timeframe=<TF>/symbol=<PAIR>/date=<YYYY-MM-DD>/*.parquet`

Catalog/query layer:

- DuckDB

Operational/evidence state:

- Supabase/Postgres (separate project intended)

Supabase is deliberately not mixed into the existing stock-scanner database.

## Install

Recommended Python: 3.11-3.14.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

On the Windows MT5 collector host only:

```bash
pip install -r requirements-mt5-windows.txt
```

## Run validation

```bash
pytest -q
python -m fx_scanner.cli validate-config
python -m fx_scanner.cli demo-ingest --symbol EURUSD --minutes 10
```

The demo command uses deterministic synthetic ticks and does not access a broker.

## MT5 read-only smoke test

On Windows with TMGM MT5 already installed and logged in:

```bash
python -m fx_scanner.cli mt5-smoke --symbol EURUSD --seconds 30
```

This only reads ticks. It does not place an order.

## Supabase

`supabase/schemas/fx_core.sql` is a declarative schema for a future dedicated FX Supabase project.
It enables RLS on exposed tables and revokes `anon` / `authenticated` privileges by default. Initial scanner writes are intended to come only from a trusted backend.

Do not put a service-role/secret key in GitHub or Streamlit client code.

## Real-money gate

The codebase records these acceptance criteria but Phase 0/1 cannot satisfy them yet:

- OOS win rate >= 55%
- Profit Factor >= 1.30
- Expectancy > 0.15R
- >= 250 aggregate OOS trades
- walk-forward pass
- spread/slippage stress pass
- multiple-regime pass
- demo forward-test pass

Until every mandatory gate is satisfied, readiness must remain `RESEARCH_ONLY` / `PAPER_ONLY`.
