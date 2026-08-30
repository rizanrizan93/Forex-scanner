# FX Institutional Scanner v0.7

Production-oriented forex scanner foundation with a **dual-feed / single-execution** design.

**Research feed:** FP Markets cTrader Open API  
**Execution venue:** HFM Cent MT5  
**Execution default:** `DISABLED`

## Operating model

The Android phone is the control/monitoring surface. A controlled VPS is the 24/5 runtime host.

```text
Global/macro data
       |
FP Markets cTrader ------------------+
(read-only research feed)            |
                                     v
                         Scanner / ranking / SMC-ICT
                                     |
                              signal candidate
                                     |
                                     v
                        HFM execution revalidation
                           (warm MT5 connection)
                                     |
                  stale/spread/divergence/chase/RR/risk
                                     |
                              pass -> MT5 order
                                     |
                              HFM Cent account

Supabase -> cached control state + async audit (not quote/order latency path)
Android  -> monitor / future approve / pause / emergency controls
```

There is **no automatic cTrader -> MT5 failover** and cTrader is configured
`RESEARCH_ONLY`. The configured factory refuses to build cTrader as an execution
backend.

## v0.6 decision engine foundation

The repository now contains deterministic, testable decision primitives:

- eight-factor currency macro scoring with explicit missing/invalid coverage
- relative macro edge by base vs quote currency
- normalized currency-strength aggregation across the configured 15-pair universe
- pair ranking using 55% macro / 30% technical / 15% cross-asset edge
- evidence coverage propagated from macro, technical, and cross-asset inputs
- ATR, displacement, FVG, swing structure, BOS, liquidity sweep/reclaim, and MSS confirmation
- 0..100 conviction scoring with explicit missing-component coverage
- state mapping: `NO_TRADE -> WATCH -> SETUP_FORMING -> ARMED -> EXECUTION_READY`
- canonical hard guards that fail closed when a required guard input is missing or invalid
- internal pair-direction and pair-coverage guards

Missing evidence is never converted into a successful neutral observation. A
high score cannot override a hard guard, a neutral pair direction, or inadequate
evidence coverage.

v0.6 established the deterministic decision engine. v0.7 adds the first
provider/live-data orchestration layer around that engine.

## v0.7 provider and live-data orchestration

Provider evidence now has explicit semantics:

- `AVAILABLE`, `PARTIAL`, `MISSING`, `STALE`, `INVALID`, `ERROR`, `NOT_APPLICABLE`
- zero is distinct from missing
- source URL, series ID, official-source flag, observation time and fetch time
- max-age freshness with stale values preserved for audit but excluded from decisions
- typed provider error categories
- positive, negative and stale TTL caching
- numeric quorum with conflict detection
- exact-single-series guards; wildcard/multi-series inputs fail closed
- HTTPS + canonical-host configuration and redirect blocking

The first keyless official adapters are:

- ECB Data Portal SDMX/CSV
- Bank of Canada Valet JSON

The macro provider pipeline normalizes source observations only through explicit
normalizers. Missing history does **not** become a neutral zero. Provider/factor
coverage and provenance are retained and can be persisted to
`currency_macro_state` in Supabase.

v0.7 also contains a typed high-impact economic-event model and deterministic
news-window evaluator for producing `NEWS_BLOCK`. A full multi-country
economic-calendar ingestion provider is not yet claimed.

Manual network smoke tests:

```bash
python -m fx_scanner.cli provider-smoke --series ECB_EURUSD_REFERENCE
python -m fx_scanner.cli provider-smoke --series BOC_POLICY_RATE
```

These are intentionally not part of mandatory CI because external provider
availability must not determine whether the codebase builds.

## HFM Cent execution contract

Startup fails closed unless the execution account and symbols match the configured
Cent contract:

- account currency: `USC`
- expected FX contract size: `1,000` units per Cent lot
- canonical symbols are resolved to broker symbols (for example `EURUSDc`) using
  explicit mapping or configured suffix candidates
- ambiguous or non-matching symbols block startup
- position sizing uses HFM-provided tick size, tick value, min/max volume and
  volume step; standard-lot economics are never hard-coded

Actual symbol names and contract metadata must still be verified against the
real HFM demo account before enabling any execution mode.

