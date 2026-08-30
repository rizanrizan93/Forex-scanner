# FX Institutional Scanner v0.4

Production-oriented forex scanner for intraday research, mobile-controlled automation, and broker-agnostic execution.

**Preferred execution backend: cTrader Open API**  
**Fallback backend: MT5 (explicit operator selection only)**  
**Execution default: `DISABLED`**

## Target operating model

The phone is the **control and monitoring plane**, not the 24/5 execution host.

```text
Phone / cTrader mobile / future dashboard
              |
              | approve / pause / kill / monitor
              v
        VPS / cloud worker
              |
      FX Scanner Core
              |
 Macro -> Pair Ranking -> SMC/ICT -> Risk/Guards
              |
       BrokerGateway
          /       \
   cTrader       MT5
  preferred     fallback
```

A home PC does not need to remain on when the cTrader backend is used. The VPS keeps the scanner, streaming connection, execution router, risk engine, and health supervisor alive.

## v0.4 broker architecture

The trading core no longer depends directly on MT5.

`BrokerGateway` normalizes:

- account/equity/margin state
- symbol and quote state
- preflight validation
- order submission and response
- order identifiers and executed volume

Backends:

- **cTrader Open API** — preferred, event-driven, server/VPS friendly
- **MT5** — compatibility fallback for brokers that only expose MT5

Automatic failover from cTrader to MT5 is deliberately forbidden. Switching brokers/backends is an explicit operator action to prevent duplicate positions or accidental cross-broker exposure.

See `docs/CTRADER_V0_4.md`.

## Runtime cadence

- heavy macro + pair ranking: 15 minutes
- shortlisted setup watcher: 60 seconds
- ARMED execution watcher: 2 seconds
- open-position monitor: 2 seconds

The runtime supervisor uses bounded concurrent workers so a slow heavy scan cannot block the execution watcher.

## Runtime safety

- non-overlap lock per watcher
- monotonic/deadline scheduling
- late-cycle skip; no catch-up storm
- bounded concurrent supervisor
- bounded FIFO execution queue
- dedicated single execution worker
- queue backpressure
- reconnect/backoff + circuit breaker
- health/stuck-worker telemetry
- atomic in-flight duplicate-signal claim
- kill-switch and signal-age recheck immediately before submit
- server-side SL/TP requirement
- broker preflight before submit
- cTrader quote freshness gate
- live environment + account allowlist gates

## Execution modes

- `DISABLED` — default
- `SIMULATION`
- `CONFIRM_TO_TRADE`
- `AUTO`

`AUTO` cannot trade until all independent live gates are deliberately opened.

## cTrader setup

Install the official Open API Python SDK on the VPS:

```bash
pip install -r requirements-ctrader.txt
```

After a cTrader Open API application is registered/approved and a demo account is available, provide secrets only as environment variables:

```text
CTRADER_CLIENT_ID
CTRADER_CLIENT_SECRET
CTRADER_ACCESS_TOKEN
CTRADER_REFRESH_TOKEN
CTRADER_ACCOUNT_ID
```

Do not commit those values.

The initial target should remain **Pepperstone cTrader demo**, then progress through simulation and confirm-to-trade before any automatic demo execution.

## Database architecture

The scanner **still needs a database**, especially for phone-only control, auditability, macro history, and performance validation. But the database is not placed in the critical quote/order latency path.

```text
Realtime critical path
cTrader stream -> in-memory state -> guards -> broker execution

Historical research
Parquet -> DuckDB

Durable operational/control state
Supabase/Postgres
```

Supabase stores durable state such as:

- macro/currency-strength snapshots
- pair rankings and signals
- broker/order audit events
- paper/demo/live performance
- mobile AUTO/PAUSE/EMERGENCY control state
- runtime heartbeats and health
- model drift/acceptance evidence

Raw tick history should stay in Parquet/DuckDB rather than being written tick-by-tick to Supabase.

See `docs/DATABASE_ARCHITECTURE_V0_4.md`.

## Data foundation

- 15 liquid G10 pairs
- canonical UTC timestamps
- Bid/Ask contract validation
- M1/M5/M15/H1/H4/D1 aggregation
- spread statistics
- freshness/duplicate/non-monotonic checks
- DST-aware sessions
- Parquet + DuckDB historical adapters
- isolated Supabase operational schema

## Install core

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Optional cTrader backend:

```bash
pip install -r requirements-ctrader.txt
```

Optional Windows MT5 fallback:

```bash
pip install -r requirements-mt5-windows.txt
```

## Validation

```bash
pytest -q
python -m fx_scanner.cli validate-config
python -m fx_scanner.cli demo-ingest --symbol EURUSD --minutes 10
python -m fx_scanner.cli runtime-smoke --seconds 86400
```

## Live progression

Do not jump directly to `AUTO`.

```text
DISABLED
-> SIMULATION
-> CONFIRM_TO_TRADE (cTrader demo)
-> AUTO (cTrader demo)
-> forward validation
-> real-money acceptance gate
```

Real-money acceptance remains at minimum:

- OOS win rate >= 55%
- Profit Factor >= 1.30
- positive robust expectancy
- walk-forward pass
- spread/slippage stress pass
- multi-regime pass
- demo forward-test pass

No real-money readiness is claimed at v0.4.


## Dedicated Supabase project

The operational database is provisioned and schema-initialized:

- project: `Forex scanner`
- project ref: `fotzcxjeypmjldhvfskt`
- region: `ap-southeast-1` (Singapore)
- URL: `https://fotzcxjeypmjldhvfskt.supabase.co`

The repository contains no backend secret. On the controlled VPS set:

```text
SUPABASE_URL=https://fotzcxjeypmjldhvfskt.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
```

Prefer the modern Supabase secret key. The legacy
`SUPABASE_SERVICE_ROLE_KEY` is accepted only as a fallback.

The control-plane refresh worker performs Supabase network I/O outside the
execution path. The router only reads a fresh in-memory cache. Missing/stale
control state, `emergency_stop=true`, `new_orders_enabled=false`, or a
database/runtime execution-mode mismatch blocks every new live order.

The bootstrap database state is deliberately fail-closed:

```text
execution_mode       DISABLED
new_orders_enabled   false
emergency_stop       true
```