## Fast execution-side revalidation

The FP Markets signal is never copied blindly to HFM. Immediately before MT5
preflight the runtime checks:

- fresh cTrader research Bid/Ask
- fresh HFM MT5 Bid/Ask
- cross-broker mid-price divergence
- HFM spread and spread divergence
- entry drift / do-not-chase
- SL/entry/TP geometry
- minimum RR
- HFM Cent account currency and contract size
- HFM tick-economics position sizing
- internal revalidation latency ceiling

MT5 then takes a fresh quote **again** during broker preflight and blocks if the
price has moved too far from the revalidated entry.

This is intentionally a fast execution-geometry reconciliation. It does not
claim to recompute the complete SMC/ICT strategy on HFM M5 bars.

## Cadence

- heavy macro / pair ranking: 15 minutes
- setup watcher: 60 seconds
- WATCH: 2 seconds
- SETUP_FORMING: 1 second
- ARMED: 250 ms
- EXECUTION_READY: 250 ms
- open-position monitor: 2 seconds

The 250 ms figure is an engineering scheduler target, not a guaranteed
broker-network order latency.

## Live safety

Live orders require all configured gates:

- mode is not `DISABLED`
- environment live-enable phrase
- broker account allowlist
- local kill switch
- fresh cached Supabase control state
- Supabase mode agreement / new-orders enabled / emergency-stop clear
- dual-feed revalidation
- MT5 broker preflight / `order_check`
- server-side SL and TP
- persistent signal idempotency state

If a broker submission crosses the side-effect boundary but its response is
lost, that signal is persisted as **uncertain**. It cannot be retried until
broker order/position reconciliation explicitly resolves the outcome.

## cTrader research reliability

The cTrader research facade exposes quotes/symbol information only; it exposes
no order submission method. On reconnect it reloads the research universe and
restores spot subscriptions.

cTrader access-token rotation is supported. Rotated access and refresh tokens
are written atomically to the VPS-only token-state file and the `state/`
directory is git-ignored.

Required VPS secret/state variables include:

```text
CTRADER_CLIENT_ID
CTRADER_CLIENT_SECRET
CTRADER_ACCESS_TOKEN
CTRADER_REFRESH_TOKEN
CTRADER_TOKEN_STATE_PATH
CTRADER_ACCOUNT_ID

MT5_TERMINAL_PATH
MT5_LOGIN
MT5_SERVER
MT5_PASSWORD

SUPABASE_URL
SUPABASE_SECRET_KEY

FX_IDEMPOTENCY_STATE_PATH
```

Never commit real values.

## Storage

- realtime quote/order state: memory on VPS
- history/research: Parquet + DuckDB
- durable control/audit: dedicated Supabase project

The Supabase project is `Forex scanner` in Singapore
(`fotzcxjeypmjldhvfskt`). Supabase network I/O is isolated from the
order-critical path. The database bootstrap remains:

```text
execution_mode       DISABLED
new_orders_enabled   false
emergency_stop       true
```

## Install

Core:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

cTrader research backend:

```bash
pip install -r requirements-ctrader.txt
```

HFM MT5 execution host requires Windows and:

```bash
pip install -r requirements-mt5-windows.txt
```

## Validation

```bash
pytest -q
python -m fx_scanner.cli validate-config
python -m fx_scanner.cli demo-ingest --symbol EURUSD --minutes 10
python -m fx_scanner.cli runtime-smoke --seconds 86400
# Optional external-network checks:
python -m fx_scanner.cli provider-smoke --series ECB_EURUSD_REFERENCE
python -m fx_scanner.cli provider-smoke --series BOC_POLICY_RATE
```

## Progression

Do not enable real-money execution from this repository state.

```text
DISABLED
-> SIMULATION
-> dual-broker live-feed smoke test
-> CONFIRM_TO_TRADE on demo
-> AUTO on demo
-> forward validation / cost & latency calibration
-> real-money acceptance review
```

Research acceptance remains at minimum: OOS win rate >=55%, Profit Factor
>=1.30, positive robust expectancy, walk-forward pass, spread/slippage stress
pass, multi-regime pass, and demo forward-test pass.

**Real-money readiness is not claimed at v0.7.**
